"""Utilidades de presentación: iconos del sprite, duración en horas e iniciales."""
from django import template
from django.utils.html import format_html

register = template.Library()


@register.simple_tag
def icon(name, size=""):
    """<svg> que referencia un símbolo del sprite de partials/icons.html (p. ej. {% icon "home" %})."""
    css = "icon icon-sm" if size == "sm" else "icon"
    return format_html('<svg class="{}" aria-hidden="true"><use href="#i-{}"/></svg>', css, name)


@register.filter
def hm(hours):
    """Horas decimales a H:MM (9.5 → "9:30"). Vacío si no hay valor."""
    if hours in (None, ""):
        return ""
    minutes = round(float(hours) * 60)
    return f"{minutes // 60}:{minutes % 60:02d}"


@register.filter
def initials(name):
    parts = [part for part in str(name or "").split() if part]
    return "".join(part[0] for part in parts[:2]).upper() or "?"
