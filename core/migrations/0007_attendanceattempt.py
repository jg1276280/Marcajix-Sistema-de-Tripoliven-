from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0006_attendancelog_latest_index"),
        ("employees", "0007_management_hierarchy"),
    ]

    operations = [
        migrations.CreateModel(
            name="AttendanceAttempt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("employee_status", models.CharField(max_length=20, verbose_name="Estatus del empleado")),
                ("mark_type", models.CharField(choices=[("entry", "Entrada"), ("exit", "Salida")], max_length=10, verbose_name="Tipo solicitado")),
                ("status", models.CharField(choices=[("blocked", "Bloqueado")], default="blocked", max_length=20, verbose_name="Estado del intento")),
                ("reason", models.CharField(max_length=255, verbose_name="Motivo")),
                ("source", models.CharField(default="Registro manual", max_length=120, verbose_name="Origen / dispositivo")),
                ("attempted_at", models.DateTimeField(auto_now_add=True, verbose_name="Fecha y hora")),
                ("attempted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="attendance_attempts", to=settings.AUTH_USER_MODEL)),
                ("employee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="attendance_attempts", to="employees.employee")),
            ],
            options={
                "verbose_name": "Intento de marcaje",
                "verbose_name_plural": "Intentos de marcaje",
                "db_table": "core_attendance_attempt",
                "ordering": ("-attempted_at", "-pk"),
            },
        ),
        migrations.AddIndex(index=models.Index(fields=["attempted_at"], name="attendance_attempted_time_idx"), model_name="attendanceattempt"),
        migrations.AddIndex(index=models.Index(fields=["status"], name="attendance_attempt_status_idx"), model_name="attendanceattempt"),
    ]