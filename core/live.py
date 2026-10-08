import json

from channels.generic.websocket import AsyncJsonWebsocketConsumer


class GaritaLiveConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add("garita-live", self.channel_name)
        await self.accept()
        await self.send_json({"type": "connection", "status": "connected", "channel": "garita-live"})

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard("garita-live", self.channel_name)

    async def broadcast_event(self, event):
        await self.send_json(event["payload"])


class AdminAlertsConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add("admin-alerts", self.channel_name)
        await self.accept()
        await self.send_json({"type": "connection", "status": "connected", "channel": "admin-alerts"})

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard("admin-alerts", self.channel_name)

    async def broadcast_event(self, event):
        await self.send_json(event["payload"])
