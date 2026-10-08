from django.db import migrations, models
import django.db.models.deletion


def canonical_department_name(value):
    name = " ".join((value or "Sin departamento").split())
    aliases = {"Sistema": "Sistemas"}
    return aliases.get(name, name)


def migrate_departments(apps, schema_editor):
    Department = apps.get_model("employees", "Department")
    Employee = apps.get_model("employees", "Employee")
    for employee in Employee.objects.all().iterator():
        department, _ = Department.objects.get_or_create(name=canonical_department_name(employee.department))
        employee.department_ref_id = department.pk
        employee.save(update_fields=["department_ref"])


class Migration(migrations.Migration):
    dependencies = [("employees", "0005_employee_status")]

    operations = [
        migrations.CreateModel(
            name="Department",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True, verbose_name="Nombre")),
            ],
            options={
                "db_table": "employees_department",
                "ordering": ("name",),
                "verbose_name": "Departamento",
                "verbose_name_plural": "Departamentos",
            },
        ),
        migrations.AddField(
            model_name="employee",
            name="department_ref",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="employees", to="employees.department", verbose_name="Departamento"),
        ),
        migrations.RunPython(migrate_departments, migrations.RunPython.noop),
        migrations.RemoveField(model_name="employee", name="department"),
        migrations.RenameField(model_name="employee", old_name="department_ref", new_name="department"),
        migrations.AlterField(
            model_name="employee",
            name="department",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="employees", to="employees.department", verbose_name="Departamento"),
        ),
    ]
