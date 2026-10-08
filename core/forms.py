from django import forms
from django.core.exceptions import ValidationError
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm
from django.contrib.auth.models import User
from django.db import Error as DatabaseError

from .models import HIDReaderConfig
from .security import register_failed_login, reset_failed_logins


class LoginForm(AuthenticationForm):
    username = forms.CharField(label="Usuario", widget=forms.TextInput(attrs={"autocomplete": "username", "placeholder": "Tu usuario"}))
    password = forms.CharField(label="Contraseña", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password", "placeholder": "Tu contraseña"}))

    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")
        try:
            user = User.objects.filter(username=username).first() if username else None
            if username and user is None:
                raise ValidationError("El usuario no existe. Verifica el nombre de usuario e inténtalo de nuevo.")
            if user and not user.is_active and password and user.check_password(password):
                raise ValidationError("Esta cuenta está inactiva. Contacta con un administrador para activarla.")
            if username and password:
                cleaned_data = super().clean()
                reset_failed_logins(user.pk)
                return cleaned_data
            return super().clean()
        except DatabaseError:
            raise ValidationError("No hay conexión con la base de datos. Inténtalo de nuevo en unos minutos.")
        except ValidationError:
            if user and user.is_active and password and not user.check_password(password):
                try:
                    attempts, locked = register_failed_login(user.pk)
                except DatabaseError:
                    raise ValidationError("No hay conexión con la base de datos. Inténtalo de nuevo en unos minutos.")
                if locked:
                    raise ValidationError("Tu cuenta ha sido bloqueada tras 3 intentos fallidos. Un administrador debe activarla.")
                remaining = 3 - attempts
                raise ValidationError(f"Credenciales inválidas. Te quedan {remaining} intento(s) antes del bloqueo.")
            raise


class RegisterForm(UserCreationForm):
    email = forms.EmailField(label="Correo electrónico", required=True, widget=forms.EmailInput(attrs={"placeholder": "nombre@empresa.com", "autocomplete": "email"}))

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class AdminUserCreateForm(forms.ModelForm):
    password1 = forms.CharField(label="Contraseña", widget=forms.PasswordInput(attrs={"placeholder": "Contraseña temporal"}))
    password2 = forms.CharField(label="Confirmar contraseña", widget=forms.PasswordInput(attrs={"placeholder": "Repite la contraseña"}))

    class Meta:
        model = User
        fields = ("username", "email", "first_name", "last_name", "is_active", "is_staff")

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("password1") != cleaned_data.get("password2"):
            self.add_error("password2", "Las contraseñas no coinciden.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class AdminUserUpdateForm(forms.ModelForm):
    password1 = forms.CharField(label="Nueva contraseña", required=False, widget=forms.PasswordInput(attrs={"placeholder": "Dejar vacío para conservarla"}))
    password2 = forms.CharField(label="Confirmar contraseña", required=False, widget=forms.PasswordInput(attrs={"placeholder": "Repite la nueva contraseña"}))

    class Meta:
        model = User
        fields = ("username", "email", "first_name", "last_name", "is_active", "is_staff")

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("password1") != cleaned_data.get("password2"):
            self.add_error("password2", "Las contraseñas no coinciden.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("password1"):
            user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email")
        labels = {"first_name": "Nombre", "last_name": "Apellidos", "email": "Correo electrónico"}
        widgets = {
            "first_name": forms.TextInput(attrs={"placeholder": "Tu nombre"}),
            "last_name": forms.TextInput(attrs={"placeholder": "Tus apellidos"}),
            "email": forms.EmailInput(attrs={"placeholder": "nombre@empresa.com"}),
        }


class ProfilePasswordForm(PasswordChangeForm):
    old_password = forms.CharField(label="Contraseña actual", widget=forms.PasswordInput(attrs={"placeholder": "Tu contraseña actual", "autocomplete": "current-password"}))
    new_password1 = forms.CharField(label="Nueva contraseña", widget=forms.PasswordInput(attrs={"placeholder": "Nueva contraseña", "autocomplete": "new-password"}))
    new_password2 = forms.CharField(label="Confirmar contraseña", widget=forms.PasswordInput(attrs={"placeholder": "Repite la nueva contraseña", "autocomplete": "new-password"}))


class HIDReaderConfigForm(forms.ModelForm):
    class Meta:
        model = HIDReaderConfig
        fields = ("name", "port", "baud_rate", "data_bits", "parity", "stop_bits", "timeout", "wiegand_format", "is_active")
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Garita Principal"}),
            "port": forms.TextInput(attrs={"placeholder": "COM3"}),
            "timeout": forms.NumberInput(attrs={"min": "0.1", "step": "0.1"}),
            "is_active": forms.CheckboxInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "checkbox" if name == "is_active" else "select" if isinstance(field.widget, forms.Select) else "input")
