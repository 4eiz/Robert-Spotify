import json
import re
from decimal import Decimal
import requests
from bs4 import BeautifulSoup
from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from .models import ExchangeRate, Payment, Expense, Member, Family, Resource, Audit, PaidPeriodAdjustment

@transaction.atomic
def adjust_paid_period(member_id, data):
    member = Member.objects.select_for_update().select_related('family').get(pk=member_id)
    if not member.active or member.family.archived or member.is_free:
        raise ValidationError('Нужен активный участник с платным участием.')
    service = data['service']
    if service == 'vpn' and not member.needs_vpn:
        raise ValidationError('У участника не подключён VPN.')
    field = service + '_until'
    previous = getattr(member, field)
    until = data['paid_until']
    if until < member.joined_on:
        raise ValidationError('Оплаченный срок не может быть раньше даты присоединения.')
    if previous and until <= previous:
        raise ValidationError('Укажите дату позже текущего оплаченного срока.')
    PaidPeriodAdjustment.objects.create(member=member, service=service, previous_until=previous,
        paid_until=until, note=data['note'])
    setattr(member, field, until)
    member.save(update_fields=[field])
    Audit.objects.create(event='Учтена прежняя оплата ' + service, object_id=str(member.pk))
    return member

def rates_snapshot():
    return {r.currency: str(r.byn_per_unit) for r in ExchangeRate.objects.all()} | {'BYN': '1'}

def convert(amount, currency, target='BYN', rates=None):
    rates = rates if rates is not None else rates_snapshot()
    if currency == target:
        return Decimal(amount)
    if currency not in rates or target not in rates:
        return None
    return Decimal(amount) * Decimal(rates[currency]) / Decimal(rates[target])

def refresh_myfin():
    """Read the official NB RB converter rates published by Myfin. Never invent a fallback."""
    response = requests.get('https://myfin.by/converter', timeout=20, headers={'User-Agent': 'FamilyLedger/1.0'})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    node = soup.select_one('#nbrb_jsonVal')
    values = {}
    if node:
        try:
            parsed = json.loads(node.get_text())
            # Myfin normalizes all rates to one currency unit (RUB is not per 100).
            values = {code: Decimal(str(parsed[code.lower()])) for code in ('USD', 'RUB')}
        except (ValueError, KeyError, TypeError, ArithmeticError):
            values = {}
    if len(values) != 2:
        raise ValidationError('Myfin изменил формат данных. Сохранённые курсы не изменены. Можно задать курс вручную в настройках.')
    if not all(v.is_finite() for v in values.values()) or not (Decimal('0.01') < values['USD'] < 1000 and Decimal('0.00001') < values['RUB'] < 10):
        raise ValidationError('Myfin вернул некорректные курсы. Сохранённые курсы не изменены.')
    with transaction.atomic():
        for code, value in values.items():
            ExchangeRate.objects.update_or_create(currency=code, defaults={'byn_per_unit': value, 'source': 'Myfin / НБРБ'})
    return rates_snapshot()

@transaction.atomic
def add_payment(data):
    member = Member.objects.select_for_update().get(pk=data['member'].pk)
    if not member.active or member.family.archived:
        raise ValidationError('Участник неактивен.')
    if member.is_free:
        raise ValidationError('У участника бесплатное участие. Сначала измените его тариф.')
    service = data['service']
    if service == 'vpn' and not member.needs_vpn:
        raise ValidationError('У участника не подключён VPN.')
    field = service + '_until'
    old = getattr(member, field)
    paid_on = data.get('paid_on', timezone.localdate())
    # End is exclusive: a month paid on 15 October lasts up to 15 November.
    start = max(old or member.joined_on, paid_on, member.joined_on)
    end = start + relativedelta(months=data['months'])
    account = member.family.account
    payment = Payment.objects.create(**data, family=member.family, period_start=start, period_end=end,
        rate_snapshot=rates_snapshot(), account_label=f'{account.name}: {account.number}' if account else '')
    setattr(member, field, end)
    member.save(update_fields=[field])
    Audit.objects.create(event='Добавлена оплата', object_id=str(payment.pk))
    return payment

@transaction.atomic
def renew(obj, data):
    data = dict(data)
    model = Family if isinstance(obj, Family) else Resource
    obj = model.objects.select_for_update().get(pk=obj.pk)
    months = data.pop('months')
    if not isinstance(months, int) or isinstance(months, bool) or not 1 <= months <= 120:
        raise ValidationError('Укажите от 1 до 120 месяцев.')
    end = max(obj.paid_until, data.get('paid_on', timezone.localdate())) + relativedelta(months=months)
    data['paid_until'] = end
    allocations = {}
    if isinstance(obj, Resource):
        families = list(obj.families.all())
        counts = {str(f.pk): f.members.filter(active=True, needs_vpn=True).count() for f in families}
        total = sum(counts.values())
        allocations = {k: str(Decimal(v) / total) for k, v in counts.items()} if total else {}
    expense = Expense.objects.create(family=obj if isinstance(obj, Family) else None,
        resource=obj if isinstance(obj, Resource) else None, allocations=allocations,
        rate_snapshot=rates_snapshot(), **data)
    obj.paid_until = end
    obj.save(update_fields=['paid_until'])
    Audit.objects.create(event='Продление подписки', object_id=f'{model.__name__}:{obj.pk}')
    return expense
