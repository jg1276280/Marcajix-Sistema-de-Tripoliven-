from django.core.management.base import BaseCommand, CommandError

from core.hid_listener import listen_hid_reader
from core.models import HIDReaderConfig


class Command(BaseCommand):
    help = "Escucha el lector HID RS-232 configurado para la garita."

    def add_arguments(self, parser):
        parser.add_argument("--reader", type=int, default=1, help="ID de la configuración del lector (por defecto: 1).")

    def handle(self, *args, **options):
        config = HIDReaderConfig.objects.filter(pk=options["reader"], is_active=True).first()
        if config is None:
            raise CommandError("No existe un lector HID activo con ese ID.")
        self.stdout.write(f"Escuchando {config.name} en {config.port}...")
        try:
            listen_hid_reader(config)
        except RuntimeError as error:
            raise CommandError(str(error)) from error