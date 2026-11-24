"""
Motor de Eventos en Tiempo Real (Sección 4.3 de la guía del laboratorio):
- Soporta Server-Sent Events (SSE) nativo en `/api/v1/stream/eventos`.
- Soporta WebSockets en `/api/v1/ws/eventos`.
- Soporta Pusher Channels (si `PUSHER_KEY` y `PUSHER_SECRET` están configurados en entorno para hosting compartido).
Cada vez que una caseta registra un vehículo o se dispara una alerta, se transmite al instante sin recargar la página.
"""

import os
import json
import asyncio
from typing import List
from fastapi import WebSocket

PUSHER_APP_ID = os.environ.get("PUSHER_APP_ID", "").strip()
PUSHER_KEY = os.environ.get("PUSHER_KEY", "").strip()
PUSHER_SECRET = os.environ.get("PUSHER_SECRET", "").strip()
PUSHER_CLUSTER = os.environ.get("PUSHER_CLUSTER", "us2").strip()

_pusher_client = None
if PUSHER_APP_ID and PUSHER_KEY and PUSHER_SECRET:
    try:
        import pusher
        _pusher_client = pusher.Pusher(
            app_id=PUSHER_APP_ID,
            key=PUSHER_KEY,
            secret=PUSHER_SECRET,
            cluster=PUSHER_CLUSTER,
            ssl=True,
        )
    except Exception:
        _pusher_client = None


class GestorTiempoReal:
    def __init__(self):
        self.colas_sse: List[asyncio.Queue] = []
        self.websockets: List[WebSocket] = []

    def suscribir_sse(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self.colas_sse.append(q)
        return q

    def desuscribir_sse(self, q: asyncio.Queue):
        if q in self.colas_sse:
            self.colas_sse.remove(q)

    async def conectar_ws(self, ws: WebSocket):
        await ws.accept()
        self.websockets.append(ws)

    def desconectar_ws(self, ws: WebSocket):
        if ws in self.websockets:
            self.websockets.remove(ws)

    async def emitir_evento(self, tipo_evento: str, datos: dict):
        paquete = {
            "evento": tipo_evento,
            "datos": datos,
        }
        mensaje_json = json.dumps(paquete, ensure_ascii=False, default=str)

        # 1. Notificar a todos los clientes SSE activos
        for q in list(self.colas_sse):
            try:
                q.put_nowait(mensaje_json)
            except Exception:
                pass

        # 2. Notificar a todos los clientes WebSocket activos
        for ws in list(self.websockets):
            try:
                await ws.send_text(mensaje_json)
            except Exception:
                self.desconectar_ws(ws)

        # 3. Notificar a Pusher (si está habilitado para hosting compartido)
        if _pusher_client is not None:
            try:
                _pusher_client.trigger("peaje-tiempo-real", tipo_evento, datos)
            except Exception:
                pass


gestor_rt = GestorTiempoReal()
