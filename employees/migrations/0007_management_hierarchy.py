from django.db import migrations, models
import django.db.models.deletion


def migrate_managements(apps, schema_editor):
    Management = apps.get_model("employees", "Management")
    Department = apps.get_model("employees", "Department")
    Employee = apps.get_model("employees", "Employee")
    managements = {}
    for employee in Employee.objects.all().iterator():
        management_name = " ".join((employee.management or "Sin gerencia").split())
        management = managements.get(management_name)
        if management is None:
            management, _ = Management.objects.get_or_create(name=management_name)
            managements[management_name] = management
        employee.management_ref_id = management.pk
        employee.save(update_fields=["management_ref"])
        department = Department.objects.get(pk=employee.department_id)
        if department.management_id is None:
            department.management_id = management.pk
            department.save(update_fields=["management"])
    default_management, _ = Management.objects.get_or_create(name="Sin gerencia")
    Department.objects.filter(management_id__isnull=True).update(management_id=default_management.pk)


def reverse_managements(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("employees", "0006_department_catalog")]

    operations = [
        migrations.CreateModel(
            name="Management",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True, verbose_name="Nombre")),
            ],
            options={
                "db_table": "employees_management",
                "ordering": ("name",),
                "verbose_name": "Gerencia",
                "verbose_name_plural": "Gerencias",
            },
        ),
        migrations.AddField(
            model_name="department",
            name="management",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="departments", to="employees.management", verbose_name="Gerencia"),
        ),
        migrations.AddField(
            model_name="employee",
            name="management_ref",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="employees_legacy", to="employees.management", verbose_name="Gerencia"),
        ),
        migrations.RunPython(migrate_managements, reverse_managements),
        migrations.RemoveField(model_name="employee", name="management"),
        migrations.RenameField(model_name="employee", old_name="management_ref", new_name="management"),
        migrations.AlterField(
            model_name="department",
            name="management",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="departments", to="employees.management", verbose_name="Gerencia"),
        ),
        migrations.AlterField(
            model_name="employee",
            name="management",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="employees", to="employees.management", verbose_name="Gerencia"),
        ),
    ]
