"""
Modelos SQLAlchemy obligatorios según la Sección 4.6 de la guía del laboratorio:
- usuarios(id, email_google, nombre, rol, activo)
- vehiculos(id, placa, propietario, categoria, ejes, saldo, activo)
- casetas(id, nombre, ubicacion)
- tarifas(id, categoria, ejes, monto)
- pasos(id, placa_leida, placa_normalizada, confianza_ocr, categoria_detectada,
        ejes_detectados, monto, caseta_id, usuario_id, imagen_url, estado, created_at)
- alertas(id, paso_id, tipo, atendida, created_at)
- configuracion(clave, valor, updated_at) -> Para persistir INFERENCE_URL editable en caliente
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from database import Base


def utc_now():
    return datetime.now(timezone.utc)


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    email_google = Column(String(255), unique=True, index=True, nullable=False)
    nombre = Column(String(255), nullable=False)
    rol = Column(String(50), nullable=False, default="operador")  # 'admin' | 'operador'
    activo = Column(Boolean, default=True, nullable=False)


class Vehiculo(Base):
    __tablename__ = "vehiculos"

    id = Column(Integer, primary_key=True, index=True)
    placa = Column(String(32), unique=True, index=True, nullable=False)
    propietario = Column(String(255), nullable=False)
    categoria = Column(String(50), nullable=False)  # moto, auto, minibus, camion, bus
    ejes = Column(Integer, nullable=False, default=2)
    saldo = Column(Float, nullable=False, default=0.0)
    activo = Column(Boolean, default=True, nullable=False)


class Caseta(Base):
    __tablename__ = "casetas"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(120), nullable=False)
    ubicacion = Column(String(255), nullable=False)


class Tarifa(Base):
    __tablename__ = "tarifas"

    id = Column(Integer, primary_key=True, index=True)
    categoria = Column(String(50), index=True, nullable=False)
    ejes = Column(Integer, index=True, nullable=False)
    monto = Column(Float, nullable=False)


class Paso(Base):
    __tablename__ = "pasos"

    id = Column(Integer, primary_key=True, index=True)
    placa_leida = Column(String(64), nullable=False)
    placa_normalizada = Column(String(32), index=True, nullable=False)
    confianza_ocr = Column(Float, nullable=False, default=0.0)
    categoria_detectada = Column(String(50), nullable=False)
    ejes_detectados = Column(Integer, nullable=False, default=2)
    monto = Column(Float, nullable=False, default=0.0)
    caseta_id = Column(Integer, ForeignKey("casetas.id"), nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    imagen_url = Column(Text, nullable=True)
    estado = Column(String(64), nullable=False)  # 'APROBADO', 'SIN_SALDO', 'NO_REGISTRADO', 'PLACA_ILEGIBLE'
    latencia_ms = Column(Float, nullable=True, default=0.0)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    caseta = relationship("Caseta")
    usuario = relationship("Usuario")


class Alerta(Base):
    __tablename__ = "alertas"

    id = Column(Integer, primary_key=True, index=True)
    paso_id = Column(Integer, ForeignKey("pasos.id"), nullable=False)
    tipo = Column(String(64), nullable=False)  # 'PLACA_NO_REGISTRADA' | 'SALDO_INSUFICIENTE' | 'PLACA_ILEGIBLE'
    mensaje = Column(String(255), nullable=True)
    atendida = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    paso = relationship("Paso")


class Configuracion(Base):
    __tablename__ = "configuracion"

    clave = Column(String(100), primary_key=True, index=True)
    valor = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
