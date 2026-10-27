import time
import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from ledger.models import Family, Member, Resource, ReminderDelivery

def send_digest():
    """At most one digest a day after 09:00 Minsk; no secrets or account data in messages."""
    now = timezone.localtime()
    if not settings.TELEGRAM_NOTIFICATION_TOKEN or not settings.OWNER_TELEGRAM_ID or now.hour < 9:
        return 'Notifications disabled or outside sending hours.'
    today = now.date()
    entries = []
    def append(label, end):
        days = (end - today).days
        if days <= 7:
            when = f'просрочено {abs(days)} дн.' if days < 0 else 'сегодня' if days == 0 else f'через {days} дн.'
            entries.append(f'• {label}: {when}')
    for family in Family.objects.filter(archived=False):
        append(f'Spotify · {family.name}', family.paid_until)
    for resource in Resource.objects.all():
        append(resource.name, resource.paid_until)
    for member in Member.objects.filter(active=True, is_free=False, family__archived=False).select_related('family'):
        append(f'Оплата Spotify · {member.name} ({member.family.name})', member.spotify_until or member.joined_on)
        if member.needs_vpn:
            append(f'Оплата VPN · {member.name}', member.vpn_until or member.joined_on)
    if not entries:
        return 'Nothing due.'
    # Lock is shared by worker instances. Failed API calls roll back the delivery marker.
    with transaction.atomic():
        delivery, _ = ReminderDelivery.objects.get_or_create(date=today)
        delivery = ReminderDelivery.objects.select_for_update().get(pk=delivery.pk)
        if delivery.sent_at:
            return 'Already sent today.'
        message = 'Круг · напоминания на ' + today.strftime('%d.%m.%Y') + '\n\n' + '\n'.join(entries)
        if len(message) > 3700:
            message = message[:3650] + '\n…Остальные события — в кабинете.'
        response = requests.post(f'https://api.telegram.org/bot{settings.TELEGRAM_NOTIFICATION_TOKEN}/sendMessage',
            json={'chat_id': settings.OWNER_TELEGRAM_ID, 'text': message, 'disable_web_page_preview': True}, timeout=20)
        # Do not include response URLs in exceptions: they contain the bot token.
        if response.status_code != 200 or not response.json().get('ok'):
            raise RuntimeError('Telegram rejected the reminder. Check the bot configuration and /start.')
        delivery.sent_at = timezone.now()
        delivery.save(update_fields=['sent_at'])
    return 'Digest sent.'

class Command(BaseCommand):
    help = 'Run reminder worker; --once sends at most one digest and exits.'
    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')
    def handle(self, *args, **options):
        while True:
            try:
                result = send_digest()
                if options['once']:
                    self.stdout.write(result)
            except Exception:
                # Never log a requests exception containing the token-bearing URL.
                self.stderr.write('Reminder delivery failed; will retry. No credentials logged.')
                if options['once']:
                    raise SystemExit(1)
            if options['once']:
                return
            time.sleep(60)
