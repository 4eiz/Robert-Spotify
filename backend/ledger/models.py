from decimal import Decimal
from cryptography.fernet import Fernet
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone

CURRENCIES = [('BYN', 'BYN'), ('USD', 'USD'), ('RUB', 'RUB')]

class Vault(models.Model):
    password_cipher = models.TextField(blank=True)

    class Meta:
        abstract = True

    def set_password(self, value):
        self.password_cipher = Fernet(settings.FIELD_ENCRYPTION_KEY.encode()).encrypt(value.encode()).decode() if value else ''

    def get_password(self):
        return Fernet(settings.FIELD_ENCRYPTION_KEY.encode()).decrypt(self.password_cipher.encode()).decode() if self.password_cipher else ''

class Account(models.Model):
    name = models.CharField(max_length=120)
    number = models.CharField(max_length=200)
    instructions = models.TextField(blank=True)

class Family(models.Model):
    name = models.CharField(max_length=120)
    address = models.TextField(blank=True)
    invite_url = models.URLField(max_length=1000, blank=True)
    started_on = models.DateField(default=timezone.localdate)
    paid_until = models.DateField()
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    currency = models.CharField(max_length=3, choices=CURRENCIES, default='USD')
    cost_months = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(120)])
    account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL)
    notes = models.TextField(blank=True)
    archived = models.BooleanField(default=False)

class Member(Vault):
    family = models.ForeignKey(Family, on_delete=models.PROTECT, related_name='members')
    name = models.CharField(max_length=120)
    email = models.EmailField()
    contact = models.CharField(max_length=150, blank=True)
    is_owner = models.BooleanField(default=False)
    is_free = models.BooleanField(default=False)
    needs_vpn = models.BooleanField(default=False)
    joined_on = models.DateField(default=timezone.localdate)
    spotify_until = models.DateField(null=True, blank=True)
    vpn_until = models.DateField(null=True, blank=True)
    spotify_price = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    vpn_price = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    notes = models.TextField(blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['family'], condition=models.Q(is_owner=True, active=True), name='one_active_owner')]

class MembershipHistory(models.Model):
    member = models.ForeignKey(Member, on_delete=models.PROTECT, related_name='history')
    family = models.ForeignKey(Family, on_delete=models.PROTECT)
    email = models.EmailField()
    started_on = models.DateField()
    ended_on = models.DateField(null=True)

class PaidPeriodAdjustment(models.Model):
    member = models.ForeignKey(Member, on_delete=models.PROTECT, related_name='paid_period_adjustments')
    service = models.CharField(max_length=10, choices=[('spotify', 'Spotify'), ('vpn', 'VPN')])
    previous_until = models.DateField(null=True)
    paid_until = models.DateField()
    note = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

class Resource(Vault):
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=10, choices=[('vps', 'VPS'), ('proxy', 'RU-прокси')])
    service_url = models.URLField(blank=True)
    login = models.CharField(max_length=200, blank=True)
    paid_until = models.DateField()
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    currency = models.CharField(max_length=3, choices=CURRENCIES, default='USD')
    cost_months = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(120)])
    families = models.ManyToManyField(Family, blank=True, related_name='resources')
    notes = models.TextField(blank=True)

class ExchangeRate(models.Model):
    currency = models.CharField(max_length=3, choices=CURRENCIES, unique=True)
    byn_per_unit = models.DecimalField(max_digits=18, decimal_places=8, validators=[MinValueValidator(Decimal('0.00000001'))])
    source = models.CharField(max_length=100, default='Myfin / НБРБ')
    updated_at = models.DateTimeField(auto_now=True)

class Payment(models.Model):
    member = models.ForeignKey(Member, on_delete=models.PROTECT, related_name='payments')
    family = models.ForeignKey(Family, on_delete=models.PROTECT)
    service = models.CharField(max_length=10, choices=[('spotify', 'Spotify'), ('vpn', 'VPN')])
    months = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(120)])
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    paid_on = models.DateField(default=timezone.localdate)
    period_start = models.DateField()
    period_end = models.DateField()
    rate_snapshot = models.JSONField(default=dict)
    account_label = models.CharField(max_length=350, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class Expense(models.Model):
    family = models.ForeignKey(Family, null=True, blank=True, on_delete=models.PROTECT)
    resource = models.ForeignKey(Resource, null=True, blank=True, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    currency = models.CharField(max_length=3, choices=CURRENCIES)
    paid_on = models.DateField(default=timezone.localdate)
    paid_until = models.DateField()
    rate_snapshot = models.JSONField(default=dict)
    allocations = models.JSONField(default=dict)
    note = models.TextField(blank=True)

class Audit(models.Model):
    occurred_at = models.DateTimeField(auto_now_add=True)
    event = models.CharField(max_length=200)
    object_id = models.CharField(max_length=100, blank=True)

class ReminderDelivery(models.Model):
    date = models.DateField(unique=True)
    sent_at = models.DateTimeField(null=True)
