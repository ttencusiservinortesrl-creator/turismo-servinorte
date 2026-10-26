"""Configuración del cotizador de turismo de Servinorte SRL."""

import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def _secret_key():
    """La clave sale de DJANGO_SECRET_KEY (en Render se genera sola). Si no está
    definida (PC local) se genera una y se guarda en .secret_key, que no se sube a GitHub."""
    clave = os.environ.get('DJANGO_SECRET_KEY')
    if clave:
        return clave
    archivo = BASE_DIR / '.secret_key'
    if archivo.exists():
        return archivo.read_text().strip()
    from django.core.management.utils import get_random_secret_key
    clave = get_random_secret_key()
    archivo.write_text(clave)
    return clave


SECRET_KEY = _secret_key()

# Seguro por defecto: DEBUG apagado. Para desarrollo local: DJANGO_DEBUG=True
DEBUG = env_bool('DJANGO_DEBUG', False)

# En línea (Render) se define DJANGO_ONLINE=True o Render pone la variable RENDER.
ONLINE = env_bool('DJANGO_ONLINE', bool(os.environ.get('RENDER')))

ALLOWED_HOSTS = [h.strip() for h in os.environ.get('DJANGO_ALLOWED_HOSTS', '*').split(',') if h.strip()]

_csrf_origins = os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', '')
CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_origins.split(',') if o.strip()]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'cotizador',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'turismo.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'turismo.wsgi.application'

# Sin DATABASE_URL usa SQLite (PC local). En línea, DATABASE_URL apunta a PostgreSQL (Supabase).
_usa_base_externa = bool(os.environ.get('DATABASE_URL'))

DATABASES = {
    'default': dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True,
        ssl_require=_usa_base_externa and env_bool('DJANGO_DB_SSL', True),
    )
}
if _usa_base_externa:
    # Compatible con el pooler de Supabase (modo transacción): sin cursores del lado del servidor.
    DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS'] = True

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'es-ar'
TIME_ZONE = 'America/Argentina/Salta'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
# WhiteNoise sirve los estáticos directamente desde STATICFILES_DIRS (sin collectstatic).
WHITENOISE_USE_FINDERS = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'cotizador:lista'
LOGOUT_REDIRECT_URL = 'login'

# Identificación para los servicios de mapas gratuitos (OpenStreetMap la exige).
MAPAS_USER_AGENT = os.environ.get(
    'MAPAS_USER_AGENT', 'ServinorteTurismo/1.1 (cotizador de viajes; +https://servinorte-turismo.onrender.com)')

# Los errores (por ejemplo, si el mapa no responde) quedan en los registros de Render.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'consola': {'class': 'logging.StreamHandler'}},
    'loggers': {'cotizador': {'handlers': ['consola'], 'level': 'INFO'}},
}

# Seguridad cuando el sistema está publicado en internet (HTTPS obligatorio).
if ONLINE:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env_bool('DJANGO_SECURE_SSL_REDIRECT', True)
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 7
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SESSION_COOKIE_AGE = 60 * 60 * 12  # la sesión se cierra sola a las 12 horas
