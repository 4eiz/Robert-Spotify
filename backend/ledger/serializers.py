from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from .models import Account, Family, Member, MembershipHistory, PaidPeriodAdjustment, Resource, Payment, Expense, ExchangeRate

class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        fields = '__all__'

class FamilySerializer(serializers.ModelSerializer):
    days_left = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()
    class Meta:
        model = Family
        fields = '__all__'
    def get_days_left(self, obj):
        return (obj.paid_until - timezone.localdate()).days
    def get_member_count(self, obj):
        return obj.members.filter(active=True).count()
    def validate(self, attrs):
        if attrs.get('archived') and self.instance and self.instance.members.filter(active=True).exists():
            raise serializers.ValidationError('Сначала перенесите или архивируйте участников семьи.')
        return attrs

class PaidPeriodAdjustmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaidPeriodAdjustment
        fields = ['id', 'service', 'previous_until', 'paid_until', 'note', 'created_at']

class MemberSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=1000, trim_whitespace=False)
    has_password = serializers.SerializerMethodField()
    family_name = serializers.CharField(source='family.name', read_only=True)
    paid_period_adjustments = PaidPeriodAdjustmentSerializer(many=True, read_only=True)
    class Meta:
        model = Member
        exclude = ['password_cipher']
    def get_has_password(self, obj):
        return bool(obj.password_cipher)
    def validate(self, attrs):
        joined_on = attrs.get('joined_on', getattr(self.instance, 'joined_on', timezone.localdate()))
        for service in ['spotify', 'vpn']:
            field = service + '_until'
            if self.instance and field in attrs:
                raise serializers.ValidationError({field: 'Для изменения срока используйте «Учесть прежнюю оплату».'})
            until = attrs.get(field, getattr(self.instance, field, None))
            if until and until < joined_on:
                raise serializers.ValidationError({field: 'Оплаченный срок не может быть раньше даты присоединения.'})
        if attrs.get('vpn_until') and not attrs.get('needs_vpn', getattr(self.instance, 'needs_vpn', False)):
            raise serializers.ValidationError({'vpn_until': 'Сначала отметьте «Нужен VPN».'})
        family = attrs.get('family', getattr(self.instance, 'family', None))
        active = attrs.get('active', getattr(self.instance, 'active', True))
        if family.archived and active:
            raise serializers.ValidationError('Семья в архиве.')
        if active:
            others = family.members.filter(active=True)
            if self.instance:
                others = others.exclude(pk=self.instance.pk)
            if others.count() >= 6:
                raise serializers.ValidationError('В семье уже заняты все 6 мест.')
            if attrs.get('is_owner', getattr(self.instance, 'is_owner', False)) and others.filter(is_owner=True).exists():
                raise serializers.ValidationError('У семьи уже есть владелец.')
        if self.instance and family.pk != self.instance.family_id:
            raise serializers.ValidationError('Для переноса используйте отдельное действие с новой почтой.')
        return attrs
    @transaction.atomic
    def create(self, validated_data):
        password = validated_data.pop('password', '')
        validated_data['family'] = Family.objects.select_for_update().get(pk=validated_data['family'].pk)
        self.validate(validated_data)
        obj = super().create(validated_data)
        obj.set_password(password)
        obj.save(update_fields=['password_cipher'])
        MembershipHistory.objects.create(member=obj, family=obj.family, email=obj.email, started_on=obj.joined_on)
        for service in ['spotify', 'vpn']:
            until = getattr(obj, service + '_until')
            if until:
                PaidPeriodAdjustment.objects.create(member=obj, service=service, paid_until=until,
                    note='Уже оплаченный период при добавлении участника')
        return obj
    @transaction.atomic
    def update(self, instance, validated_data):
        instance = Member.objects.select_for_update().get(pk=instance.pk)
        self.instance = instance
        Family.objects.select_for_update().get(pk=instance.family_id)
        self.validate(validated_data)
        password = validated_data.pop('password', None)
        obj = super().update(instance, validated_data)
        if password is not None:
            obj.set_password(password)
            obj.save(update_fields=['password_cipher'])
        if not obj.active:
            obj.history.filter(ended_on=None).update(ended_on=timezone.localdate())
        return obj

class ResourceSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=1000, trim_whitespace=False)
    has_password = serializers.SerializerMethodField()
    days_left = serializers.SerializerMethodField()
    class Meta:
        model = Resource
        exclude = ['password_cipher']
    def get_has_password(self, obj):
        return bool(obj.password_cipher)
    def get_days_left(self, obj):
        return (obj.paid_until - timezone.localdate()).days
    def create(self, validated_data):
        password = validated_data.pop('password', '')
        obj = super().create(validated_data)
        obj.set_password(password)
        obj.save(update_fields=['password_cipher'])
        return obj
    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        obj = super().update(instance, validated_data)
        if password is not None:
            obj.set_password(password)
            obj.save(update_fields=['password_cipher'])
        return obj

class PaymentSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.name', read_only=True)
    family_name = serializers.CharField(source='family.name', read_only=True)
    class Meta:
        model = Payment
        fields = '__all__'
        read_only_fields = ['family', 'period_start', 'period_end', 'rate_snapshot', 'account_label', 'created_at']
    def validate_paid_on(self, value):
        if value > timezone.localdate():
            raise serializers.ValidationError('Дата поступления не может быть в будущем.')
        return value

class PaidPeriodInputSerializer(serializers.Serializer):
    service = serializers.ChoiceField(choices=['spotify', 'vpn'])
    paid_until = serializers.DateField()
    note = serializers.CharField(max_length=2000, allow_blank=False)

class RenewSerializer(serializers.Serializer):
    months = serializers.IntegerField(min_value=1, max_value=120)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    currency = serializers.ChoiceField(choices=['BYN', 'USD', 'RUB'])
    paid_on = serializers.DateField(default=timezone.localdate)
    note = serializers.CharField(required=False, allow_blank=True, max_length=5000)
    def validate_paid_on(self, value):
        if value > timezone.localdate():
            raise serializers.ValidationError('Дата расхода не может быть в будущем.')
        return value

class ExpenseSerializer(serializers.ModelSerializer):
    label = serializers.SerializerMethodField()
    class Meta:
        model = Expense
        fields = '__all__'
    def get_label(self, obj):
        return obj.family.name if obj.family else obj.resource.name

class RateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExchangeRate
        fields = '__all__'
        read_only_fields = ['updated_at', 'source']
