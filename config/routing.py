import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application
from django.urls import path

from core.live import GaritaLiveConsumer

application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        # Rechaza conexiones desde otros orígenes (secuestro de WebSocket entre sitios).
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(
                URLRouter(
                    [
                        path("ws/garita-live/", GaritaLiveConsumer.as_asgi()),
                    ]
                )
            )
        ),
    }
)
