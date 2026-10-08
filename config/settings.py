import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
# Por defecto en modo producción: el modo de desarrollo hay que activarlo explícitamente en .env.
DEBUG = os.getenv("DEBUG", "False").lower() == "true"
ALLOWED_HOSTS = [host.strip() for host in os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if host.strip()]
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if origin.strip()]


def env_bool(name, default=False):
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


if not DEBUG and (SECRET_KEY == "dev-only-change-me" or len(SECRET_KEY) < 50):
    raise ImproperlyConfigured("SECRET_KEY debe ser aleatoria y tener al menos 50 caracteres en producción.")
if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured("ALLOWED_HOSTS debe contener al menos un host en producción.")

INSTALLED_APPS = ["django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles", "channels", "core.apps.CoreConfig", "employees.apps.EmployeesConfig"]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware", "whitenoise.middleware.WhiteNoiseMiddleware", "django.contrib.sessions.middleware.SessionMiddleware", "django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware", "django.contrib.auth.middleware.AuthenticationMiddleware", "core.middleware.SessionExpiryMiddleware", "django.contrib.messages.middleware.MessageMiddleware", "django.middleware.clickjacking.XFrameOptionsMiddleware", "core.middleware.SlowQueryLoggingMiddleware"]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True, "OPTIONS": {"context_processors": ["django.template.context_processors.request", "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages", "core.context_processors.access"]}}]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.routing.application"
# El lector HID (manage.py listen_hid) corre en un proceso aparte del servidor web. Para que sus
# eventos lleguen en vivo al kiosco y al monitor hace falta una capa compartida (Redis/Memurai).
CHANNEL_REDIS_URL = os.getenv("CHANNEL_REDIS_URL", "").strip()
if CHANNEL_REDIS_URL:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels_redis.core.RedisChannelLayer", "CONFIG": {"hosts": [CHANNEL_REDIS_URL]}}}
else:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

db_engine = os.getenv("DB_ENGINE", "").lower()
if db_engine not in {"mssql", "sql_server", "sqlserver"}:
    raise ImproperlyConfigured("SQL Server es obligatorio. Configura DB_ENGINE=sql_server en el archivo .env.")

db_name = os.getenv("DB_NAME", "").strip()
db_host = os.getenv("DB_HOST", "").strip()
db_auth = os.getenv("DB_AUTH", "sql").lower()
if not db_name or not db_host:
    raise ImproperlyConfigured("Faltan DB_NAME o DB_HOST en el archivo .env.")
if db_auth not in {"sql", "windows", "trusted"}:
    raise ImproperlyConfigured("DB_AUTH debe ser sql o windows en el archivo .env.")
if db_auth == "sql" and (not os.getenv("DB_USER", "").strip() or not os.getenv("DB_PASSWORD", "")):
    raise ImproperlyConfigured("DB_USER y DB_PASSWORD son obligatorios con DB_AUTH=sql.")

db_options = {
    "driver": os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server"),
    "connection_timeout": int(os.getenv("DB_CONNECTION_TIMEOUT", "5")),
    "query_timeout": int(os.getenv("DB_QUERY_TIMEOUT", "30")),
    "connection_retries": int(os.getenv("DB_CONNECTION_RETRIES", "0")),
    "connection_retry_backoff_time": int(os.getenv("DB_CONNECTION_RETRY_BACKOFF", "0")),
    "extra_params": f"TrustServerCertificate={os.getenv('DB_TRUST_CERT', 'yes')};",
}
if db_auth in {"windows", "trusted"}:
    db_options["extra_params"] = "Trusted_Connection=yes;TrustServerCertificate=yes;"
DATABASES = {"default": {"ENGINE": "mssql", "NAME": db_name, "USER": "" if db_auth in {"windows", "trusted"} else os.getenv("DB_USER", ""), "PASSWORD": "" if db_auth in {"windows", "trusted"} else os.getenv("DB_PASSWORD", ""), "HOST": db_host, "PORT": os.getenv("DB_PORT", "1433"), "OPTIONS": db_options, "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "300")), "CONN_HEALTH_CHECKS": True}}

AUTH_PASSWORD_VALIDATORS = [{"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"}, {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"}, {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"}, {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"}]
LANGUAGE_CODE = "es-es"
TIME_ZONE = os.getenv("TIME_ZONE", "America/Caracas")

# Jornada de referencia (horas) para calcular el balance y las horas extra de cada empleado.
ATTENDANCE_WORKDAY_HOURS = float(os.getenv("ATTENDANCE_WORKDAY_HOURS", "8"))
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"
SESSION_MAX_AGE = 12 * 60 * 60
SESSION_COOKIE_AGE = SESSION_MAX_AGE
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE")
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE")
CSRF_COOKIE_HTTPONLY = True  # Los formularios y fetch leen el token del DOM, nunca de la cookie.
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT")
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS")
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD")
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

SLOW_QUERY_THRESHOLD_MS = float(os.getenv("SLOW_QUERY_THRESHOLD_MS", "200"))
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "performance": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "performance",
        },
    },
    "loggers": {
        "performance.sql": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}
