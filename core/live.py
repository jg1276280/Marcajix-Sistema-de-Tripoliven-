from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .permissions import MONITOR_DOOR, has_capability

GARITA_GROUP = "garita-live"


class GaritaLiveConsumer(AsyncJsonWebsocketConsumer):
    """Eventos en vivo de la puerta: solo para usuarios con acceso al monitoreo de garita."""

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not await database_sync_to_async(has_capability)(user, MONITOR_DOOR):
            await self.close(code=4403)
            return
        await self.channel_layer.group_add(GARITA_GROUP, self.channel_name)
        await self.accept()
        await self.send_json({"type": "connection", "status": "connected", "channel": GARITA_GROUP})

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(GARITA_GROUP, self.channel_name)

    async def broadcast_event(self, event):
        await self.send_json(event["payload"])
