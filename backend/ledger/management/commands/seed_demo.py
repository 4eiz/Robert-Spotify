from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from ledger.models import *
from ledger.services import refresh_myfin, rates_snapshot

class Command(BaseCommand):
    help = 'Create fictional demo data only in an empty database. Never imports clipboard credentials.'
    @transaction.atomic
    def handle(self, *args, **options):
        if Family.objects.exists() or Member.objects.exists():
            raise CommandError('База не пустая. Демо-данные не добавлены.')
        today = timezone.localdate()
        account = Account.objects.create(name='ЕРИП · основной', number='ДЕМО — укажите свой счёт', instructions='Замените демонстрационные реквизиты перед работой.')
        colors = ['Каир', 'Александрия', 'Гиза', 'Асуан', 'Луксор']
        names = ['Роберт', 'Артём', 'Вера', 'Павел', 'Анна', 'Лиза', 'Михаил', 'Даша', 'Алексей', 'Настя', 'Илья', 'Ольга', 'Никита', 'Елена', 'Денис', 'Саша', 'Мария', 'Вадим', 'Юлия', 'Роман', 'Полина', 'Максим', 'Ирина', 'Егор']
        cursor = 0
        for i, name in enumerate(colors):
            family = Family.objects.create(name=f'Семья {name}', address=f'Демонстрационный адрес · {name}, Египет',
                paid_until=today+timedelta(days=[4,19,26,-2,12][i]), started_on=today-timedelta(days=90),
                cost='799' if i % 2 == 0 else '8.99', currency='RUB' if i % 2 == 0 else 'USD', account=account,
                notes='Демонстрационные данные — можно отредактировать или архивировать.')
            for j in range([5,6,4,5,4][i]):
                member = Member.objects.create(family=family,name=names[cursor],email=f'person{cursor+1}@example.com',
                    is_owner=j==0,is_free=j==0,needs_vpn=j%2==1,spotify_price='12',vpn_price='4',
                    joined_on=today-timedelta(days=60),spotify_until=today+timedelta(days=[20,-3,8,2,24,12][j]),
                    vpn_until=today+timedelta(days=10))
                MembershipHistory.objects.create(member=member, family=family, email=member.email, started_on=member.joined_on)
                cursor += 1
        for name, kind, cost, currency, days in [('VPS · Нидерланды','vps','5','USD',6),('RU-прокси · Москва','proxy','250','RUB',18)]:
            resource=Resource.objects.create(name=name,kind=kind,cost=cost,currency=currency,paid_until=today+timedelta(days=days),service_url='https://example.com',login='demo@example.com')
            resource.families.set(Family.objects.all())
        try:
            refresh_myfin()
        except Exception as exc:
            self.stdout.write(f'Курсы не загружены: {exc}')
        self.stdout.write(self.style.SUCCESS('Созданы 5 демонстрационных семей. Реальные данные из изображения не использовались.'))
