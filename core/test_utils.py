from io import BytesIO
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile


def create_test_image(name="test.png", size=(40, 40), color="green", image_format="PNG"):
    """Genera una imagen sintética en memoria para pruebas unitarias de Django."""
    image = Image.new("RGB", size, color)
    content = BytesIO()
    image.save(content, format=image_format)
    return SimpleUploadedFile(name, content.getvalue(), content_type=f"image/{image_format.lower()}")
