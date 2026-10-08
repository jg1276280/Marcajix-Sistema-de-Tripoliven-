from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0008_attendancelog_session_status_and_more")]

    operations = [
        migrations.CreateModel(
            name="HIDReaderConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(default="Garita Principal", max_length=120, verbose_name="Nombre")),
                ("port", models.CharField(default="COM3", help_text="COM1, COM3 en Windows o /dev/ttyUSB0 en Linux", max_length=80, verbose_name="Puerto")),
                ("baud_rate", models.IntegerField(choices=[(1200, "1200"), (2400, "2400"), (4800, "4800"), (9600, "9600"), (19200, "19200")], default=9600, verbose_name="Velocidad")),
                ("data_bits", models.IntegerField(choices=[(7, "7"), (8, "8")], default=8, verbose_name="Bits de datos")),
                ("parity", models.CharField(choices=[("N", "N / Ninguna"), ("E", "E / Par"), ("O", "O / Impar")], default="N", max_length=1, verbose_name="Paridad")),
                ("stop_bits", models.IntegerField(choices=[(1, "1"), (2, "2")], default=1, verbose_name="Bits de parada")),
                ("timeout", models.FloatField(default=1.0, verbose_name="Tiempo de espera (s)")),
                ("wiegand_format", models.CharField(default="Wiegand 26-bit", max_length=60, verbose_name="Formato Wiegand")),
                ("is_active", models.BooleanField(default=True, verbose_name="Lector activo")),
            ],
            options={"db_table": "core_hid_reader_config", "verbose_name": "Configuración de lector HID", "verbose_name_plural": "Configuración de lectores HID"},
        ),
    ]