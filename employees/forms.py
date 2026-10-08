from datetime import date

from django import forms
from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError
import re

from .models import Department, Employee, Management, Position


class EmployeeForm(forms.ModelForm):
    # Gerencia y departamento solo filtran la lista de cargos; el empleado guarda únicamente su cargo.
    management = forms.ModelChoiceField(label="Gerencia", queryset=Management.objects.order_by("name"), required=False, empty_label="Selecciona una gerencia", widget=forms.Select(attrs={"data-management-select": "true"}))
    department = forms.ModelChoiceField(label="Departamento", queryset=Department.objects.select_related("management").order_by("name"), required=False, empty_label="Selecciona un departamento", widget=forms.Select(attrs={"data-department-select": "true"}))
    position = forms.ModelChoiceField(label="Cargo", queryset=Position.objects.select_related("department__management").order_by("name"), empty_label="Selecciona un cargo", widget=forms.Select(attrs={"data-position-select": "true"}))

    class Meta:
        model = Employee
        fields = ("full_name", "identification", "hid_card_code", "status", "position", "emergency_phone", "emergency_contact_name", "photo", "birthday", "hire_date")
        widgets = {
            "full_name": forms.TextInput(attrs={"placeholder": "Nombre completo"}),
            "identification": forms.TextInput(attrs={"placeholder": "Ej. 31395897", "inputmode": "numeric", "maxlength": "8"}),
            "hid_card_code": forms.TextInput(attrs={"placeholder": "Código leído por el dispositivo"}),
            "emergency_phone": forms.TextInput(attrs={"placeholder": "Teléfono opcional"}),
            "emergency_contact_name": forms.TextInput(attrs={"placeholder": "Nombre opcional"}),
            "photo": forms.ClearableFileInput(attrs={"accept": "image/*", "class": "photo-input"}),
            "birthday": forms.DateInput(attrs={"type": "date"}),
            "hire_date": forms.DateInput(attrs={"type": "date"}),
        }

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if not photo and not self.instance.pk:
            raise forms.ValidationError("La foto del empleado es obligatoria.")
        if not photo:
            return photo
        if photo.size > 5 * 1024 * 1024:
            raise forms.ValidationError("La foto no puede superar 5 MB.")
        try:
            image = Image.open(photo)
            image.verify()
            photo.seek(0)
            image_format = (image.format or "").upper()
            if image_format not in {"JPEG", "PNG", "WEBP"}:
                raise forms.ValidationError("La foto debe ser JPG, PNG o WEBP.")
            if image.width > 4000 or image.height > 4000:
                raise forms.ValidationError("La foto no puede superar 4000 x 4000 píxeles.")
        except (UnidentifiedImageError, OSError, SyntaxError) as exc:
            raise forms.ValidationError("El archivo no es una imagen válida.") from exc
        return photo

    def clean_full_name(self):
        value = " ".join(self.cleaned_data["full_name"].split())
        if not re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ' -]+", value):
            raise ValidationError("El nombre solo puede contener letras, espacios, apóstrofes o guiones.")
        return value

    def clean_identification(self):
        value = self.cleaned_data["identification"].strip()
        if not re.fullmatch(r"\d{6,8}", value):
            raise ValidationError("La cédula debe contener solo números y tener entre 6 y 8 dígitos.")
        return value

    def clean_hid_card_code(self):
        value = self.cleaned_data.get("hid_card_code")
        if not value:
            return None
        normalized = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9\-_.]{1,79}", normalized):
            raise ValidationError("El código de tarjeta solo admite letras, números, guiones y puntos.")
        if Employee.objects.filter(hid_card_code__iexact=normalized).exclude(pk=self.instance.pk).exists():
            raise ValidationError("Ya existe un empleado con este código de tarjeta.")
        return normalized

    def clean_emergency_phone(self):
        value = (self.cleaned_data.get("emergency_phone") or "").strip()
        if not value:
            return ""
        normalized = value.replace(" ", "")
        if not re.fullmatch(r"\+?\d{8,15}", normalized):
            raise ValidationError("El teléfono de emergencia debe contener solo números y tener entre 8 y 15 dígitos.")
        return normalized

    def clean_hire_date(self):
        value = self.cleaned_data.get("hire_date")
        if not value:
            raise ValidationError("La fecha de ingreso es obligatoria.")
        if value > date.today():
            raise ValidationError("La fecha de ingreso no puede ser posterior a la fecha actual.")
        return value

    def clean(self):
        cleaned_data = super().clean()
        management = cleaned_data.get("management")
        department = cleaned_data.get("department")
        position = cleaned_data.get("position")
        if management and department and department.management_id != management.pk:
            self.add_error("department", "El departamento no pertenece a la gerencia seleccionada.")
        if department and position and position.department_id != department.pk:
            self.add_error("position", "El cargo no pertenece al departamento seleccionado.")
        elif management and position and position.department.management_id != management.pk:
            self.add_error("position", "El cargo no pertenece a la gerencia seleccionada.")
        return cleaned_data

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["department"].initial = self.instance.position.department_id
            self.fields["management"].initial = self.instance.position.department.management_id
        for field in self.fields.values():
            field.help_text = "Campo requerido" if field.required else "Campo opcional"


class ManagementForm(forms.ModelForm):
    class Meta:
        model = Management
        fields = ("name",)
        widgets = {"name": forms.TextInput(attrs={"placeholder": "Ej. Recursos Humanos"})}


class ManagementRenameForm(forms.ModelForm):
    class Meta:
        model = Management
        fields = ("name",)
        widgets = {"name": forms.TextInput(attrs={"autocomplete": "off"})}


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ("management", "name")
        widgets = {"name": forms.TextInput(attrs={"placeholder": "Ej. Nómina"})}


class DepartmentRenameForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ("name",)
        widgets = {"name": forms.TextInput(attrs={"autocomplete": "off"})}

class PositionForm(forms.ModelForm):
    class Meta:
        model = Position
        fields = ("department", "name")
        widgets = {"name": forms.TextInput(attrs={"placeholder": "Ej. Analista de nómina"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.select_related("management").order_by("management__name", "name")


class PositionRenameForm(forms.ModelForm):
    class Meta:
        model = Position
        fields = ("name",)
        widgets = {"name": forms.TextInput(attrs={"autocomplete": "off"})}
