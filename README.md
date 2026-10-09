# Marcajix · Control de asistencia de Tripoliven

Sistema de control de entradas y salidas por la garita, con lector de tarjetas HID.

## Cómo funciona

```
                    PC DE LA GARITA (servidor)
 ┌─────────────────────────────────────────────────────────────┐
 │  Lector HID ──► "Marcajix\Lector HID" ──┐                   │
 │                (tarea en 2.º plano)     ▼                   │
 │                                   SQL Server Express        │
 │                                         ▲                   │
 │  "Marcajix\Servidor" (web, puerto 8000) ┘                   │
 │      │                     │                                │
 │      ▼                     ▼                                │
 │  Monitor exterior      Monitor interior                     │
 │  KIOSCO (sin sesión)   PANEL del inspector (con sesión)     │
 └──────┬──────────────────────────────────────────────────────┘
        │ red interna de la empresa
        ▼
  Otras PCs (RRHH, Sistemas…) → http://NOMBRE-PC-GARITA:8000/
```

- **El lector y el servidor web arrancan con Windows** como tareas programadas, aunque nadie
  haya iniciado sesión en Marcajix. Si se cierran por un error, Windows los reinicia solos.
- **El kiosco exterior no necesita sesión.** Solo la propia PC de la garita puede verlo sin
  usuario (se reconoce por su IP; ver `KIOSK_DISPLAY_IPS`). Muestra la foto, el nombre,
  el departamento, si es ENTRADA o SALIDA y la hora de cada tarjeta leída. También avisa si la
  tarjeta no está registrada o si el empleado no tiene acceso.
- **El panel interior** es para el inspector de Seguridad: inicia sesión con su usuario, ve
  los marcajes en vivo y puede registrar marcajes manuales de empleados sin tarjeta.
- El resto de PCs entra por la red con el navegador. Cada usuario ve lo que su rol permite:
  **Sistemas** (todo), **Seguridad** (garita y marcajes) y **Recursos Humanos** (personal y reportes).

## Instalación en la PC de la garita (desde cero)

Requisitos: Windows 10 u 11, conexión a internet durante la instalación y una cuenta de Windows
con permisos de administrador (la misma que usará la garita a diario).

1. **Descargar el sistema.** En GitHub: botón verde **Code → Download ZIP**. Descomprímalo en
   `C:\Marcajix`. No lo ponga en el Escritorio, en Descargas ni dentro de OneDrive.
   *(Alternativa con Git: `git clone <url-del-repositorio> C:\Marcajix`, que permite actualizar
   con un clic.)*
2. **Doble clic en `C:\Marcajix\INSTALAR.bat`** y elija la opción **1 (PC de la garita)**.
   El instalador:
   - instala Python 3.12, el driver ODBC 18 y, si lo indica, SQL Server 2022 Express;
   - crea la configuración (`.env`) con una clave secreta propia y la base de datos;
   - le pide crear el **usuario administrador**;
   - abre el puerto 8000 en el firewall para las demás PCs;
   - registra el servidor y el lector para que arranquen con Windows. Le pedirá la contraseña
     de Windows: con ella funcionan aunque nadie haya iniciado sesión;
   - crea en el escritorio los accesos **Marcajix** (panel) y **Marcajix Garita** (abre las dos
     pantallas) y, si quiere, hace que las pantallas se abran solas al iniciar sesión.
3. **Conecte el monitor exterior como segunda pantalla** (Configuración → Sistema → Pantalla →
   *Extender estas pantallas*). La pantalla **principal** será la del inspector, y la otra mostrará
   el kiosco a pantalla completa.
4. **Entre con el administrador** (acceso *Marcajix*) y:
   - en **Dispositivos / Garita**, ponga el puerto COM del lector (Administrador de dispositivos →
     Puertos COM y LPT) y pulse *Probar lectura*;
   - en **Estructura**, cree gerencias, departamentos y cargos;
   - en **Usuarios**, cree las cuentas de los inspectores (rol Seguridad) y de RRHH;
   - en **Personal**, registre a los empleados con su foto y su código de tarjeta.
5. **Recomendado para la garita:**
   - Que Windows inicie sesión solo tras un corte de luz, así las pantallas se abren otra vez
     sin intervención (ejecute `netplwiz` y desmarque *Los usuarios deben escribir su nombre y
     contraseña*).
   - Asigne a esta PC una **IP fija** o use siempre su nombre de equipo para entrar desde las
     demás PCs.

## Acceso desde las demás PCs

No hace falta instalar nada: abra en el navegador `http://NOMBRE-PC-GARITA:8000/` (el
instalador muestra la dirección exacta al terminar). Si prefiere un acceso directo en el
escritorio, copie la carpeta en esa PC, ejecute `INSTALAR.bat` y elija la opción **2**.

## Funciones por rol

- **Seguridad:** Garita (en vivo y registro manual), **Presencia** (dentro, salieron hoy, sin marcar),
  Movimientos y **Alertas** de la puerta (accesos denegados, tarjetas desconocidas insistentes,
  personas con demasiadas horas dentro y lector desconectado).
- **Recursos Humanos:** Personal, fichas con horas y horas extra, Reportes con exportación a Excel y,
  si Sistemas lo activa, **correcciones de marcajes** (añadir olvidos o anular errores, siempre con
  motivo y registradas en la auditoría).
- **Sistemas:** todo lo anterior, más Usuarios, Estructura, Lector HID, Auditoría y **Sistema**
  (respaldos y activación de correcciones).
- **Kiosco:** celebra con confeti el **cumpleaños** y el **aniversario laboral** de quien marca ese día.

## Respaldos de la base de datos

En **Sistema → Respaldos automáticos**: active el respaldo diario, pulse **Examinar…** para elegir la
carpeta (o escriba la ruta de red `\\SERVIDOR\Carpeta`), pulse **Probar carpeta** y luego **Respaldar
ahora** para comprobarlo. Marcajix borra solo sus respaldos más antiguos que los días indicados.

- Use rutas de red completas: las letras de unidad conectadas (Z:) no existen para el servicio.
- La cuenta de Windows con la que corre Marcajix necesita permiso de escritura en esa carpeta.
- Si SQL Server está en otro servidor, la carpeta debe ser accesible también para la cuenta del
  servicio de SQL Server de ese servidor.
- Si un respaldo falla o pasan 48 h sin uno correcto, Sistemas recibe una alerta.

## Actualizar

Doble clic en **`ACTUALIZAR.bat`**. Detiene el sistema, descarga la versión nueva (si se instaló
con Git), actualiza dependencias y base de datos, y vuelve a arrancar.

Si se instaló desde un ZIP: descargue el ZIP nuevo y descomprímalo **encima** de `C:\Marcajix`
(se conservan `.env`, `media` y `logs`). Después ejecute `ACTUALIZAR.bat`.

## Solución de problemas

| Síntoma | Qué revisar |
|---|---|
| El kiosco dice *Lector sin conexión* | Puerto COM correcto en *Dispositivos*; `logs\lector.log` |
| El kiosco dice *Sin conexión con el servidor* | `logs\servidor.log`; Programador de tareas → carpeta *Marcajix* |
| Otras PCs no abren la página | Que la red de la garita esté como *Privada* o de *Dominio*; regla de firewall *Marcajix* |
| Cambió la IP de la garita | Añádala a `ALLOWED_HOSTS` y `CSRF_TRUSTED_ORIGINS` en `.env` y reinicie la PC |

Las tareas se pueden detener, iniciar o revisar en **Programador de tareas → Biblioteca →
Marcajix**.

## Configuración (`.env`)

El instalador lo genera. Las variables principales están documentadas en `.env.example`:
la base de datos (`DB_*`), los equipos que pueden ver el kiosco sin sesión (`KIOSK_DISPLAY_IPS`),
la zona horaria (`TIME_ZONE`), la jornada de referencia para las horas extra
(`ATTENDANCE_WORKDAY_HOURS`, 8 h), las horas máximas de una sesión antes de considerarla un olvido de
marcaje (`ATTENDANCE_MAX_SESSION_HOURS`, 16 h) y los segundos en que se ignora una segunda pasada de la
misma tarjeta (`HID_REPEAT_SECONDS`, 60 s).
