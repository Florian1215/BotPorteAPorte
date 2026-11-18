"""Django settings for the canvassing web application."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def env_bool(key: str, default: bool = False) -> bool:
    return env(key, "1" if default else "0").lower() in {"1", "true", "yes", "on"}


def env_list(key: str, default: str = "") -> list[str]:
    return [item.strip() for item in env(key, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = env("DJANGO_SECRET_KEY") or ("dev-insecure-secret-key" if DEBUG else "")
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off.")

ALLOWED_HOSTS = ["*"] if DEBUG else env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "rest_framework",
    "accounts",
    "canvassing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "HOST": env("DATABASE_HOST", "db"),
        "PORT": env("DATABASE_PORT", "5432"),
        "NAME": env("POSTGRES_DB", "canvassing"),
        "USER": env("POSTGRES_USER", "canvassing"),
        "PASSWORD": env("POSTGRES_PASSWORD", ""),
        "CONN_MAX_AGE": 60,
    }
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = env("TIME_ZONE", "Europe/Berlin")
USE_I18N = True
USE_TZ = True

# Served by nginx under /django-static/ (Vite owns /assets/).
STATIC_URL = "/django-static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
    # Per IP, on the login endpoints (code requests / guesses); per-email limits are in accounts.views.
    # Generous: a whole local group may log in at once from the same wifi.
    "DEFAULT_THROTTLE_RATES": {"login": "120/hour", "telegram_link": "30/hour"},
    # Client IP taken from X-Forwarded-For as set by our nginx (+1 per extra proxy in front of it).
    "NUM_PROXIES": int(env("NUM_PROXIES", "1")),
}

# Behind nginx
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
# Plain HTTP by default (nginx listens on HTTP_PORT); enable when HTTPS is terminated in front.
SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", False)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30  # 30 days: militants stay logged in on their phone

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}

# --- Canvassing domain settings (ported from the Telegram bot) ---
ORS_TOKEN = env("ORS_TOKEN")
NOMINATIM_DOMAIN = env("NOMINATIM_DOMAIN")  # blank = public nominatim.openstreetmap.org
NOMINATIM_USER_AGENT = env("NOMINATIM_USER_AGENT", "canvassing-web")
# Optional typo-tolerant search (self-hosted Photon server, e.g. photon:2322) used as a last resort for
# hand-typed addresses. Blank = disabled (the public photon.komoot.io blocks bulk use).
PHOTON_DOMAIN = env("PHOTON_DOMAIN")
# Google Maps Platform – Geocoding API: last resort for the addresses OpenStreetMap could not locate (the ones
# already located are never sent to Google). Blank = disabled. Requests per calendar month are capped
# (each address is sent at most once, see `GeocodeCache.google_tried_at`).
GOOGLE_MAPS_API_KEY = env("GOOGLE_MAPS_API_KEY")
GOOGLE_GEOCODING_MONTHLY_LIMIT = int(env("GOOGLE_GEOCODING_MONTHLY_LIMIT", "9000"))
# AI import of the zones (Claude Managed Agents, see canvassing/services/ai_import.py). Blank key = disabled.
# The agent is set up once with `make ai-agent`; each import is capped at AI_IMPORT_BUDGET_USD (list price).
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
AI_IMPORT_BUDGET_USD = float(env("AI_IMPORT_BUDGET_USD", "2"))
CANVASSING_MAX_STOPS = int(env("CANVASSING_MAX_STOPS", "250"))
CANVASSING_TOUR_TIMEOUT_HOURS = int(env("CANVASSING_TOUR_TIMEOUT_HOURS", "24"))
CANVASSING_DRAFT_TIMEOUT_HOURS = 2

# --- Passwordless login (one-time code + link sent by email) ---
LOGIN_CODE_TTL_MINUTES = int(env("LOGIN_CODE_TTL_MINUTES", "15"))
LOGIN_CODE_MAX_ATTEMPTS = 5
LOGIN_CODE_MAX_PER_HOUR = 5  # codes requested per email address
# Public URL of the site, used in the login link (e.g. https://porte-a-porte.example.org). Blank = request host.
PUBLIC_URL = env("PUBLIC_URL").rstrip("/")

# Email: sent with Brevo's API when CLE_API_BREVO is set, else by SMTP when EMAIL_HOST is set,
# else printed in the backend logs (development).
BREVO_API_KEY = env("CLE_API_BREVO")

# Telegram bot (token from @BotFather): lets militant·es link their Telegram account, to get back what they did
# with the old Telegram bot. Its domain must be set to the site's with BotFather's /setdomain. Blank = disabled.
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")
TELEGRAM_BOT_ID = int(TELEGRAM_BOT_TOKEN.split(":")[0]) if TELEGRAM_BOT_TOKEN.split(":")[0].isdigit() else None
EMAIL_HOST = env("EMAIL_HOST")
if BREVO_API_KEY:
    EMAIL_BACKEND = "accounts.brevo.BrevoEmailBackend"
elif EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = 15
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "Porte-à-porte <no-reply@localhost>")

# --- Map tiles (CARTO Voyager basemap) ---
CARTO_API_KEY = env("CARTO_API_KEY")
MAP_TILE_URL = "https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png" + (
    f"?key={CARTO_API_KEY}" if CARTO_API_KEY else ""
)
MAP_TILE_ATTRIBUTION = (
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> '
    '&copy; <a href="https://carto.com/attributions">CARTO</a>'
)
