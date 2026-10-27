from datetime import date, timedelta, datetime
from decimal import Decimal
from unittest.mock import patch, Mock
from django.conf import settings
from django.test import TestCase, Client, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient
from .models import *
from .services import add_payment, renew, convert, refresh_myfin
from .serializers import MemberSerializer
from .management.commands.send_reminders import send_digest

class LedgerTests(TestCase):
    def setUp(self):
        self.family = Family.objects.create(name='Test', paid_until=date(2027,1,15), cost=10, currency='USD')
        self.member = Member.objects.create(family=self.family, name='A',email='a@example.com',joined_on=date(2026,1,1),spotify_price=12,vpn_price=4,needs_vpn=True)
        ExchangeRate.objects.create(currency='USD',byn_per_unit=3)
        ExchangeRate.objects.create(currency='RUB',byn_per_unit='.035')
    def pay(self, **extra):
        return add_payment({'member':self.member,'service':'spotify','months':1,'amount':Decimal(12),'paid_on':date(2026,1,31)}|extra)
    def test_month_end_and_independent_family_expiry(self):
        payment=self.pay()
        self.assertEqual(payment.period_end,date(2026,2,28))
        self.family.refresh_from_db()
        self.assertEqual(self.family.paid_until,date(2027,1,15))
    def test_prepayment_extends_existing_period(self):
        self.member.spotify_until=date(2026,5,15);self.member.save()
        self.assertEqual(self.pay(months=3).period_end,date(2026,8,15))
    def test_expired_starts_from_payment_date(self):
        self.member.spotify_until=date(2026,1,5);self.member.save()
        self.assertEqual(self.pay().period_start,date(2026,1,31))
    def test_vpn_separate_from_spotify(self):
        self.pay(service='vpn')
        self.member.refresh_from_db()
        self.assertIsNone(self.member.spotify_until)
        self.assertEqual(self.member.vpn_until,date(2026,2,28))
    def test_free_participant_cannot_be_charged(self):
        self.member.is_free=True;self.member.save()
        with self.assertRaises(ValidationError): self.pay()
        self.assertEqual(Payment.objects.count(),0)
    def test_seventh_member_rejected(self):
        for i in range(5):Member.objects.create(family=self.family,name=str(i),email=f'{i}@example.com')
        serializer=MemberSerializer(data={'name':'Seventh','email':'s@example.com','family':self.family.pk})
        self.assertFalse(serializer.is_valid())
    def test_only_one_owner(self):
        self.member.is_owner=True;self.member.save()
        serializer=MemberSerializer(data={'name':'Other','email':'s@example.com','family':self.family.pk,'is_owner':True})
        self.assertFalse(serializer.is_valid())
    def test_secret_encrypted_and_absent_in_serializer(self):
        self.member.set_password('private-value');self.member.save()
        self.assertNotIn('private-value',self.member.password_cipher)
        self.assertEqual(self.member.get_password(),'private-value')
        self.assertNotIn('password_cipher',MemberSerializer(self.member).data)
        self.assertNotIn('password',MemberSerializer(self.member).data)
    def test_exchange_snapshot_does_not_change(self):
        payment=self.pay()
        ExchangeRate.objects.filter(currency='USD').update(byn_per_unit=6)
        self.assertEqual(convert(12,'BYN','USD',payment.rate_snapshot),Decimal(4))
        self.assertEqual(convert(12,'BYN','USD'),Decimal(2))
    def test_unknown_exchange_is_missing_not_zero(self):
        self.assertIsNone(convert(10,'USD','BYN',{'BYN':'1'}))
    def test_shared_vpn_expense_allocation_frozen(self):
        other=Family.objects.create(name='Other',paid_until=date(2027,1,1))
        Member.objects.create(family=other,name='B',email='b@example.com',needs_vpn=True)
        resource=Resource.objects.create(name='VPS',kind='vps',paid_until=date(2026,1,1))
        resource.families.set([self.family,other])
        expense=renew(resource,{'amount':Decimal(10),'currency':'USD','months':1,'paid_on':date(2026,1,1)})
        self.assertEqual(Decimal(expense.allocations[str(self.family.pk)]),Decimal('.5'))
        Member.objects.filter(family=other).update(needs_vpn=False)
        expense.refresh_from_db()
        self.assertEqual(Decimal(expense.allocations[str(self.family.pk)]),Decimal('.5'))
    @patch('ledger.services.requests.get')
    def test_myfin_rub_is_one_unit(self,get):
        get.return_value=Mock(text='<div id="nbrb_jsonVal">{"usd":"2.94","rub":"0.036"}</div>')
        refresh_myfin()
        self.assertEqual(ExchangeRate.objects.get(currency='RUB').byn_per_unit,Decimal('.036'))
    @patch('ledger.services.requests.get')
    def test_myfin_format_change_preserves_rates(self,get):
        get.return_value=Mock(text='<html>Changed</html>')
        with self.assertRaises(ValidationError):refresh_myfin()
        self.assertEqual(ExchangeRate.objects.get(currency='USD').byn_per_unit,Decimal(3))

class AccessTests(TestCase):
    def test_anonymous_cannot_access_any_records(self):
        c=APIClient()
        for endpoint in ['families','members','payments','resources','accounts','rates','expenses','overview']:
            self.assertIn(c.get('/api/'+endpoint+'/').status_code,[401,403])
    @override_settings(DEBUG=False,LOCAL_DEV_LOGIN=False)
    def test_production_has_no_local_login(self):
        c=Client()
        self.assertEqual(c.post('/api/auth/local/').status_code,403)
    @override_settings(DEBUG=True,LOCAL_DEV_LOGIN=True)
    def test_local_login_rejects_remote(self):
        self.assertEqual(Client().post('/api/auth/local/',REMOTE_ADDR='192.168.1.2').status_code,403)
    @override_settings(DEBUG=True,LOCAL_DEV_LOGIN=True)
    def test_csrf_required_for_local_login(self):
        self.assertEqual(Client(enforce_csrf_checks=True).post('/api/auth/local/').status_code,403)
    def test_bad_oidc_state_rejected(self):
        response=Client().get('/api/auth/callback/?code=fake&state=wrong')
        self.assertEqual(response.status_code,302)
        self.assertIn('auth_error=state',response.url)
    @override_settings(DEBUG=True,LOCAL_DEV_LOGIN=True)
    def test_move_requires_new_email_and_preserves_history(self):
        c=Client();c.post('/api/auth/local/')
        old=Family.objects.create(name='A',paid_until=date(2027,1,1));new=Family.objects.create(name='B',paid_until=date(2027,1,1))
        m=Member.objects.create(family=old,name='Test',email='old@example.com',spotify_until=date(2027,2,1))
        MembershipHistory.objects.create(member=m,family=old,email=m.email,started_on=date(2026,1,1))
        self.assertEqual(c.post(f'/api/members/{m.pk}/move/',{'family':new.pk,'email':m.email},content_type='application/json').status_code,400)
        response=c.post(f'/api/members/{m.pk}/move/',{'family':new.pk,'email':'new@example.com'},content_type='application/json')
        self.assertEqual(response.status_code,200)
        m.refresh_from_db();self.assertEqual(m.spotify_until,date(2027,2,1));self.assertEqual(m.history.count(),2)

class ReminderTests(TestCase):
    @override_settings(TELEGRAM_NOTIFICATION_TOKEN='fake',OWNER_TELEGRAM_ID='123')
    @patch('ledger.management.commands.send_reminders.requests.post')
    @patch('ledger.management.commands.send_reminders.timezone.localtime')
    def test_daily_digest_deduplicated(self,now,post):
        now.return_value=datetime(2026,10,27,12,0,tzinfo=timezone.get_current_timezone())
        Family.objects.create(name='Test',paid_until=date(2026,10,28))
        post.return_value=Mock(status_code=200,json=lambda:{'ok':True})
        send_digest();send_digest()
        self.assertEqual(post.call_count,1)
    @override_settings(TELEGRAM_NOTIFICATION_TOKEN='fake',OWNER_TELEGRAM_ID='123')
    @patch('ledger.management.commands.send_reminders.requests.post')
    @patch('ledger.management.commands.send_reminders.timezone.localtime')
    def test_failure_can_retry(self,now,post):
        now.return_value=datetime(2026,10,27,12,0,tzinfo=timezone.get_current_timezone())
        Family.objects.create(name='Test',paid_until=date(2026,10,28))
        post.return_value=Mock(status_code=400,json=lambda:{'ok':False})
        with self.assertRaises(RuntimeError):send_digest()
        self.assertFalse(ReminderDelivery.objects.exists())

@override_settings(DEBUG=True, LOCAL_DEV_LOGIN=True)
class WorkflowTests(TestCase):
    def setUp(self):
        self.client.post('/api/auth/local/')
        self.family = Family.objects.create(name='API family', paid_until=date(2026,10,31), cost=30, currency='BYN')
        self.member = Member.objects.create(family=self.family, name='API member', email='api@example.com', joined_on=date(2026,1,1), spotify_price=12)
    def test_payment_http_updates_member_not_family(self):
        response = self.client.post('/api/payments/', {'member':self.member.pk, 'service':'spotify','months':3,'amount':'36','paid_on':'2026-10-15'}, content_type='application/json')
        self.assertEqual(response.status_code,201,response.content)
        self.assertEqual(response.json()['period_end'],'2027-01-15')
        self.family.refresh_from_db()
        self.assertEqual(self.family.paid_until,date(2026,10,31))
    def test_renew_http_creates_expense(self):
        response=self.client.post(f'/api/families/{self.family.pk}/renew/',{'amount':'30','currency':'BYN','paid_on':'2026-10-20','months':1},content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(Expense.objects.count(),1)
    def test_unallocated_vpn_still_counts_in_global_profit(self):
        Resource.objects.create(name='Unused VPS',kind='vps',paid_until=date(2027,1,1),cost=10,currency='BYN')
        response=self.client.get('/api/overview/?currency=BYN')
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response.json()['totals']['cost'],'40.00')
        self.assertEqual(response.json()['totals']['profit'],'-28.00')
        self.assertEqual(response.json()['totals']['vpn_profit'],'-10.00')
    def test_archived_families_stay_in_cash_history(self):
        Payment.objects.create(member=self.member,family=self.family,service='spotify',months=1,amount=12,paid_on=date(2026,10,1),period_start=date(2026,10,1),period_end=date(2026,11,1),rate_snapshot={'BYN':'1'})
        self.family.archived=True;self.family.save()
        response=self.client.get('/api/overview/?currency=BYN')
        self.assertEqual(response.json()['cash'][0]['income'],'12.00')
