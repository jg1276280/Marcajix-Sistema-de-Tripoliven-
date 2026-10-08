from django.db import migrations, models


def migrate_employee_statuses(apps, schema_editor):
    Employee = apps.get_model("employees", "Employee")
    Employee.objects.filter(is_active=False).update(status="inactive")
    Employee.objects.filter(is_active=True).update(status="active")


class Migration(migrations.Migration):
    dependencies = [("employees", "0004_alter_employee_hid_card_code")]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="status",
            field=models.CharField(choices=[("active", "Activo"), ("inactive", "Inactivo"), ("retired", "Retirado"), ("vacation", "Vacaciones"), ("suspended", "Suspendido")], db_index=True, default="active", max_length=10, verbose_name="Estado"),
        ),
        migrations.RunPython(migrate_employee_statuses, migrations.RunPython.noop),
        migrations.RemoveField(model_name="employee", name="is_active"),
    ]