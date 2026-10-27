"""Create a private local .env without printing secrets."""
from pathlib import Path
import secrets
from cryptography.fernet import Fernet
root = Path(__file__).resolve().parent.parent
path = root / '.env'
if not path.exists():
    path.write_text('DEBUG=1\nLOCAL_DEV_LOGIN=1\nDJANGO_SECRET_KEY=' + secrets.token_urlsafe(48) + '\nFIELD_ENCRYPTION_KEY=' + Fernet.generate_key().decode() + '\nALLOWED_HOSTS=localhost,127.0.0.1\nOWNER_TELEGRAM_ID=\nTELEGRAM_CLIENT_ID=\nTELEGRAM_CLIENT_SECRET=\nTELEGRAM_REDIRECT_URI=http://localhost:3000/api/auth/callback/\nFRONTEND_URL=http://localhost:3000\n', encoding='utf-8')
    print('Created private .env for loopback-only local development.')
else:
    print('Existing .env preserved.')
