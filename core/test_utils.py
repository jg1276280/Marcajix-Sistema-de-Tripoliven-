from io import BytesIO
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile


def create_test_image(name="test.png", size=(40, 40), color="green", image_format="PNG"):
    """Genera una imagen sintética en memoria para pruebas unitarias de Django."""
    image = Image.new("RGB", size, color)
    content = BytesIO()
    image.save(content, format=image_format)
    return SimpleUploadedFile(name, content.getvalue(), content_type=f"image/{image_format.lower()}")


def create_user_with_role(username, role, password="ValidPassword123!", **extra):
    """Crea un usuario de prueba asignado al grupo del rol indicado (Sistemas, Seguridad o Recursos Humanos)."""
    from django.contrib.auth.models import Group, User

    user = User.objects.create_user(username=username, password=password, **extra)
    user.groups.add(Group.objects.get(name=role))
    return user
