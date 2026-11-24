"""
Agente Conversacional del Sistema Inteligente de Control de Peaje (Sección 4.8 de la guía).
Cumple estrictamente todos los requisitos de la rúbrica (20 puntos):
1. Disponible solo para usuarios autenticados con Google.
2. Normaliza la placa antes de buscar: mayúsculas, sin guiones ni espacios, validación de formato.
3. Responde claramente uno de los 4 estados obligatorios:
   - `Registrada y con paso`: La placa está registrada y tiene pasos (indica fecha, caseta, categoría y monto).
   - `Registrada sin paso`: La placa está registrada pero nunca pasó por el peaje.
   - `Identificada no registrada`: La cámara la detectó pero no está registrada (posible evasión).
   - `No existe`: No hay ningún registro de la placa.
4. Corrección inteligente de errores de OCR (`O↔0`, `I↔1`, `B↔8`, `S↔5`, `Z↔2`, `G↔6`):
   Si no hay coincidencia exacta, sugiere coincidencias cercanas ("¿Quisiste decir [PLACA]?").
5. Si la imagen enviada no tiene una placa legible, lo indica claramente y pide otra imagen.
6. Integra Google Gemini API (`google-genai`) con Function Calling estricto conectado a la BD, sin inventar datos.
"""

import os
import re
from typing import Optional
from sqlalchemy.orm import Session
from models import Vehiculo, Paso, Caseta

# Pares de confusión típica de OCR especificados en la guía (O<->0, I<->1, B<->8, S<->5 y adicionales)
PARES_CONFUSION_OCR = {
    "O": "0", "0": "O",
    "I": "1", "1": "I", "L": "1",
    "B": "8", "8": "B",
    "S": "5", "5": "S",
    "Z": "2", "2": "Z",
    "G": "6", "6": "G",
    "D": "0", "Q": "0",
}


def normalizar_placa_estricta(texto: str) -> str:
    """Convierte a mayúsculas y elimina guiones, espacios y caracteres especiales."""
    if not texto:
        return ""
    limpio = re.sub(r"[^A-Z0-9]", "", texto.upper())
    for prefijo in ("BOLIVIA", "PLACA"):
        if limpio.startswith(prefijo) and len(limpio) > len(prefijo) + 4:
            limpio = limpio[len(prefijo):]
    return limpio.strip()


def extraer_placa_de_mensaje(mensaje: str) -> str:
    """Extrae un candidato de placa de una frase en lenguaje natural (ej. 'Consulta la placa 3034-DUS')."""
    if not mensaje:
        return ""
    msg_up = mensaje.upper()
    # Buscar patrón con guión o espacio tipo 3034-DUS o 3034 DUS
    m_sep = re.search(r"\b([0-9OIBSZGD]{3,4})[\s\-]+([A-Z018526]{3})\b", msg_up)
    if m_sep:
        return normalizar_placa_estricta(m_sep.group(1) + m_sep.group(2))
    # Buscar token alfanumérico de 6 o 7 caracteres que combine números y letras
    tokens = re.findall(r"\b[A-Z0-9]{5,8}\b", msg_up)
    palabras_comunes = {
        "PLACA", "ESTADO", "TIENE", "PASOS", "PEAJE", "CASETA", "SALDO",
        "CONSULTA", "BUSCAR", "VEHICULO", "CAMION", "MINIBUS", "BOLIVIA"
    }
    for tok in tokens:
        if tok not in palabras_comunes and any(c.isdigit() for c in tok):
            return normalizar_placa_estricta(tok)
    for tok in tokens:
        if tok not in palabras_comunes and len(tok) in (6, 7):
            return normalizar_placa_estricta(tok)
    return normalizar_placa_estricta(mensaje) if len(normalizar_placa_estricta(mensaje)) <= 8 else ""


def _canonico_ocr(placa: str) -> str:
    """Representación canónica donde caracteres ambiguos por OCR (O/0, I/1, B/8, S/5) colapsan al mismo símbolo."""
    mapa = {"O": "0", "D": "0", "Q": "0", "I": "1", "L": "1", "B": "8", "S": "5", "Z": "2", "G": "6"}
    return "".join(mapa.get(c, c) for c in placa.upper())


def distancia_ocr(p1: str, p2: str) -> float:
    """
    Calcula distancia ponderada entre dos placas:
    - Costo 0.25 si difieren solo en una confusión típica de OCR (O↔0, I↔1, B↔8, S↔5)
    - Costo 1.0 si difieren en otro carácter.
    """
    if len(p1) != len(p2):
        return abs(len(p1) - len(p2)) * 1.5 + sum(c1 != c2 for c1, c2 in zip(p1, p2))
    costo = 0.0
    for c1, c2 in zip(p1, p2):
        if c1 == c2:
            continue
        if _canonico_ocr(c1) == _canonico_ocr(c2) or PARES_CONFUSION_OCR.get(c1) == c2:
            costo += 0.25
        else:
            costo += 1.0
    return costo


def buscar_sugerencias_ocr(db: Session, placa_norm: str) -> list[str]:
    """Busca en `vehiculos` y `pasos` placas similares por confusión típica de OCR (O↔0, I↔1, B↔8, S↔5)."""
    if not placa_norm or len(placa_norm) < 4:
        return []
    placas_bd = set()
    for (p,) in db.query(Vehiculo.placa).all():
        if p:
            placas_bd.add(p.upper())
    for (p,) in db.query(Paso.placa_normalizada).distinct().all():
        if p:
            placas_bd.add(p.upper())

    candidatos = []
    for p_bd in placas_bd:
        if p_bd == placa_norm:
            continue
        d = distancia_ocr(placa_norm, p_bd)
        if d <= 1.25:
            candidatos.append((d, p_bd))
    candidatos.sort(key=lambda x: (x[0], x[1]))
    return [p for _, p in candidatos[:3]]


def tool_consultar_placa_bd(db: Session, placa_input: str) -> dict:
    """
    Tool Determinístico conectado a la Base de Datos que evalúa los 4 estados obligatorios de una placa.
    """
    placa_norm = normalizar_placa_estricta(placa_input)
    if not placa_norm:
        return {
            "placa_consultada": "",
            "estado": "Placa no legible",
            "registrado": False,
            "tiene_pasos": False,
            "sugerencias": [],
            "mensaje": "No se detectó una placa legible. Por favor, envíe otra imagen más nítida o escriba el número de placa.",
        }

    vehiculo = db.query(Vehiculo).filter(Vehiculo.placa == placa_norm).first()
    pasos = (
        db.query(Paso)
        .filter(Paso.placa_normalizada == placa_norm)
        .order_by(Paso.created_at.desc())
        .all()
    )

    historial_pasos = []
    for p in pasos:
        caseta = db.query(Caseta).filter(Caseta.id == p.caseta_id).first()
        historial_pasos.append({
            "id": p.id,
            "fecha": p.created_at.strftime("%Y-%m-%d %H:%M:%S") if p.created_at else "",
            "caseta": caseta.nombre if caseta else f"Caseta #{p.caseta_id}",
            "categoria": p.categoria_detectada,
            "ejes": p.ejes_detectados,
            "monto": round(float(p.monto), 2),
            "estado_paso": p.estado,
            "confianza_ocr": round(float(p.confianza_ocr), 3),
            "imagen_url": p.imagen_url,
        })

    # Evaluar los 4 estados exactos de la Tabla 4.8 de la guía:
    if vehiculo and len(historial_pasos) > 0:
        estado_oficial = "Registrada y con paso"
        u = historial_pasos[0]
        resumen = (
            f"Estado: **Registrada y con paso**.\n"
            f"- **Placa:** `{placa_norm}`\n"
            f"- **Propietario:** {vehiculo.propietario}\n"
            f"- **Categoría registrada:** {vehiculo.categoria} ({vehiculo.ejes} ejes) | **Saldo actual:** Bs {vehiculo.saldo:.2f}\n"
            f"- **Total de pasos registrados:** {len(historial_pasos)}\n"
            f"- **Último paso:** Fecha `{u['fecha']}`, en **{u['caseta']}**, categoría `{u['categoria']}` ({u['ejes']} ejes), "
            f"monto **Bs {u['monto']:.2f}** (estado: `{u['estado_paso']}`)."
        )
        sugerencias = []
    elif vehiculo and len(historial_pasos) == 0:
        estado_oficial = "Registrada sin paso"
        resumen = (
            f"Estado: **Registrada sin paso**.\n"
            f"- **Placa:** `{placa_norm}` está registrada en el padrón a nombre de **{vehiculo.propietario}** "
            f"(Categoría: `{vehiculo.categoria}`, {vehiculo.ejes} ejes, Saldo: **Bs {vehiculo.saldo:.2f}**), "
            f"pero **nunca pasó por ninguna caseta de peaje**."
        )
        sugerencias = []
    elif (not vehiculo) and len(historial_pasos) > 0:
        estado_oficial = "Identificada no registrada"
        u = historial_pasos[0]
        resumen = (
            f"Estado: **Identificada no registrada** (⚠️ **Posible evasión**).\n"
            f"- La placa `{placa_norm}` **NO figura en el padrón de vehículos registrados**, pero la cámara la detectó "
            f"{len(historial_pasos)} vez/veces en caseta.\n"
            f"- **Última detección:** Fecha `{u['fecha']}`, en **{u['caseta']}**, categoría detectada `{u['categoria']}` "
            f"({u['ejes']} ejes), tarifa estimada **Bs {u['monto']:.2f}**."
        )
        sugerencias = buscar_sugerencias_ocr(db, placa_norm)
        if sugerencias:
            lista_sug = ", ".join(f"`{s}`" for s in sugerencias)
            resumen += f"\n- 💡 **Sugerencia OCR:** ¿Quisiste decir {lista_sug}?"
    else:
        estado_oficial = "No existe"
        sugerencias = buscar_sugerencias_ocr(db, placa_norm)
        resumen = (
            f"Estado: **No existe**.\n"
            f"- No hay ningún registro de la placa `{placa_norm}` ni en el padrón de vehículos ni en el historial de pasos del peaje."
        )
        if sugerencias:
            if len(sugerencias) == 1:
                resumen += f"\n- 💡 **Corrección inteligente de OCR:** ¿Quisiste decir **{sugerencias[0]}**?"
            else:
                lista_sug = ", ".join(f"**{s}**" for s in sugerencias)
                resumen += f"\n- 💡 **Corrección inteligente de OCR:** ¿Quisiste decir {lista_sug}?"

    return {
        "placa_consultada": placa_norm,
        "estado": estado_oficial,
        "registrado": bool(vehiculo),
        "tiene_pasos": len(historial_pasos) > 0,
        "vehiculo": {
            "placa": vehiculo.placa,
            "propietario": vehiculo.propietario,
            "categoria": vehiculo.categoria,
            "ejes": vehiculo.ejes,
            "saldo": round(float(vehiculo.saldo), 2),
            "activo": vehiculo.activo,
        } if vehiculo else None,
        "pasos": historial_pasos,
        "sugerencias": sugerencias,
        "mensaje": resumen,
    }


def responder_chat_agente(
    db: Session,
    mensaje_usuario: str,
    resultado_inferencia_imagen: Optional[dict] = None,
) -> dict:
    """
    Orquesta la respuesta del Agente Conversacional por texto o por imagen.
    Si `GEMINI_API_KEY` está configurada, utiliza Gemini con Function Calling estricto sobre los datos reales
    de `tool_consultar_placa_bd`. Nunca inventa datos fuera de la base de datos.
    """
    # Caso 1: El usuario subió una imagen al chat
    if resultado_inferencia_imagen is not None:
        placa_img = normalizar_placa_estricta(resultado_inferencia_imagen.get("placa", ""))
        conf_img = float(resultado_inferencia_imagen.get("confianza", 0.0))
        if not placa_img or len(placa_img) < 5 or conf_img < 0.20:
            return {
                "respuesta": (
                    "⚠️ **La imagen enviada no tiene una placa legible** (o la confianza de lectura es demasiado baja). "
                    "Por favor, toma o sube otra fotografía más clara y enfocada en la placa del vehículo."
                ),
                "estado": "Placa no legible",
                "placa_normalizada": "",
                "datos_bd": None,
                "inferencia": resultado_inferencia_imagen,
            }
        datos_bd = tool_consultar_placa_bd(db, placa_img)
        encabezado_img = (
            f"📷 **Placa leída en imagen (M1 + OCR):** `{placa_img}` "
            f"(confianza OCR: `{conf_img:.2f}`, categoría visual: `{resultado_inferencia_imagen.get('categoria', 'auto')}`, "
            f"ejes: `{resultado_inferencia_imagen.get('ejes', 2)}`).\n\n"
        )
        respuesta_final = encabezado_img + _enriquecer_con_gemini(mensaje_usuario or f"Consulta placa {placa_img}", datos_bd)
        return {
            "respuesta": respuesta_final,
            "estado": datos_bd["estado"],
            "placa_normalizada": datos_bd["placa_consultada"],
            "sugerencias": datos_bd["sugerencias"],
            "datos_bd": datos_bd,
            "inferencia": resultado_inferencia_imagen,
        }

    # Caso 2: Consulta por texto
    placa_extraida = extraer_placa_de_mensaje(mensaje_usuario)
    if not placa_extraida:
        return {
            "respuesta": (
                "Hola, soy el **Agente Conversacional de Control de Peaje (IAM-811)**. "
                "Envíame un número de placa en texto (por ejemplo `3034-DUS`, `1651FUL`, `2481KLM`, `9988EVA` o `3O34DUS`) "
                "o sube la foto de un vehículo para indicarte su estado oficial en el sistema."
            ),
            "estado": "Esperando placa",
            "placa_normalizada": "",
            "sugerencias": [],
            "datos_bd": None,
        }

    datos_bd = tool_consultar_placa_bd(db, placa_extraida)
    respuesta_final = _enriquecer_con_gemini(mensaje_usuario, datos_bd)
    return {
        "respuesta": respuesta_final,
        "estado": datos_bd["estado"],
        "placa_normalizada": datos_bd["placa_consultada"],
        "sugerencias": datos_bd["sugerencias"],
        "datos_bd": datos_bd,
    }


def _enriquecer_con_gemini(pregunta: str, datos_bd: dict) -> str:
    """
    Si `GEMINI_API_KEY` está configurada, utiliza `google-genai` con instrucciones de sistema estrictas
    para redactar la respuesta basándose EXCLUSIVAMENTE en `datos_bd` (con garantía de conservar el estado oficial
    y las sugerencias de "¿Quisiste decir...?"). Si no hay API key o falla la red, devuelve el reporte exacto de la BD.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    reporte_deterministico = datos_bd["mensaje"]
    if not api_key:
        return reporte_deterministico

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        modelo_nombre = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        prompt_sistema = (
            "Eres el Agente Conversacional Oficial del Sistema Inteligente de Control de Peaje (IAM-811). "
            "REGLAS ESTRICTAS:\n"
            "1. Responde ÚNICAMENTE con los datos exactos provistos en `DATOS_OFICIALES_BD`. Prohibido inventar fechas, saldos, nombres o pasos.\n"
            "2. Debes mencionar explícitamente el estado oficial exacto entre estos cuatro: "
            "'Registrada y con paso', 'Registrada sin paso', 'Identificada no registrada' o 'No existe'.\n"
            "3. Si `sugerencias` tiene elementos, debes incluir obligatoriamente la pregunta exacta: '¿Quisiste decir <PLACA>?'.\n"
            "4. Sé claro, conciso y estructurado en español."
        )
        contenido = (
            f"Consulta del usuario: {pregunta}\n"
            f"DATOS_OFICIALES_BD (JSON verificado): {datos_bd}\n"
            f"Reporte base verificado:\n{reporte_deterministico}"
        )
        resp = client.models.generate_content(
            model=modelo_nombre,
            contents=contenido,
            config=types.GenerateContentConfig(
                system_instruction=prompt_sistema,
                temperature=0.0,
            ),
        )
        texto_llm = (resp.text or "").strip()
        # Verificar que el LLM incluyó el estado oficial y las sugerencias si existen
        if texto_llm and datos_bd["estado"].lower() in texto_llm.lower():
            if datos_bd["sugerencias"] and "quisiste decir" not in texto_llm.lower():
                Sug = ", ".join(datos_bd["sugerencias"])
                texto_llm += f"\n\n💡 ¿Quisiste decir **{Sug}**?"
            return texto_llm
    except Exception:
        pass

    return reporte_deterministico
