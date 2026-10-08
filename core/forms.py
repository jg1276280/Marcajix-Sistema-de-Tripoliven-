from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth.models import Group, User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import Error as DatabaseError

from .models import HIDReaderConfig
from .permissions import ROLES, SYSTEMS, user_role
from .security import locked_until, register_failed_login, reset_failed_logins

DATABASE_UNAVAILABLE = "No hay conexión con la base de datos. Inténtalo de nuevo en unos minutos."


class LoginForm(AuthenticationForm):
    username = forms.CharField(label="Usuario", widget=forms.TextInput(attrs={"autocomplete": "username", "placeholder": "Tu usuario"}))
    password = forms.CharField(label="Contraseña", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password", "placeholder": "Tu contraseña"}))
    # Mensajes genéricos: no revelan si el usuario existe ni si la contraseña era la incorrecta.
    error_messages = {
        "invalid_login": "Usuario o contraseña incorrectos.",
        "inactive": "Usuario o contraseña incorrectos.",
        "locked": "Demasiados intentos fallidos. Inténtalo de nuevo en 15 minutos.",
        "no_role": "Tu cuenta no tiene un rol asignado. Contacta con el área de Sistemas.",
    }

    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")
        if not username or not password:
            return self.cleaned_data
        try:
            user = User.objects.filter(username=username).first()
            if user is not None and locked_until(user):
                raise ValidationError(self.error_messages["locked"], code="locked")
            try:
                return super().clean()
            except ValidationError as error:
                if user is not None and user.is_active and error.code != "no_role" and register_failed_login(user):
                    raise ValidationError(self.error_messages["locked"], code="locked") from error
                raise
        except DatabaseError as error:
            raise ValidationError(DATABASE_UNAVAILABLE, code="database") from error

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user_role(user) is None:
            raise ValidationError(self.error_messages["no_role"], code="no_role")
        reset_failed_logins(user)


class UserAccountForm(forms.ModelForm):
    """Alta y edición de cuentas por parte de Sistemas; cada cuenta tiene exactamente un rol."""

    role = forms.ChoiceField(label="Rol", choices=[("", "Selecciona un rol")] + [(role, role) for role in ROLES])
    password1 = forms.CharField(label="Contraseña", strip=False, widget=forms.PasswordInput(attrs={"placeholder": "Contraseña temporal", "autocomplete": "new-password"}))
    password2 = forms.CharField(label="Confirmar contraseña", strip=False, widget=forms.PasswordInput(attrs={"placeholder": "Repite la contraseña", "autocomplete": "new-password"}))

    class Meta:
        model = User
        fields = ("username", "email", "first_name", "last_name", "is_active")

    def __init__(self, *args, acting_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.acting_user = acting_user
        if self.instance.pk:
            self.fields["role"].initial = user_role(self.instance)
            self.fields["password1"].required = False
            self.fields["password2"].required = False
            self.fields["password1"].label = "Nueva contraseña"
            self.fields["password1"].widget.attrs["placeholder"] = "Dejar vacío para conservarla"
            self.fields["password2"].widget.attrs["placeholder"] = "Repite la nueva contraseña"

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        if password1 != cleaned_data.get("password2"):
            self.add_error("password2", "Las contraseñas no coinciden.")
        elif password1:
            candidate = self.instance if self.instance.pk else User(username=cleaned_data.get("username", ""), email=cleaned_data.get("email", ""), first_name=cleaned_data.get("first_name", ""), last_name=cleaned_data.get("last_name", ""))
            try:
                validate_password(password1, candidate)
            except ValidationError as error:
                self.add_error("password1", error)
        is_self = self.acting_user is not None and self.instance.pk == self.acting_user.pk
        if is_self and not cleaned_data.get("is_active", True):
            self.add_error("is_active", "No puedes desactivar tu propia cuenta.")
        if is_self and not self.instance.is_superuser and cleaned_data.get("role") not in (None, SYSTEMS):
            self.add_error("role", "No puedes quitarte el rol de Sistemas a ti mismo.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = user.is_superuser  # El admin de Django queda reservado a superusuarios.
        if self.cleaned_data.get("password1"):
            user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
            user.groups.set([Group.objects.get(name=self.cleaned_data["role"])])
            if user.is_active:
                reset_failed_logins(user)
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
