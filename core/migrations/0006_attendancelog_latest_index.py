from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0005_alter_attendancelog_capture_mode_and_more")]

    operations = [
        migrations.AddIndex(
            model_name="attendancelog",
            index=models.Index(fields=("employee", "-marked_at", "-id"), name="attendance_latest_idx"),
        ),
    ]