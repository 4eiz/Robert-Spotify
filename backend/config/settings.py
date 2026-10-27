import os
from pathlib import Path
import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR.parent / '.env')
DEBUG = os.getenv('DEBUG', '0') == '1'
SECRET_KEY = os.environ['DJANGO_SECRET_KEY']
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
INSTALLED_APPS = ['django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions', 'rest_framework', 'ledger']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'ledger.middleware.PrivateResponseMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware']
ROOT_URLCONF = 'config.urls'
DATABASES = {'default': dj_database_url.config(default=f'sqlite:///{BASE_DIR / "local.sqlite3"}', conn_max_age=60)}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
TIME_ZONE = 'Europe/Minsk'
USE_TZ = True
LANGUAGE_CODE = 'ru'
REST_FRAMEWORK = {'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework.authentication.SessionAuthentication'], 'DEFAULT_PERMISSION_CLASSES': ['ledger.auth.OwnerOnly'], 'DEFAULT_THROTTLE_CLASSES': ['rest_framework.throttling.AnonRateThrottle'], 'DEFAULT_THROTTLE_RATES': {'anon': '30/min'}}
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
CSRF_TRUSTED_ORIGINS = os.getenv('CSRF_TRUSTED_ORIGINS', 'http://localhost:3000,http://127.0.0.1:3000').split(',')
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
X_FRAME_OPTIONS = 'DENY'
LOCAL_DEV_LOGIN = DEBUG and os.getenv('LOCAL_DEV_LOGIN') == '1'
OWNER_TELEGRAM_ID = os.getenv('OWNER_TELEGRAM_ID', '')
TELEGRAM_CLIENT_ID = os.getenv('TELEGRAM_CLIENT_ID', '')
TELEGRAM_CLIENT_SECRET = os.getenv('TELEGRAM_CLIENT_SECRET', '')
TELEGRAM_REDIRECT_URI = os.getenv('TELEGRAM_REDIRECT_URI', 'http://localhost:3000/api/auth/callback/')
FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:3000')
FIELD_ENCRYPTION_KEY = os.environ['FIELD_ENCRYPTION_KEY']
TELEGRAM_NOTIFICATION_TOKEN = os.getenv('TELEGRAM_NOTIFICATION_TOKEN', '')
SESSION_COOKIE_AGE = 60 * 60 * 12
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_REFERRER_POLICY = 'no-referrer'
DATA_UPLOAD_MAX_MEMORY_SIZE = 64 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 100
REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES'] = ['rest_framework.renderers.JSONRenderer']
REST_FRAMEWORK['DEFAULT_PARSER_CLASSES'] = ['rest_framework.parsers.JSONParser']
