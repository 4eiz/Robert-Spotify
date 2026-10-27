from datetime import date
from unittest.mock import patch
from django.test import TestCase, Client, override_settings
from .models import Family, Member, Payment, Expense, PaidPeriodAdjustment

@override_settings(DEBUG=True, LOCAL_DEV_LOGIN=True, SECURE_SSL_REDIRECT=False)
class ExistingPaidPeriodTests(TestCase):
    def setUp(self):
        self.today_patch=patch('django.utils.timezone.localdate',return_value=date(2026,10,27))
        self.today_patch.start(); self.addCleanup(self.today_patch.stop)
        self.family=Family.objects.create(name='Imported family',started_on=date(2025,10,29),paid_until=date(2026,10,29))
        self.client.post('/api/auth/local/')
    def create_member(self, **extra):
        return self.client.post('/api/members/',{'family':self.family.pk,'name':'Existing member','email':'member@example.com','joined_on':'2025-10-29','spotify_price':'12',**extra},content_type='application/json')
    def adjust(self, member, **extra):
        return self.client.post(f'/api/members/{member.pk}/paid-period/',{'service':'spotify','paid_until':'2026-11-29','note':'Payment received before bookkeeping started',**extra},content_type='application/json')
    def test_import_preserves_join_date_and_creates_no_fake_income(self):
        response=self.create_member(spotify_until='2026-11-29')
        self.assertEqual(response.status_code,201,response.content)
        member=Member.objects.get(pk=response.json()['id'])
        self.assertEqual(member.joined_on,date(2025,10,29))
        self.assertEqual(member.spotify_until,date(2026,11,29))
        self.assertEqual(PaidPeriodAdjustment.objects.get(member=member).paid_until,date(2026,11,29))
        self.assertEqual(Payment.objects.count(),0)
        alerts=self.client.get('/api/overview/').json()['alerts']
        self.assertFalse(any(a['kind']=='spotify' and a['id']==member.pk for a in alerts))
    def test_early_payment_extends_existing_end_not_payment_date(self):
        member_id=self.create_member(spotify_until='2026-10-29').json()['id']
        response=self.client.post('/api/payments/',{'member':member_id,'service':'spotify','months':1,'amount':'12','paid_on':'2026-10-20'},content_type='application/json')
        self.assertEqual(response.status_code,201,response.content)
        self.assertEqual(response.json()['period_start'],'2026-10-29')
        self.assertEqual(response.json()['period_end'],'2026-11-29')
        self.family.refresh_from_db(); self.assertEqual(self.family.paid_until,date(2026,10,29))
    def test_adjustment_removes_debt_without_changing_cash_or_family(self):
        member=Member.objects.get(pk=self.create_member().json()['id'])
        response=self.adjust(member)
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response.json()['spotify_until'],'2026-11-29')
        self.assertEqual(Payment.objects.count(),0); self.assertEqual(Expense.objects.count(),0)
        self.assertEqual(self.client.get('/api/overview/').json()['cash'][0]['income'],'0.00')
        self.family.refresh_from_db(); self.assertEqual(self.family.paid_until,date(2026,10,29))
        record=PaidPeriodAdjustment.objects.get(member=member)
        self.assertIsNone(record.previous_until); self.assertTrue(record.note)
    def test_vpn_adjustment_is_independent(self):
        member=Member.objects.get(pk=self.create_member(needs_vpn=True,spotify_until='2026-11-29').json()['id'])
        self.assertEqual(self.adjust(member,service='vpn',paid_until='2026-12-05').status_code,200)
        member.refresh_from_db(); self.assertEqual(member.spotify_until,date(2026,11,29)); self.assertEqual(member.vpn_until,date(2026,12,5))
    def test_invalid_adjustments_rejected_without_writes(self):
        member=Member.objects.get(pk=self.create_member(spotify_until='2026-11-29').json()['id'])
        for extra in [{'note':'   '},{'paid_until':'2026-10-29'},{'paid_until':'2025-01-01'},{'service':'vpn'}]:
            with self.subTest(extra=extra): self.assertEqual(self.adjust(member,**extra).status_code,400)
        self.assertEqual(PaidPeriodAdjustment.objects.filter(member=member).count(),1)
    def test_invalid_import_date_and_unneeded_vpn_rejected(self):
        for extra in [{'spotify_until':'2025-01-01'},{'vpn_until':'2026-11-29'}]:
            with self.subTest(extra=extra): self.assertEqual(self.create_member(**extra).status_code,400)
        self.assertEqual(Member.objects.count(),0)
    def test_patch_cannot_bypass_adjustment_history(self):
        member_id=self.create_member().json()['id']
        response=self.client.patch(f'/api/members/{member_id}/',{'spotify_until':'2026-11-29'},content_type='application/json')
        self.assertEqual(response.status_code,400)
    def test_adjustment_requires_owner_and_csrf(self):
        member=Member.objects.get(pk=self.create_member().json()['id'])
        url=f'/api/members/{member.pk}/paid-period/'
        c=Client(enforce_csrf_checks=True)
        self.assertEqual(c.post(url,{},content_type='application/json').status_code,403)
        token=c.get('/api/auth/session/').json()['csrfToken']
        c.post('/api/auth/local/',HTTP_X_CSRFTOKEN=token)
        self.assertEqual(c.post(url,{},content_type='application/json').status_code,403)
