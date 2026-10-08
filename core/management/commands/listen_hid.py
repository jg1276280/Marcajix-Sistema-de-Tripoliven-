import logging

from django.core.management.base import BaseCommand, CommandError

from core.hid_listener import listen_hid_reader
from core.models import HIDReaderConfig


class Command(BaseCommand):
    help = "Escucha el lector HID RS-232 de la garita y registra cada tarjeta leída."

    def add_arguments(self, parser):
        parser.add_argument("--reader", type=int, default=1, help="ID de la configuración del lector (por defecto: 1).")

    def handle(self, *args, **options):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        # Si aún no se configuró el lector, se crea con los valores por defecto (editables en Dispositivos).
        config, created = HIDReaderConfig.objects.get_or_create(pk=options["reader"])
        if created:
            self.stdout.write(f"Se creó la configuración por defecto del lector ({config.port}).")
        self.stdout.write(f"Escuchando {config.name} en {config.port}...")
        try:
            listen_hid_reader(config)
        except RuntimeError as error:
            raise CommandError(str(error)) from error
