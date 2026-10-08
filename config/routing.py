import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application
from django.urls import path

from core.live import GaritaLiveConsumer, AdminAlertsConsumer

application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        "websocket": AuthMiddlewareStack(
            URLRouter(
                [
                    path("ws/garita-live/", GaritaLiveConsumer.as_asgi()),
                    path("ws/admin-alerts/", AdminAlertsConsumer.as_asgi()),
                ]
            )
        ),
    }
)
