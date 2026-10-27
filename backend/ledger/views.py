from decimal import Decimal
import requests
from django.db import transaction
from django.db.models import ProtectedError
from django.utils import timezone
from rest_framework import viewsets, status, serializers
from rest_framework.decorators import action, api_view
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from .models import *
from .serializers import *
from .services import add_payment, renew, rates_snapshot, refresh_myfin, convert, adjust_paid_period

class AccountViewSet(viewsets.ModelViewSet):
    queryset = Account.objects.order_by('id')
    serializer_class = AccountSerializer

class RenewMixin:
    @action(detail=True, methods=['post'])
    def renew(self, request, pk=None):
        serializer = RenewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(ExpenseSerializer(renew(self.get_object(), serializer.validated_data)).data)

class FamilyViewSet(RenewMixin, viewsets.ModelViewSet):
    queryset = Family.objects.order_by('id')
    serializer_class = FamilySerializer
    def destroy(self, request, *args, **kwargs):
        return Response({'detail': 'Используйте архив: история оплат должна сохраняться.'}, status=405)

class VaultMixin:
    @action(detail=True, methods=['post'])
    def reveal(self, request, pk=None):
        obj = self.get_object()
        Audit.objects.create(event=f'Просмотр пароля {type(obj).__name__}', object_id=str(obj.pk))
        response = Response({'password': obj.get_password()})
        response['Cache-Control'] = 'no-store'
        return response

class MemberViewSet(VaultMixin, viewsets.ModelViewSet):
    queryset = Member.objects.select_related('family').prefetch_related('paid_period_adjustments').order_by('-active', '-is_owner', 'id')
    serializer_class = MemberSerializer
    @action(detail=True, methods=['post'], url_path='paid-period')
    def paid_period(self, request, pk=None):
        member = self.get_object()
        serializer = PaidPeriodInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(MemberSerializer(adjust_paid_period(member.pk, serializer.validated_data)).data)
    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        obj.active = False
        obj.save(update_fields=['active'])
        obj.history.filter(ended_on=None).update(ended_on=timezone.localdate())
        return Response(status=204)
    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        return Response(list(self.get_object().history.values('family__name', 'email', 'started_on', 'ended_on')))
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def move(self, request, pk=None):
        class MoveSerializer(serializers.Serializer):
            family = serializers.PrimaryKeyRelatedField(queryset=Family.objects.filter(archived=False))
            email = serializers.EmailField()
        serializer = MoveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        member = Member.objects.select_for_update().get(pk=pk)
        family = Family.objects.select_for_update().get(pk=serializer.validated_data['family'].pk)
        email = serializer.validated_data['email']
        if not member.active or family.pk == member.family_id or email.lower() == member.email.lower():
            raise ValidationError('Нужны активный участник, другая семья и новая почта.')
        if member.is_owner:
            raise ValidationError('Перед переносом снимите отметку владельца.')
        if family.members.filter(active=True).count() >= 6:
            raise ValidationError('В новой семье заняты все 6 мест.')
        member.history.filter(ended_on=None).update(ended_on=timezone.localdate())
        member.family, member.email = family, email
        member.set_password('')
        member.save()
        MembershipHistory.objects.create(member=member, family=family, email=email, started_on=timezone.localdate())
        Audit.objects.create(event='Перенос участника', object_id=str(member.pk))
        return Response(MemberSerializer(member).data)

class ResourceViewSet(VaultMixin, RenewMixin, viewsets.ModelViewSet):
    queryset = Resource.objects.order_by('id')
    serializer_class = ResourceSerializer
    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            raise ValidationError('У ресурса есть расходы в истории. Удаление недоступно.')

class PaymentViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Payment.objects.select_related('member', 'family').order_by('-paid_on', '-id')
    serializer_class = PaymentSerializer
    def create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = add_payment(serializer.validated_data)
        return Response(self.get_serializer(payment).data, status=status.HTTP_201_CREATED)

class ExpenseViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Expense.objects.select_related('family', 'resource').order_by('-paid_on', '-id')
    serializer_class = ExpenseSerializer

class RateViewSet(viewsets.ModelViewSet):
    queryset = ExchangeRate.objects.order_by('currency')
    serializer_class = RateSerializer
    http_method_names = ['get', 'post', 'patch', 'head', 'options']
    def perform_create(self, serializer):
        serializer.save(source='Вручную')
    def perform_update(self, serializer):
        serializer.save(source='Вручную')
    @action(detail=False, methods=['post'])
    def refresh(self, request):
        try:
            return Response(refresh_myfin())
        except requests.RequestException:
            raise ValidationError('Myfin недоступен. Сохранённые курсы не изменены.')

@api_view(['GET'])
def overview(request):
    today = timezone.localdate()
    target = request.GET.get('currency', 'BYN')
    if target not in dict(CURRENCIES):
        raise ValidationError('Неизвестная валюта.')
    rates = rates_snapshot()
    alerts, forecast = [], []
    resources = list(Resource.objects.prefetch_related('families').all())
    families = Family.objects.filter(archived=False).prefetch_related('members')
    def money(value):
        return str(value.quantize(Decimal('0.01'))) if value is not None else None
    def add_alert(kind, label, date, object_id, family_id=None):
        left = (date - today).days
        if left <= 7:
            alerts.append({'kind': kind, 'label': label, 'date': date, 'days': left, 'id': object_id, 'family_id': family_id})
    for family in families:
        members = [m for m in family.members.all() if m.active]
        income_spotify = sum((m.spotify_price for m in members if not m.is_free), Decimal(0))
        income_vpn = sum((m.vpn_price for m in members if m.needs_vpn and not m.is_free), Decimal(0))
        cost = convert(family.cost / family.cost_months, family.currency, target, rates)
        vpn_cost = Decimal(0)
        for resource in resources:
            ids = [f.pk for f in resource.families.all() if not f.archived]
            if family.pk not in ids:
                continue
            counts = {f: Member.objects.filter(family_id=f, active=True, needs_vpn=True).count() for f in ids}
            total = sum(counts.values())
            amount = convert(resource.cost / resource.cost_months, resource.currency, target, rates)
            if amount is None:
                vpn_cost = None
                break
            vpn_cost += amount * Decimal(counts[family.pk]) / total if total else Decimal(0)
        inc_s = convert(income_spotify, 'BYN', target, rates)
        inc_v = convert(income_vpn, 'BYN', target, rates)
        profit = inc_s + inc_v - cost - vpn_cost if all(v is not None for v in [inc_s, inc_v, cost, vpn_cost]) else None
        forecast.append({'id': family.pk, 'name': family.name, 'spotify_income': money(inc_s), 'vpn_income': money(inc_v), 'spotify_cost': money(cost), 'vpn_cost': money(vpn_cost), 'profit': money(profit)})
        add_alert('family', family.name, family.paid_until, family.pk)
        for member in members:
            if member.is_free:
                continue
            for service in ['spotify'] + (['vpn'] if member.needs_vpn else []):
                date = getattr(member, service + '_until') or member.joined_on
                add_alert(service, member.name, date, member.pk, family.pk)
    for resource in resources:
        add_alert('resource', resource.name, resource.paid_until, resource.pk)
    def sum_money(values):
        values = list(values)
        return sum(values, Decimal(0)) if all(v is not None for v in values) else None
    spotify_income = sum_money(convert(m.spotify_price, 'BYN', target, rates) for m in Member.objects.filter(active=True, is_free=False, family__archived=False))
    vpn_income = sum_money(convert(m.vpn_price, 'BYN', target, rates) for m in Member.objects.filter(active=True, is_free=False, needs_vpn=True, family__archived=False))
    spotify_cost = sum_money(convert(f.cost / f.cost_months, f.currency, target, rates) for f in families)
    # All VPS/proxy expenses count globally, even without a family allocation.
    vpn_cost_total = sum_money(convert(r.cost / r.cost_months, r.currency, target, rates) for r in resources)
    total_income, total_cost = sum_money([spotify_income, vpn_income]), sum_money([spotify_cost, vpn_cost_total])
    totals = {'income': money(total_income), 'cost': money(total_cost),
        'profit': money(total_income-total_cost) if total_income is not None and total_cost is not None else None,
        'vpn_income': money(vpn_income), 'vpn_cost': money(vpn_cost_total),
        'vpn_profit': money(vpn_income-vpn_cost_total) if vpn_income is not None and vpn_cost_total is not None else None}
    # Cash flow uses the exchange snapshot at the time of each entry.
    cash = []
    for family in Family.objects.all():
        income, costs = Decimal(0), Decimal(0)
        complete = True
        for payment in Payment.objects.filter(family=family):
            value = convert(payment.amount, 'BYN', target, payment.rate_snapshot)
            if value is None:
                complete = False
            else:
                income += value
        for expense in Expense.objects.all():
            share = Decimal(1) if expense.family_id == family.pk else Decimal(expense.allocations.get(str(family.pk), '0'))
            if not share:
                continue
            value = convert(expense.amount, expense.currency, target, expense.rate_snapshot)
            if value is None:
                complete = False
            else:
                costs += value * share
        cash.append({'id': family.pk, 'name': family.name, 'income': money(income) if complete else None,
            'cost': money(costs) if complete else None, 'balance': money(income-costs) if complete else None})
    return Response({'date': today, 'currency': target, 'alerts': sorted(alerts, key=lambda a: a['days']),
        'forecast': forecast, 'cash': cash, 'rates': rates, 'totals': totals,
        'unallocated_resources': [r.name for r in resources if not Member.objects.filter(family__in=r.families.all(), active=True, needs_vpn=True).exists()]})
