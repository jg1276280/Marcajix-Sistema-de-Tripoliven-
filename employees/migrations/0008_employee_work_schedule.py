from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("employees", "0007_management_hierarchy")]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="expected_start_time",
            field=models.TimeField(default="08:00", verbose_name="Hora esperada de entrada"),
        ),
        migrations.AddField(
            model_name="employee",
            name="workday_hours",
            field=models.DecimalField(decimal_places=2, default=8, max_digits=4, verbose_name="Horas de jornada"),
        ),
        migrations.AddField(
            model_name="employee",
            name="punctuality_tolerance_minutes",
            field=models.PositiveSmallIntegerField(default=15, verbose_name="Tolerancia de puntualidad (minutos)"),
        ),
    ]
