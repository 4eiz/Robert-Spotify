import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode
import jwt
import requests
from django.conf import settings
from django.contrib.auth import login, logout, get_user_model
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST
from rest_framework.permissions import BasePermission

class OwnerOnly(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user.is_authenticated and request.session.get('owner_verified') and
            ((request.session.get('telegram_id') == settings.OWNER_TELEGRAM_ID and settings.OWNER_TELEGRAM_ID)
             or (settings.LOCAL_DEV_LOGIN and request.session.get('local_dev') and request.META.get('REMOTE_ADDR') in ('127.0.0.1', '::1'))))

def session_info(request):
    allowed = OwnerOnly().has_permission(request, None)
    return JsonResponse({'authenticated': allowed, 'csrfToken': get_token(request), 'local_dev': settings.LOCAL_DEV_LOGIN,
        'telegram_configured': bool(settings.TELEGRAM_CLIENT_ID and settings.TELEGRAM_CLIENT_SECRET and settings.OWNER_TELEGRAM_ID)})

def establish(request, telegram_id=None, local=False):
    user, _ = get_user_model().objects.get_or_create(username='owner', defaults={'is_staff': True})
    if user.has_usable_password():
        user.set_unusable_password()
        user.save(update_fields=['password'])
    login(request, user)
    request.session['owner_verified'] = True
    request.session['telegram_id'] = telegram_id
    request.session['local_dev'] = local

@require_POST
@csrf_protect
def local_login(request):
    if not settings.LOCAL_DEV_LOGIN or request.META.get('REMOTE_ADDR') not in ('127.0.0.1', '::1'):
        return JsonResponse({'detail': 'Недоступно'}, status=403)
    establish(request, local=True)
    return JsonResponse({'ok': True})

@require_POST
@csrf_protect
def sign_out(request):
    logout(request)
    return JsonResponse({'ok': True})

def auth_start(request):
    if not all([settings.TELEGRAM_CLIENT_ID, settings.TELEGRAM_CLIENT_SECRET, settings.OWNER_TELEGRAM_ID]):
        return JsonResponse({'detail': 'Заполните настройки Telegram в .env'}, status=503)
    state, verifier, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    request.session['oidc'] = {'state': state, 'verifier': verifier, 'nonce': nonce, 'created_at': time.time()}
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    return redirect('https://oauth.telegram.org/auth?' + urlencode({'client_id': settings.TELEGRAM_CLIENT_ID,
        'redirect_uri': settings.TELEGRAM_REDIRECT_URI, 'response_type': 'code', 'scope': 'openid profile',
        'state': state, 'nonce': nonce, 'code_challenge': challenge, 'code_challenge_method': 'S256'}))

def auth_callback(request):
    flow = request.session.pop('oidc', None)
    if not flow or time.time()-flow.get('created_at', 0)>600 or not secrets.compare_digest(request.GET.get('state', ''), flow['state']) or not request.GET.get('code'):
        return redirect(settings.FRONTEND_URL + '/?auth_error=state')
    try:
        response = requests.post('https://oauth.telegram.org/token', timeout=20,
            auth=(settings.TELEGRAM_CLIENT_ID, settings.TELEGRAM_CLIENT_SECRET), data={
                'grant_type': 'authorization_code', 'code': request.GET['code'], 'redirect_uri': settings.TELEGRAM_REDIRECT_URI,
                'client_id': settings.TELEGRAM_CLIENT_ID, 'code_verifier': flow['verifier']})
        response.raise_for_status()
        token = response.json()['id_token']
        key = jwt.PyJWKClient('https://oauth.telegram.org/.well-known/jwks.json').get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=['RS256'], audience=settings.TELEGRAM_CLIENT_ID,
            issuer='https://oauth.telegram.org', options={'require': ['exp', 'iat', 'sub', 'iss', 'aud']})
        telegram_id = str(claims.get('id', ''))
        if claims.get('nonce') != flow['nonce'] or telegram_id != settings.OWNER_TELEGRAM_ID:
            return redirect(settings.FRONTEND_URL + '/?auth_error=access')
        establish(request, telegram_id=telegram_id)
    except (requests.RequestException, jwt.PyJWTError, KeyError, ValueError):
        return redirect(settings.FRONTEND_URL + '/?auth_error=token')
    return redirect(settings.FRONTEND_URL)
