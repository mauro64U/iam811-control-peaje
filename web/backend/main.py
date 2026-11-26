"""
Backend Web Principal + API REST Documentada (Swagger/OpenAPI) + Tiempo Real (SSE/WS) + Agente Conversacional
Sistema Inteligente de Control de Peaje (IAM-811)

Implementa todas las rutas exigidas en la Sección 4.5 de la guía del laboratorio:
- POST /api/v1/auth/google
- POST /api/v1/pasos/frame
- POST /api/v1/placas/consultar
- POST /api/v1/placas/consultar-imagen
- GET  /api/v1/placas/{placa}/historial
- GET  /api/v1/casetas/{id}/resumen
- POST /api/v1/agente/chat

Además de las rutas para las 6 páginas del Panel Web en Tiempo Real (Vehículos CRUD, Pasos, Alertas, Estado/INFERENCE_URL, Stream SSE).
"""

import os
import time
import uuid
import base64
import shutil
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional
import httpx
from fastapi import FastAPI, Depends, File, UploadFile, Form, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import Base, engine, get_db, SessionLocal
from models import Usuario, Vehiculo, Caseta, Tarifa, Paso, Alerta, Configuracion
from seed import ejecutar_seed, calcular_tarifa_peaje
from auth import verificar_token_google, crear_token_sesion, obtener_usuario_actual, exigir_rol_admin
from realtime import gestor_rt
from agent import normalizar_placa_estricta, tool_consultar_placa_bd, responder_chat_agente

# Crear tablas e inicializar seed automático
Base.metadata.create_all(bind=engine)
with SessionLocal() as _db_init:
    ejecutar_seed(_db_init)

DIR_BASE = os.path.dirname(os.path.abspath(__file__))
DIR_EVIDENCIAS = os.path.join(DIR_BASE, "evidencias")
os.makedirs(DIR_EVIDENCIAS, exist_ok=True)

# Copiar las fotografías reales de `Placas_en_mi_caso` a `evidencias/` si están disponibles para mostrarlas en vivo
DIR_PLACAS_PROPIAS = os.path.abspath(os.path.join(DIR_BASE, "..", "..", "..", "Placas_en_mi_caso"))
if os.path.isdir(DIR_PLACAS_PROPIAS):
    for archivo in os.listdir(DIR_PLACAS_PROPIAS):
        if archivo.lower().endswith((".jpg", ".jpeg", ".png")):
            orig = os.path.join(DIR_PLACAS_PROPIAS, archivo)
            dest = os.path.join(DIR_EVIDENCIAS, archivo)
            if not os.path.exists(dest):
                try:
                    shutil.copy(orig, dest)
                except Exception:
                    pass

app = FastAPI(
    title="IAM-811 Sistema Inteligente de Control de Peaje - API REST",
    description=(
        "API REST oficial del Sistema Inteligente de Control de Peaje con autenticación exclusiva Google OAuth 2.0, "
        "conexión dinámica a Google Colab (`INFERENCE_URL`), actualización en tiempo real (SSE/WebSockets) y Agente Conversacional."
    ),
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/evidencias", StaticFiles(directory=DIR_EVIDENCIAS), name="evidencias")


# ==================== ESQUEMAS PYDANTIC ====================

class GoogleAuthRequest(BaseModel):
    token: Optional[str] = None
    id_token: Optional[str] = None
    credential: Optional[str] = None


class ConsultaPlacaTextoRequest(BaseModel):
    placa: str


class ChatAgenteRequest(BaseModel):
    mensaje: str


class VehiculoCreateUpdate(BaseModel):
    placa: str
    propietario: str
    categoria: str
    ejes: int = 2
    saldo: float = 0.0
    activo: bool = True


class ConfigInferenceRequest(BaseModel):
    inference_url: str
    inference_api_token: Optional[str] = ""


class UsuarioCreateRequest(BaseModel):
    email_google: str
    nombre: str
    rol: str = "operador"
    activo: bool = True


# ==================== UTILIDADES DE INFERENCIA REMOTA (COLAB) ====================

def obtener_inference_config(db: Session) -> tuple[str, str]:
    cfg_url = db.query(Configuracion).filter(Configuracion.clave == "INFERENCE_URL").first()
    cfg_tok = db.query(Configuracion).filter(Configuracion.clave == "INFERENCE_API_TOKEN").first()
    url = (cfg_url.valor if cfg_url and cfg_url.valor else os.environ.get("INFERENCE_URL", "")).strip().rstrip("/")
    tok = (cfg_tok.valor if cfg_tok and cfg_tok.valor else os.environ.get("INFERENCE_API_TOKEN", "")).strip()
    return url, tok


async def llamar_endpoint_inferencia_colab(db: Session, datos_imagen: bytes, nombre_archivo: str = "frame.jpg") -> dict:
    """
    Envía el frame al único endpoint de inferencia en Google Colab (`INFERENCE_URL/inferir`).
    """
    url_base, api_token = obtener_inference_config(db)
    if not url_base:
        raise HTTPException(
            status_code=503,
            detail="INFERENCE_URL no está configurada. Ingrese a la pestaña 'Estado' del panel web y pegue la URL pública de Google Colab.",
        )

    endpoint = url_base if url_base.endswith(("/inferir", "/predict")) else f"{url_base}/inferir"
    headers = {}
    if api_token:
        headers["X-API-Token"] = api_token

    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=35.0, verify=False) as client:
            files = {"file": (nombre_archivo, datos_imagen, "image/jpeg")}
            resp = await client.post(endpoint, files=files, headers=headers)
            if resp.status_code != 200:
                # Reintento enviando raw JPEG bytes en el body (compatible con week_2_servidor_pose_colab_v2)
                headers_raw = {**headers, "Content-Type": "image/jpeg"}
                resp = await client.post(endpoint, content=datos_imagen, headers=headers_raw)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"No se pudo conectar con el servidor de inferencia en Google Colab ({endpoint}): {str(e)}",
        )

    latencia_total = round((time.perf_counter() - t0) * 1000, 1)
    placa_norm = normalizar_placa_estricta(data.get("placa") or data.get("placa_detalle", {}).get("texto", ""))
    ahora_bo = datetime.now(timezone(timedelta(hours=-4))).strftime("%d/%m/%Y %H:%M:%S")
    return {
        "placa": placa_norm,
        "placa_leida": data.get("placa_leida") or placa_norm,
        "confianza": float(data.get("confianza", 0.0)),
        "detectado": bool(placa_norm),
        "fecha_hora_deteccion": data.get("fecha_hora_deteccion") or ahora_bo,
        "categoria": (data.get("categoria") or data.get("vehiculo", {}).get("categoria") or "auto").lower(),
        "confianza_categoria": float(data.get("confianza_categoria") or data.get("vehiculo", {}).get("confianza") or 0.88),
        "ejes": int(data.get("ejes") or 2),
        "ruedas_detectadas": int(data.get("ruedas_detectadas") or len(data.get("keypoints", []))),
        "keypoints": data.get("keypoints", []),
        "area_mascara": float(data.get("area_mascara") or data.get("vehiculo", {}).get("area_mascara") or 0.0),
        "imagen_anotada_b64": data.get("imagen_anotada_b64") or "",
        "placa_bbox": data.get("placa_detalle", {}).get("bbox", [0, 0, 0, 0]),
        "latencia_ms": float(data.get("latencia_ms") or latencia_total),
        "latencia_e2e_ms": latencia_total,
    }


def serializar_paso(p: Paso, db: Session) -> dict:
    caseta = db.query(Caseta).filter(Caseta.id == p.caseta_id).first()
    veh = db.query(Vehiculo).filter(Vehiculo.placa == p.placa_normalizada).first()
    dt_bo = p.created_at.astimezone(timezone(timedelta(hours=-4))) if p.created_at else datetime.now(timezone(timedelta(hours=-4)))
    detectado_ok = bool(p.placa_normalizada and p.placa_normalizada != "ILEGIBLE")
    return {
        "id": p.id,
        "placa_leida": p.placa_leida,
        "placa_normalizada": p.placa_normalizada,
        "confianza_ocr": round(float(p.confianza_ocr), 3),
        "detectado": detectado_ok,
        "estado_deteccion": "DETECTADO" if detectado_ok else "NO DETECTADO",
        "fecha_hora_registro": dt_bo.strftime("%d/%m/%Y %H:%M:%S"),
        "categoria_detectada": p.categoria_detectada,
        "ejes_detectados": p.ejes_detectados,
        "monto": round(float(p.monto), 2),
        "caseta_id": p.caseta_id,
        "caseta_nombre": caseta.nombre if caseta else f"Caseta #{p.caseta_id}",
        "usuario_id": p.usuario_id,
        "propietario": veh.propietario if veh else "No registrado",
        "saldo_restante": round(float(veh.saldo), 2) if veh else None,
        "imagen_url": p.imagen_url,
        "estado": p.estado,
        "latencia_ms": round(float(p.latencia_ms or 0.0), 1),
        "created_at": p.created_at.isoformat() if p.created_at else "",
    }


# ==================== 1. AUTENTICACIÓN GOOGLE OAUTH 2.0 ====================

@app.post("/api/v1/auth/google", tags=["1. Autenticación Google OAuth 2.0"])
def login_con_google(req: GoogleAuthRequest, db: Session = Depends(get_db)):
    """
    Recibe el token de Google desde la aplicación web o móvil, lo valida con Google OAuth 2.0,
    verifica la lista blanca en la tabla `usuarios` y devuelve el JWT de sesión y el rol (`admin` u `operador`).
    """
    token_raw = req.token or req.id_token or req.credential
    info_google = verificar_token_google(token_raw)
    email = info_google["email"].lower()

    usuario = db.query(Usuario).filter(Usuario.email_google == email).first()
    if not usuario or not usuario.activo:
        raise HTTPException(
            status_code=403,
            detail=f"Acceso denegado: La cuenta de Google '{email}' no se encuentra autorizada en la lista blanca del sistema.",
        )

    if info_google.get("name") and usuario.nombre.startswith("Administrador ("):
        usuario.nombre = info_google["name"]
        db.commit()

    jwt_token = crear_token_sesion(usuario, picture=info_google.get("picture", ""))
    return {
        "access_token": jwt_token,
        "token_type": "bearer",
        "usuario": {
            "id": usuario.id,
            "email_google": usuario.email_google,
            "nombre": usuario.nombre,
            "rol": usuario.rol,
            "activo": usuario.activo,
            "picture": info_google.get("picture", ""),
        },
    }


@app.get("/api/v1/auth/me", tags=["1. Autenticación Google OAuth 2.0"])
def perfil_actual(usuario: Usuario = Depends(obtener_usuario_actual)):
    return {
        "id": usuario.id,
        "email_google": usuario.email_google,
        "nombre": usuario.nombre,
        "rol": usuario.rol,
        "activo": usuario.activo,
    }


# ==================== 2. REGISTRO DE PASO EN CASETA + TIEMPO REAL ====================

@app.post("/api/v1/pasos/frame", tags=["2. Operación de Caseta y Tiempo Real"])
async def registrar_paso_frame(
    file: UploadFile = File(...),
    caseta_id: int = Form(default=1),
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: Session = Depends(get_db),
):
    """
    Recibe un frame capturado desde la app móvil (Modo Caseta) o el panel web,
    llama a `INFERENCE_URL` (M1 + M2 + M3 en Google Colab), calcula la tarifa según categoría y ejes,
    descuenta el saldo del vehículo o genera una alerta si no está registrado / sin saldo,
    guarda la imagen de evidencia y emite el evento en tiempo real al panel web sin recargar la página.
    """
    datos_img = await file.read()
    if not datos_img:
        raise HTTPException(status_code=400, detail="La imagen enviada está vacía.")

    # Guardar imagen de evidencia original inicialmente
    ext = os.path.splitext(file.filename or "frame.jpg")[1] or ".jpg"
    nombre_evidencia = f"paso_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.jpg"
    ruta_evidencia = os.path.join(DIR_EVIDENCIAS, nombre_evidencia)
    with open(ruta_evidencia, "wb") as f:
        f.write(datos_img)
    url_evidencia = f"/evidencias/{nombre_evidencia}"

    # Llamar al endpoint unificado de inferencia en Google Colab
    inf = await llamar_endpoint_inferencia_colab(db, datos_img, nombre_evidencia)

    # Si Google Colab devolvió la imagen con las máscaras de colores (M1+M2+M3), sobrescribir la evidencia con la imagen pintada
    if inf.get("imagen_anotada_b64"):
        try:
            bytes_anotados = base64.b64decode(inf["imagen_anotada_b64"])
            with open(ruta_evidencia, "wb") as f:
                f.write(bytes_anotados)
        except Exception:
            pass

    placa_norm = inf["placa"]
    placa_leida = inf["placa_leida"] or placa_norm or "ILEGIBLE"
    categoria = inf["categoria"]
    ejes = inf["ejes"]
    confianza = inf["confianza"]
    monto = calcular_tarifa_peaje(db, categoria, ejes)

    alerta_creada = None
    vehiculo = db.query(Vehiculo).filter(Vehiculo.placa == placa_norm).first() if placa_norm else None

    if not placa_norm:
        estado_paso = "PLACA_ILEGIBLE"
        tipo_alerta = "PLACA_ILEGIBLE"
        msg_alerta = f"Vehículo ({categoria}, {ejes} ejes) detectado en Caseta #{caseta_id} con placa ilegible."
    elif not vehiculo:
        estado_paso = "NO_REGISTRADO"
        tipo_alerta = "PLACA_NO_REGISTRADA"
        msg_alerta = f"Placa {placa_norm} ({categoria}, {ejes} ejes) no registrada en el sistema (posible evasión). Tarifa: Bs {monto:.2f}"
    elif vehiculo.saldo < monto:
        estado_paso = "SIN_SALDO"
        tipo_alerta = "SALDO_INSUFICIENTE"
        msg_alerta = (
            f"Placa {placa_norm} ({vehiculo.propietario}) tiene saldo insuficiente "
            f"(Saldo: Bs {vehiculo.saldo:.2f} < Tarifa: Bs {monto:.2f})."
        )
    else:
        estado_paso = "APROBADO"
        tipo_alerta = None
        msg_alerta = None
        vehiculo.saldo = round(float(vehiculo.saldo - monto), 2)

    nuevo_paso = Paso(
        placa_leida=placa_leida,
        placa_normalizada=placa_norm or "ILEGIBLE",
        confianza_ocr=confianza,
        categoria_detectada=categoria,
        ejes_detectados=ejes,
        monto=monto,
        caseta_id=caseta_id,
        usuario_id=usuario.id,
        imagen_url=url_evidencia,
        estado=estado_paso,
        latencia_ms=inf["latencia_ms"],
    )
    db.add(nuevo_paso)
    db.flush()

    if tipo_alerta:
        alerta_creada = Alerta(
            paso_id=nuevo_paso.id,
            tipo=tipo_alerta,
            mensaje=msg_alerta,
            atendida=False,
        )
        db.add(alerta_creada)

    db.commit()
    db.refresh(nuevo_paso)

    paso_dict = serializar_paso(nuevo_paso, db)
    alerta_dict = None
    if alerta_creada:
        db.refresh(alerta_creada)
        alerta_dict = {
            "id": alerta_creada.id,
            "paso_id": alerta_creada.paso_id,
            "tipo": alerta_creada.tipo,
            "mensaje": alerta_creada.mensaje,
            "atendida": alerta_creada.atendida,
            "placa": nuevo_paso.placa_normalizada,
            "categoria": nuevo_paso.categoria_detectada,
            "monto": nuevo_paso.monto,
            "imagen_url": nuevo_paso.imagen_url,
            "created_at": alerta_creada.created_at.isoformat(),
        }

    # Emitir en tiempo real al panel web (SSE + WebSockets + Pusher)
    await gestor_rt.emitir_evento(
        "nuevo_paso",
        {
            "paso": paso_dict,
            "alerta": alerta_dict,
            "inferencia": inf,
        },
    )

    return {
        "paso": paso_dict,
        "alerta": alerta_dict,
        "inferencia": inf,
    }


# ==================== 3. CONSULTA DE PLACAS E HISTORIAL ====================

@app.post("/api/v1/placas/consultar", tags=["3. Consulta de Placas"])
def consultar_placa_por_texto(
    req: ConsultaPlacaTextoRequest,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: Session = Depends(get_db),
):
    """Consulta una placa por texto normalizado y devuelve su estado entre los 4 estados del sistema."""
    return tool_consultar_placa_bd(db, req.placa)


@app.post("/api/v1/placas/consultar-imagen", tags=["3. Consulta de Placas"])
async def consultar_placa_por_imagen(
    file: UploadFile = File(...),
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: Session = Depends(get_db),
):
    """Envía una imagen a M1 + OCR en Google Colab y devuelve el estado de la placa en el sistema."""
    datos_img = await file.read()
    inf = await llamar_endpoint_inferencia_colab(db, datos_img, file.filename or "consulta.jpg")
    resultado_bd = tool_consultar_placa_bd(db, inf.get("placa", ""))
    return {
        "inferencia": inf,
        "consulta": resultado_bd,
    }


@app.get("/api/v1/placas/{placa}/historial", tags=["3. Consulta de Placas"])
def historial_por_placa(
    placa: str,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: Session = Depends(get_db),
):
    """Devuelve el historial completo de pasos de una placa normalizada."""
    return tool_consultar_placa_bd(db, placa)


# ==================== 4. RESUMEN DE CASETAS ====================

@app.get("/api/v1/casetas/{caseta_id}/resumen", tags=["4. Casetas y Recaudación"])
def resumen_caseta(
    caseta_id: int,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: Session = Depends(get_db),
):
    """Devuelve el conteo de pasos, alertas y recaudación acumulada de una caseta."""
    caseta = db.query(Caseta).filter(Caseta.id == caseta_id).first()
    if not caseta:
        raise HTTPException(status_code=404, detail=f"Caseta #{caseta_id} no encontrada.")

    pasos = db.query(Paso).filter(Paso.caseta_id == caseta_id).all()
    recaudacion = sum(p.monto for p in pasos if p.estado == "APROBADO")
    por_categoria = {}
    for p in pasos:
        por_categoria[p.categoria_detectada] = por_categoria.get(p.categoria_detectada, 0) + 1

    return {
        "caseta": {"id": caseta.id, "nombre": caseta.nombre, "ubicacion": caseta.ubicacion},
        "total_pasos": len(pasos),
        "pasos_aprobados": sum(1 for p in pasos if p.estado == "APROBADO"),
        "pasos_observados": sum(1 for p in pasos if p.estado != "APROBADO"),
        "recaudacion_total_bs": round(float(recaudacion), 2),
        "por_categoria": por_categoria,
    }


@app.get("/api/v1/casetas", tags=["4. Casetas y Recaudación"])
def listar_casetas(usuario: Usuario = Depends(obtener_usuario_actual), db: Session = Depends(get_db)):
    casetas = db.query(Caseta).order_by(Caseta.id.asc()).all()
    return [{"id": c.id, "nombre": c.nombre, "ubicacion": c.ubicacion} for c in casetas]


# ==================== 5. AGENTE CONVERSACIONAL (TEXTO E IMAGEN) ====================

@app.post("/api/v1/agente/chat", tags=["5. Agente Conversacional"])
async def chat_con_agente(
    request: Request,
    mensaje: Optional[str] = Form(default=None),
    file: Optional[UploadFile] = File(default=None),
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: Session = Depends(get_db),
):
    """
    Endpoint unificado del Agente Conversacional:
    - Acepta JSON `{"mensaje": "3034DUS"}` o `multipart/form-data` con `mensaje` y/o `file` (imagen de placa).
    - Responde los 4 estados obligatorios, normaliza placas, sugiere correcciones OCR (`O↔0`, `I↔1`, `B↔8`, `S↔5`)
      y no inventa ningún dato fuera de la base de datos.
    """
    texto_msg = mensaje or ""
    resultado_inf = None

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        texto_msg = body.get("mensaje") or body.get("placa") or ""

    if file is not None:
        datos_img = await file.read()
        if datos_img:
            resultado_inf = await llamar_endpoint_inferencia_colab(db, datos_img, file.filename or "chat_placa.jpg")
            if resultado_inf.get("imagen_anotada_b64"):
                nombre_chat_ev = f"chat_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.jpg"
                ruta_chat_ev = os.path.join(DIR_EVIDENCIAS, nombre_chat_ev)
                try:
                    with open(ruta_chat_ev, "wb") as f:
                        f.write(base64.b64decode(resultado_inf["imagen_anotada_b64"]))
                    resultado_inf["imagen_url"] = f"/evidencias/{nombre_chat_ev}"
                except Exception:
                    pass

    res_agente = responder_chat_agente(db, texto_msg, resultado_inf)
    if resultado_inf and resultado_inf.get("imagen_url"):
        res_agente["imagen_url"] = resultado_inf["imagen_url"]
        res_agente["fecha_hora_deteccion"] = resultado_inf.get("fecha_hora_deteccion", "")
    return res_agente


# ==================== 6. RUTAS DEL PANEL WEB (DASHBOARD, VEHÍCULOS CRUD, PASOS, ALERTAS, ESTADO) ====================

@app.get("/api/v1/dashboard/resumen", tags=["6. Panel Web y Gestión"])
def resumen_dashboard(usuario: Usuario = Depends(obtener_usuario_actual), db: Session = Depends(get_db)):
    total_pasos = db.query(Paso).count()
    recaudacion = db.query(func.sum(Paso.monto)).filter(Paso.estado == "APROBADO").scalar() or 0.0
    alertas_pendientes = db.query(Alerta).filter(Alerta.atendida == False).count()  # noqa: E712
    total_vehiculos = db.query(Vehiculo).count()
    ultimos_pasos = db.query(Paso).order_by(Paso.created_at.desc()).limit(25).all()
    ultimas_alertas = db.query(Alerta).order_by(Alerta.created_at.desc()).limit(20).all()

    alertas_serializadas = []
    for a in ultimas_alertas:
        p = db.query(Paso).filter(Paso.id == a.paso_id).first()
        alertas_serializadas.append({
            "id": a.id,
            "paso_id": a.paso_id,
            "tipo": a.tipo,
            "mensaje": a.mensaje,
            "atendida": a.atendida,
            "placa": p.placa_normalizada if p else "",
            "categoria": p.categoria_detectada if p else "",
            "monto": round(float(p.monto), 2) if p else 0.0,
            "imagen_url": p.imagen_url if p else "",
            "created_at": a.created_at.isoformat() if a.created_at else "",
        })

    return {
        "kpis": {
            "total_pasos": total_pasos,
            "recaudacion_total_bs": round(float(recaudacion), 2),
            "alertas_pendientes": alertas_pendientes,
            "total_vehiculos": total_vehiculos,
        },
        "pasos": [serializar_paso(p, db) for p in ultimos_pasos],
        "alertas": alertas_serializadas,
    }


@app.get("/api/v1/pasos", tags=["6. Panel Web y Gestión"])
def listar_pasos(
    placa: Optional[str] = None,
    categoria: Optional[str] = None,
    estado: Optional[str] = None,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: Session = Depends(get_db),
):
    q = db.query(Paso)
    if placa:
        norm = normalizar_placa_estricta(placa)
        q = q.filter(Paso.placa_normalizada.contains(norm))
    if categoria:
        q = q.filter(Paso.categoria_detectada == categoria.lower())
    if estado:
        q = q.filter(Paso.estado == estado.upper())
    lista = q.order_by(Paso.created_at.desc()).limit(100).all()
    return [serializar_paso(p, db) for p in lista]


@app.get("/api/v1/alertas", tags=["6. Panel Web y Gestión"])
def listar_alertas(usuario: Usuario = Depends(obtener_usuario_actual), db: Session = Depends(get_db)):
    alertas = db.query(Alerta).order_by(Alerta.atendida.asc(), Alerta.created_at.desc()).all()
    salida = []
    for a in alertas:
        p = db.query(Paso).filter(Paso.id == a.paso_id).first()
        salida.append({
            "id": a.id,
            "paso_id": a.paso_id,
            "tipo": a.tipo,
            "mensaje": a.mensaje,
            "atendida": a.atendida,
            "placa": p.placa_normalizada if p else "",
            "categoria": p.categoria_detectada if p else "",
            "monto": round(float(p.monto), 2) if p else 0.0,
            "imagen_url": p.imagen_url if p else "",
            "created_at": a.created_at.isoformat() if a.created_at else "",
        })
    return salida


@app.patch("/api/v1/alertas/{alerta_id}/atender", tags=["6. Panel Web y Gestión"])
async def atender_alerta(
    alerta_id: int,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: Session = Depends(get_db),
):
    alerta = db.query(Alerta).filter(Alerta.id == alerta_id).first()
    if not alerta:
        raise HTTPException(status_code=404, detail="Alerta no encontrada.")
    alerta.atendida = True
    db.commit()
    await gestor_rt.emitir_evento("alerta_atendida", {"id": alerta.id, "atendida": True})
    return {"id": alerta.id, "atendida": True}


@app.get("/api/v1/vehiculos", tags=["6. Panel Web y Gestión"])
def listar_vehiculos(usuario: Usuario = Depends(obtener_usuario_actual), db: Session = Depends(get_db)):
    vehiculos = db.query(Vehiculo).order_by(Vehiculo.id.desc()).all()
    return [
        {
            "id": v.id,
            "placa": v.placa,
            "propietario": v.propietario,
            "categoria": v.categoria,
            "ejes": v.ejes,
            "saldo": round(float(v.saldo), 2),
            "activo": v.activo,
        }
        for v in vehiculos
    ]


@app.post("/api/v1/vehiculos", tags=["6. Panel Web y Gestión"])
def crear_vehiculo(
    req: VehiculoCreateUpdate,
    admin: Usuario = Depends(exigir_rol_admin),
    db: Session = Depends(get_db),
):
    placa_norm = normalizar_placa_estricta(req.placa)
    if not placa_norm:
        raise HTTPException(status_code=400, detail="Placa inválida.")
    if db.query(Vehiculo).filter(Vehiculo.placa == placa_norm).first():
        raise HTTPException(status_code=400, detail=f"La placa {placa_norm} ya está registrada.")
    v = Vehiculo(
        placa=placa_norm,
        propietario=req.propietario.strip(),
        categoria=req.categoria.strip().lower(),
        ejes=max(2, req.ejes),
        saldo=round(float(req.saldo), 2),
        activo=req.activo,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return {"id": v.id, "placa": v.placa, "propietario": v.propietario, "categoria": v.categoria, "ejes": v.ejes, "saldo": v.saldo, "activo": v.activo}


@app.put("/api/v1/vehiculos/{vehiculo_id}", tags=["6. Panel Web y Gestión"])
def actualizar_vehiculo(
    vehiculo_id: int,
    req: VehiculoCreateUpdate,
    admin: Usuario = Depends(exigir_rol_admin),
    db: Session = Depends(get_db),
):
    v = db.query(Vehiculo).filter(Vehiculo.id == vehiculo_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado.")
    v.placa = normalizar_placa_estricta(req.placa)
    v.propietario = req.propietario.strip()
    v.categoria = req.categoria.strip().lower()
    v.ejes = max(2, req.ejes)
    v.saldo = round(float(req.saldo), 2)
    v.activo = req.activo
    db.commit()
    return {"id": v.id, "placa": v.placa, "propietario": v.propietario, "categoria": v.categoria, "ejes": v.ejes, "saldo": v.saldo, "activo": v.activo}


@app.delete("/api/v1/vehiculos/{vehiculo_id}", tags=["6. Panel Web y Gestión"])
def eliminar_vehiculo(
    vehiculo_id: int,
    admin: Usuario = Depends(exigir_rol_admin),
    db: Session = Depends(get_db),
):
    v = db.query(Vehiculo).filter(Vehiculo.id == vehiculo_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado.")
    db.delete(v)
    db.commit()
    return {"eliminado": True, "id": vehiculo_id}


@app.get("/api/v1/usuarios", tags=["6. Panel Web y Gestión"])
def listar_usuarios_whitelist(admin: Usuario = Depends(exigir_rol_admin), db: Session = Depends(get_db)):
    usuarios = db.query(Usuario).order_by(Usuario.id.asc()).all()
    return [{"id": u.id, "email_google": u.email_google, "nombre": u.nombre, "rol": u.rol, "activo": u.activo} for u in usuarios]


@app.post("/api/v1/usuarios", tags=["6. Panel Web y Gestión"])
def autorizar_usuario_google(
    req: UsuarioCreateRequest,
    admin: Usuario = Depends(exigir_rol_admin),
    db: Session = Depends(get_db),
):
    email = req.email_google.strip().lower()
    u = db.query(Usuario).filter(Usuario.email_google == email).first()
    if u:
        u.nombre = req.nombre
        u.rol = req.rol
        u.activo = req.activo
    else:
        u = Usuario(email_google=email, nombre=req.nombre, rol=req.rol, activo=req.activo)
        db.add(u)
    db.commit()
    db.refresh(u)
    return {"id": u.id, "email_google": u.email_google, "nombre": u.nombre, "rol": u.rol, "activo": u.activo}


# ==================== 7. ESTADO DEL ENDPOINT DE INFERENCIA (COLAB) Y ACTUALIZACIÓN EN CALIENTE ====================

@app.get("/api/v1/estado/inferencia", tags=["7. Estado de Inferencia (Google Colab)"])
async def verificar_estado_inferencia(
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: Session = Depends(get_db),
):
    """
    Verifica en tiempo real si el endpoint de inferencia en Google Colab (`INFERENCE_URL/health`)
    responde y mide su latencia de respuesta.
    """
    url_base, api_token = obtener_inference_config(db)
    if not url_base:
        return {
            "online": False,
            "inference_url": "",
            "latencia_ms": None,
            "detalle": "INFERENCE_URL no configurada. Pegue la URL de Cloudflare Tunnel generada en Google Colab.",
        }

    health_url = f"{url_base}/health"
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            resp = await client.get(health_url)
            lat = round((time.perf_counter() - t0) * 1000, 1)
            if resp.status_code == 200:
                return {
                    "online": True,
                    "inference_url": url_base,
                    "latencia_ms": lat,
                    "remoto": resp.json(),
                }
            return {
                "online": False,
                "inference_url": url_base,
                "latencia_ms": lat,
                "detalle": f"HTTP {resp.status_code}",
            }
    except Exception as e:
        return {
            "online": False,
            "inference_url": url_base,
            "latencia_ms": None,
            "detalle": str(e),
        }


@app.put("/api/v1/estado/inferencia", tags=["7. Estado de Inferencia (Google Colab)"])
def actualizar_url_inferencia_colab(
    req: ConfigInferenceRequest,
    admin: Usuario = Depends(exigir_rol_admin),
    db: Session = Depends(get_db),
):
    """
    Permite al Administrador actualizar `INFERENCE_URL` en caliente desde la página 'Estado'
    cada vez que reinicie su sesión de Google Colab, guardándola en la base de datos sin redesplegar.
    """
    nueva_url = req.inference_url.strip().rstrip("/")
    cfg_url = db.query(Configuracion).filter(Configuracion.clave == "INFERENCE_URL").first()
    if not cfg_url:
        cfg_url = Configuracion(clave="INFERENCE_URL", valor=nueva_url)
        db.add(cfg_url)
    else:
        cfg_url.valor = nueva_url

    if req.inference_api_token is not None:
        cfg_tok = db.query(Configuracion).filter(Configuracion.clave == "INFERENCE_API_TOKEN").first()
        if not cfg_tok:
            db.add(Configuracion(clave="INFERENCE_API_TOKEN", valor=req.inference_api_token.strip()))
        else:
            cfg_tok.valor = req.inference_api_token.strip()

    db.commit()
    return {"actualizado": True, "inference_url": nueva_url}


# ==================== 8. STREAM EN TIEMPO REAL (SSE Y WEBSOCKET) ====================

@app.get("/api/v1/stream/eventos", tags=["2. Operación de Caseta y Tiempo Real"])
async def stream_eventos_sse(
    request: Request,
    usuario: Usuario = Depends(obtener_usuario_actual),
):
    """Stream Server-Sent Events (SSE) que actualiza el panel web al instante con cada paso o alerta."""
    cola = gestor_rt.suscribir_sse()

    async def generador_eventos():
        try:
            yield 'data: {"evento": "conectado", "datos": {"estado": "SSE activo"}}\n\n'
            while True:
                if await request.is_disconnected():
                    break
                try:
                    mensaje = await asyncio.wait_for(cola.get(), timeout=15.0)
                    yield f"data: {mensaje}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            gestor_rt.desuscribir_sse(cola)

    return StreamingResponse(
        generador_eventos(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.websocket("/api/v1/ws/eventos")
async def websocket_eventos(websocket: WebSocket):
    await gestor_rt.conectar_ws(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        gestor_rt.desconectar_ws(websocket)


# ==================== 9. SERVIR FRONTEND COMPILADO EN UN SOLO SUBDOMINIO HTTPS ====================

DIR_FRONTEND_DIST = os.path.abspath(os.path.join(DIR_BASE, "..", "frontend", "dist"))
if os.path.isdir(DIR_FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIR_FRONTEND_DIST, "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def servir_spa(full_path: str):
        archivo = os.path.join(DIR_FRONTEND_DIST, full_path)
        if full_path and os.path.isfile(archivo):
            return FileResponse(archivo)
        return FileResponse(os.path.join(DIR_FRONTEND_DIST, "index.html"))
