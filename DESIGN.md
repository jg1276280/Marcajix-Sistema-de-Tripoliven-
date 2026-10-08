# Marcajix · Guía de diseño

Interfaz clara, minimalista y práctica para el control de acceso de Tripoliven.

## Principios
- **Un solo color de marca.** El rojo Tripoliven (`--brand: #c8102e`) se reserva para la acción principal de cada pantalla, el elemento activo del menú y los datos destacados (horas extra). Todo lo demás va en grises neutros.
- **Legibilidad primero.** Texto base de 14 px, títulos de 18 a 24 px y números tabulares para horas y fechas. Fuentes del sistema (Segoe UI en Windows): sin dependencias de internet.
- **Bordes redondeados y sombras suaves.** 8 px en controles, 12 px en avisos y 16 px en tarjetas.
- **El estado se comunica con color y texto a la vez:** verde (entrada, activo), azul (salida, vacaciones), ámbar (advertencias, incidencias) y rojo (denegado, errores).

## Archivos
- `static/css/marcajix.css`: tokens (`:root`) y todos los componentes. No se usan estilos en línea, salvo la altura dinámica de las barras del gráfico.
- `static/js/marcajix.js`: escapado de HTML, avisos, modales (`<dialog>`), menú móvil y `pollFeed` para los datos en vivo.
- `templates/partials/`: iconos (sprite SVG), campo de formulario, fila de evento, estado del empleado y paginación.
- `core/templatetags/ui.py`: `{% icon "nombre" %}`, el filtro `|hm` (horas en H:MM) y el filtro `|initials`.

## Componentes
`btn` (`btn-primary`, `btn-secondary`, `btn-ghost`, `btn-danger`, `btn-sm`, `btn-icon`) · `card` (`card-header`, `card-body`, `card-footer`) · `kpis`/`kpi` · `table` · `badge-*` · `status-live` · `list`/`list-item` · `bars` (gráfico) · `segmented` · `filters` · `field` · `modal` · `toast` · `empty` · `facts` · `people-grid`/`person-card`.

## Kiosco
`templates/dashboard/kiosk/live.html` es independiente: tipografía grande para leerse a distancia, ENTRADA en verde, SALIDA en rojo y alertas en ámbar o rojo oscuro.
