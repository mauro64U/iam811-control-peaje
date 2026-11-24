"""
Seed Automático de Base de Datos para el Sistema Inteligente de Control de Peaje (IAM-811).
Incluye:
- Lista blanca obligatoria con `doc.alvaro.pinto.ma@unifranz.edu.bo` como Administrador + correos en `ADMIN_EMAILS`.
- Casetas de peaje de Bolivia (Autopista La Paz - El Alto, Retén Achica Arriba, Peaje Sica Sica).
- Tarifario oficial según categoría (moto, auto, minibus, camion, bus) y número de ejes.
- 24 vehículos de prueba realistas que incluyen las 16 placas reales fotografiadas en `Placas_en_mi_caso`
  y vehículos adicionales para cubrir los 4 estados del Agente Conversacional:
  1) Registrada y con paso
  2) Registrada sin paso
  3) Identificada no registrada (posible evasión en tabla pasos)
  4) No existe
"""

import os
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from models import Usuario, Vehiculo, Caseta, Tarifa, Paso, Alerta, Configuracion


VEHICULOS_PRUEBA = [
    # --- 16 Placas reales fotografiadas en `Placas_en_mi_caso` ---
    {"placa": "3034DUS", "propietario": "Mauricio Vásquez Guillén", "categoria": "auto", "ejes": 2, "saldo": 145.0, "activo": True},
    {"placa": "1620AEN", "propietario": "Carlos Alberto Mamani Quispe", "categoria": "minibus", "ejes": 2, "saldo": 90.0, "activo": True},
    {"placa": "4222TLN", "propietario": "Sindicato Trans Copacabana S.R.L.", "categoria": "minibus", "ejes": 2, "saldo": 180.0, "activo": True},
    {"placa": "5314PFC", "propietario": "Valeria Rojas Fernández", "categoria": "auto", "ejes": 2, "saldo": 85.0, "activo": True},
    {"placa": "1152SFU", "propietario": "Jorge Luis Condori Choque", "categoria": "auto", "ejes": 2, "saldo": 2.0, "activo": True},   # Saldo insuficiente
    {"placa": "4694INB", "propietario": "Cooperativa Transporte King Long", "categoria": "minibus", "ejes": 2, "saldo": 120.0, "activo": True},
    {"placa": "1857NTE", "propietario": "Constructora Altiplano S.A.", "categoria": "camion", "ejes": 2, "saldo": 250.0, "activo": True},
    {"placa": "4763FSS", "propietario": "Agropecuaria del Oriente S.R.L.", "categoria": "auto", "ejes": 2, "saldo": 110.0, "activo": True},
    {"placa": "1651FUL", "propietario": "Expreso Rápido El Alto", "categoria": "minibus", "ejes": 2, "saldo": 0.0, "activo": True},    # Sin saldo
    {"placa": "4454FGX", "propietario": "Patricia Mendoza Vda. de Siles", "categoria": "auto", "ejes": 2, "saldo": 200.0, "activo": True},
    {"placa": "4695ELB", "propietario": "Rodrigo Gutiérrez Torrez", "categoria": "auto", "ejes": 2, "saldo": 65.0, "activo": True},
    {"placa": "1605KLX", "propietario": "Fernando Flores Apaza", "categoria": "auto", "ejes": 2, "saldo": 95.0, "activo": True},
    {"placa": "1367ZTG", "propietario": "Gabriela Salazar Vargas", "categoria": "auto", "ejes": 2, "saldo": 4.0, "activo": True},    # Saldo bajo
    {"placa": "1205HGL", "propietario": "Hernán Zeballos Terceros", "categoria": "auto", "ejes": 2, "saldo": 75.0, "activo": True},
    {"placa": "1318IZH", "propietario": "Transporte Interprovincial Aroma", "categoria": "minibus", "ejes": 2, "saldo": 160.0, "activo": True},
    {"placa": "1506UAX", "propietario": "Miguel Ángel Paz Campero", "categoria": "auto", "ejes": 2, "saldo": 55.0, "activo": True},
    # --- 8 Vehículos pesados, buses y motos adicionales (total = 24 vehículos >= 20 obligatorios) ---
    {"placa": "2481KLM", "propietario": "Flota Bolívar Internacional", "categoria": "bus", "ejes": 3, "saldo": 340.0, "activo": True},
    {"placa": "3910BTR", "propietario": "Logística Pesada Andina S.A.", "categoria": "camion", "ejes": 3, "saldo": 420.0, "activo": True},
    {"placa": "4108CTN", "propietario": "Transporte de Carga Transredes", "categoria": "camion", "ejes": 4, "saldo": 510.0, "activo": True},
    {"placa": "5820HDP", "propietario": "Frigoríficos del Sur S.R.L.", "categoria": "camion", "ejes": 5, "saldo": 10.0, "activo": True},   # Saldo insuficiente para 5 ejes
    {"placa": "2945MXP", "propietario": "Trans Emperador Bus Cama", "categoria": "bus", "ejes": 3, "saldo": 280.0, "activo": True},
    {"placa": "1094MTO", "propietario": "Daniela choquehuanca Nina", "categoria": "moto", "ejes": 2, "saldo": 45.0, "activo": True},
    {"placa": "3372MTR", "propietario": "Sebastián Mercado Arancibia", "categoria": "moto", "ejes": 2, "saldo": 30.0, "activo": True},
    {"placa": "4890BNA", "propietario": "Importadora Cruz del Sur S.A.", "categoria": "camion", "ejes": 3, "saldo": 0.0, "activo": True},
]

TARIFAS_BASE = [
    {"categoria": "moto", "ejes": 2, "monto": 3.0},
    {"categoria": "auto", "ejes": 2, "monto": 7.0},
    {"categoria": "minibus", "ejes": 2, "monto": 10.0},
    {"categoria": "bus", "ejes": 2, "monto": 18.0},
    {"categoria": "bus", "ejes": 3, "monto": 25.0},
    {"categoria": "bus", "ejes": 4, "monto": 32.0},
    {"categoria": "camion", "ejes": 2, "monto": 15.0},
    {"categoria": "camion", "ejes": 3, "monto": 25.0},
    {"categoria": "camion", "ejes": 4, "monto": 35.0},
    {"categoria": "camion", "ejes": 5, "monto": 45.0},
    {"categoria": "camion", "ejes": 6, "monto": 55.0},
]

CASETAS_BASE = [
    {"nombre": "Caseta 1 - Autopista La Paz - El Alto", "ubicacion": "Km 7 Autopista La Paz - El Alto (Carril Central)"},
    {"nombre": "Caseta 2 - Retén Achica Arriba", "ubicacion": "Ruta Nacional 1 La Paz - Oruro Km 38"},
    {"nombre": "Caseta 3 - Peaje Patacamaya", "ubicacion": "Ruta Nacional 1 La Paz - Oruro Km 98"},
]


def calcular_tarifa_peaje(db: Session, categoria: str, ejes: int) -> float:
    cat = (categoria or "auto").strip().lower()
    ejes_val = max(2, int(ejes or 2))
    t = db.query(Tarifa).filter(Tarifa.categoria == cat, Tarifa.ejes == ejes_val).first()
    if t:
        return float(t.monto)
    t_cat = db.query(Tarifa).filter(Tarifa.categoria == cat).order_by(Tarifa.ejes.asc()).first()
    if t_cat:
        ejes_extra = max(0, ejes_val - t_cat.ejes)
        return float(t_cat.monto + ejes_extra * 8.0)
    return 7.0


def ejecutar_seed(db: Session):
    # 1. Usuarios autorizados en Lista Blanca (Docente obligatorio + Estudiante + variables de entorno)
    correos_admin = [
        "doc.alvaro.pinto.ma@unifranz.edu.bo",
        "lpze.mauriciosebastian.vasquez.gu@unifranz.edu.bo",
    ]
    env_admins = os.environ.get("ADMIN_EMAILS", "")
    for correo in env_admins.split(","):
        c = correo.strip().lower()
        if c and c not in correos_admin:
            correos_admin.append(c)

    for email in correos_admin:
        existe = db.query(Usuario).filter(Usuario.email_google == email).first()
        if not existe:
            if "alvaro.pinto" in email:
                nombre = "Ing. Alvaro Pinto Mamani (Docente IAM-811)"
            elif "mauriciosebastian.vasquez" in email:
                nombre = "Mauricio Sebastián Vásquez Guillén (Administrador)"
            else:
                nombre = f"Administrador ({email.split('@')[0]})"
            db.add(Usuario(email_google=email, nombre=nombre, rol="admin", activo=True))
        else:
            existe.rol = "admin"
            existe.activo = True

    operador_demo = "operador.caseta@unifranz.edu.bo"
    if not db.query(Usuario).filter(Usuario.email_google == operador_demo).first():
        db.add(Usuario(email_google=operador_demo, nombre="Operador de Caseta Peaje", rol="operador", activo=True))

    db.commit()

    # 2. Configuracion dinámica (INFERENCE_URL)
    inf_url = os.environ.get("INFERENCE_URL", "").strip()
    cfg_url = db.query(Configuracion).filter(Configuracion.clave == "INFERENCE_URL").first()
    if not cfg_url:
        db.add(Configuracion(clave="INFERENCE_URL", valor=inf_url))
    elif inf_url and not cfg_url.valor:
        cfg_url.valor = inf_url

    inf_tok = os.environ.get("INFERENCE_API_TOKEN", "").strip()
    cfg_tok = db.query(Configuracion).filter(Configuracion.clave == "INFERENCE_API_TOKEN").first()
    if not cfg_tok:
        db.add(Configuracion(clave="INFERENCE_API_TOKEN", valor=inf_tok))

    # 3. Casetas
    if db.query(Caseta).count() == 0:
        for c in CASETAS_BASE:
            db.add(Caseta(**c))
        db.commit()

    # 4. Tarifas
    if db.query(Tarifa).count() == 0:
        for t in TARIFAS_BASE:
            db.add(Tarifa(**t))
        db.commit()

    # 5. Vehículos (24 vehículos de prueba)
    if db.query(Vehiculo).count() == 0:
        for v in VEHICULOS_PRUEBA:
            db.add(Vehiculo(**v))
        db.commit()

    # 6. Pasos y Alertas iniciales para demostrar de inmediato los 4 estados del Agente Conversacional
    if db.query(Paso).count() == 0:
        admin_user = db.query(Usuario).filter(Usuario.email_google == "doc.alvaro.pinto.ma@unifranz.edu.bo").first()
        caseta1 = db.query(Caseta).first()
        ahora = datetime.now(timezone.utc)

        pasos_semilla = [
            # Estado 1: Registrada y con paso
            {
                "placa_leida": "3034-DUS",
                "placa_normalizada": "3034DUS",
                "confianza_ocr": 0.96,
                "categoria_detectada": "auto",
                "ejes_detectados": 2,
                "monto": 7.0,
                "caseta_id": caseta1.id,
                "usuario_id": admin_user.id if admin_user else None,
                "imagen_url": "/evidencias/photo_1_2026-11-24_12-03-30.jpg",
                "estado": "APROBADO",
                "latencia_ms": 215.4,
                "created_at": ahora - timedelta(minutes=45),
            },
            {
                "placa_leida": "4222TLN",
                "placa_normalizada": "4222TLN",
                "confianza_ocr": 0.94,
                "categoria_detectada": "minibus",
                "ejes_detectados": 2,
                "monto": 10.0,
                "caseta_id": caseta1.id,
                "usuario_id": admin_user.id if admin_user else None,
                "imagen_url": "/evidencias/photo_3_2026-11-24_12-03-30.jpg",
                "estado": "APROBADO",
                "latencia_ms": 198.2,
                "created_at": ahora - timedelta(minutes=30),
            },
            {
                "placa_leida": "1857NTE",
                "placa_normalizada": "1857NTE",
                "confianza_ocr": 0.95,
                "categoria_detectada": "camion",
                "ejes_detectados": 2,
                "monto": 15.0,
                "caseta_id": caseta1.id,
                "usuario_id": admin_user.id if admin_user else None,
                "imagen_url": "/evidencias/photo_5_2026-11-24_12-03-30.jpg",
                "estado": "APROBADO",
                "latencia_ms": 230.1,
                "created_at": ahora - timedelta(minutes=20),
            },
            # Paso con Saldo Insuficiente (genera Alerta)
            {
                "placa_leida": "1651FUL",
                "placa_normalizada": "1651FUL",
                "confianza_ocr": 0.92,
                "categoria_detectada": "minibus",
                "ejes_detectados": 2,
                "monto": 10.0,
                "caseta_id": caseta1.id,
                "usuario_id": admin_user.id if admin_user else None,
                "imagen_url": "/evidencias/photo_7_2026-11-24_12-03-30.jpg",
                "estado": "SIN_SALDO",
                "latencia_ms": 210.0,
                "created_at": ahora - timedelta(minutes=12),
            },
            # Estado 3: Identificada por cámara pero NO registrada en tabla vehiculos (Posible evasión)
            {
                "placa_leida": "9988EVA",
                "placa_normalizada": "9988EVA",
                "confianza_ocr": 0.89,
                "categoria_detectada": "camion",
                "ejes_detectados": 3,
                "monto": 25.0,
                "caseta_id": caseta1.id,
                "usuario_id": admin_user.id if admin_user else None,
                "imagen_url": "/evidencias/photo_6_2026-11-24_12-03-30.jpg",
                "estado": "NO_REGISTRADO",
                "latencia_ms": 240.8,
                "created_at": ahora - timedelta(minutes=5),
            },
        ]

        for p_data in pasos_semilla:
            paso = Paso(**p_data)
            db.add(paso)
            db.flush()
            if paso.estado == "SIN_SALDO":
                db.add(
                    Alerta(
                        paso_id=paso.id,
                        tipo="SALDO_INSUFICIENTE",
                        mensaje=f"Vehículo {paso.placa_normalizada} ({paso.categoria_detectada}) sin saldo suficiente para cubrir Bs {paso.monto:.2f}",
                        atendida=False,
                        created_at=paso.created_at,
                    )
                )
            elif paso.estado == "NO_REGISTRADO":
                db.add(
                    Alerta(
                        paso_id=paso.id,
                        tipo="PLACA_NO_REGISTRADA",
                        mensaje=f"Placa {paso.placa_normalizada} detectada en caseta pero no figura en el padrón de vehículos (posible evasión)",
                        atendida=False,
                        created_at=paso.created_at,
                    )
                )
        db.commit()
