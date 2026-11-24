"""
Autenticación Exclusiva con Google OAuth 2.0 y Lista Blanca en Base de Datos (Sección 4.4 de la guía).
- Valida el `id_token` o `access_token` emitido por Google Identity Services / Google Sign-In (Web y Android).
- Verifica que el correo esté en la tabla `usuarios` y tenga `activo = True`.
- Si no está autorizado, devuelve HTTP 403 Forbidden ("Acceso denegado: Su cuenta de Google no está en la lista blanca").
- Emite un JWT de sesión del sistema y protege todas las rutas excepto `POST /api/v1/auth/google` y `/api/v1/health`.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
import requests
from fastapi import Depends, HTTPException, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from sqlalchemy.orm import Session
from database import get_db
from models import Usuario

JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "iam811_peaje_jwt_secret_key_change_in_prod_2026")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "1440"))

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_ANDROID_CLIENT_ID = os.environ.get("GOOGLE_ANDROID_CLIENT_ID", "").strip()

security_scheme = HTTPBearer(auto_error=False)


def verificar_token_google(credential_token: str) -> dict:
    """
    Valida un ID Token de Google (o un Access Token de OAuth2 desde Web/Android) contra los servidores de Google.
    Devuelve {'email': ..., 'name': ..., 'picture': ...}.
    """
    if not credential_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de Google vacío.")

    # 1. Intentar validar como Google ID Token (JWT firmado por Google)
    try:
        info = id_token.verify_oauth2_token(credential_token, google_requests.Request())
        audiencias_validas = [c for c in (GOOGLE_CLIENT_ID, GOOGLE_ANDROID_CLIENT_ID) if c]
        if audiencias_validas and info.get("aud") not in audiencias_validas and info.get("azp") not in audiencias_validas:
            raise ValueError("El client_id (aud) del token de Google no coincide con los configurados.")
        email = (info.get("email") or "").strip().lower()
        if not email:
            raise ValueError("El token de Google no contiene un correo electrónico.")
        return {
            "email": email,
            "name": info.get("name") or email.split("@")[0],
            "picture": info.get("picture") or "",
        }
    except Exception:
        pass

    # 2. Respaldo: validar como OAuth2 Access Token contra el endpoint oficial de Google UserInfo
    try:
        resp = requests.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {credential_token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            email = (data.get("email") or "").strip().lower()
            if email:
                return {
                    "email": email,
                    "name": data.get("name") or email.split("@")[0],
                    "picture": data.get("picture") or "",
                }
    except Exception:
        pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token de Google inválido o expirado. Inicie sesión nuevamente con Google OAuth 2.0.",
    )


def crear_token_sesion(usuario: Usuario, picture: str = "") -> str:
    ahora = datetime.now(timezone.utc)
    payload = {
        "sub": str(usuario.id),
        "email": usuario.email_google,
        "nombre": usuario.nombre,
        "rol": usuario.rol,
        "picture": picture,
        "iat": ahora,
        "exp": ahora + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def obtener_usuario_actual(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    token_query: Optional[str] = Query(default=None, alias="token"),
    db: Session = Depends(get_db),
) -> Usuario:
    """
    Dependencia para proteger rutas de la API REST y del stream SSE.
    Acepta tanto un JWT emitido por el sistema como un ID token directo de Google.
    """
    raw_token = creds.credentials if creds else token_query
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida. Envíe el header Authorization: Bearer <token>.",
        )

    email_usuario = None
    # 1. Intentar decodificar como JWT propio del sistema
    try:
        payload = jwt.decode(raw_token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        email_usuario = (payload.get("email") or "").strip().lower()
    except Exception:
        # 2. Según sección 4.4: "La API valida el token de Google (o un token propio emitido tras el inicio de sesión)"
        info_google = verificar_token_google(raw_token)
        email_usuario = info_google["email"]

    usuario = db.query(Usuario).filter(Usuario.email_google == email_usuario).first()
    if not usuario or not usuario.activo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Acceso denegado (Lista Blanca): La cuenta de Google '{email_usuario}' no está autorizada en el sistema.",
        )
    return usuario


def exigir_rol_admin(usuario: Usuario = Depends(obtener_usuario_actual)) -> Usuario:
    if usuario.rol != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acción restringida: Se requiere rol de Administrador.",
        )
    return usuario
