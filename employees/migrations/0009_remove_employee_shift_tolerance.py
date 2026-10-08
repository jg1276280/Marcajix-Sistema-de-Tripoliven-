from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("employees", "0008_employee_work_schedule")]

    operations = [
        migrations.RemoveField(model_name="employee", name="expected_start_time"),
        migrations.RemoveField(model_name="employee", name="punctuality_tolerance_minutes"),
    ]