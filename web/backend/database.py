"""
Configuración de conexión a Base de Datos (PostgreSQL en la nube: Neon / Supabase / Render)
para el Sistema Inteligente de Control de Peaje (IAM-811).
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

if not DATABASE_URL:
    # Base de datos SQLite en archivo efímero de contenedor cloud si aún no se inyectó DATABASE_URL
    DATABASE_URL = "sqlite:///./peaje_cloud.db"

# Compatibilidad con URLs postgres:// de algunos proveedores cloud (Render / Heroku)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
