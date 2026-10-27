import time
from datetime import date
from unittest.mock import Mock, patch
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from django.db import IntegrityError, transaction
from django.test import TestCase, Client, override_settings
from ledger.models import Family, Member, Resource, Audit
from ledger.serializers import MemberSerializer

@override_settings(DEBUG=True, LOCAL_DEV_LOGIN=True)
class PrivateApiTests(TestCase):
    def setUp(self):
        self.family=Family.objects.create(name='Private',paid_until=date(2027,1,31))
        self.member=Member.objects.create(family=self.family,name='Owner',email='owner@example.com',is_owner=True)
        self.member.set_password('  correct secret  ')
        self.member.save()
    def test_password_requires_authentication(self):
        response=self.client.post(f'/api/members/{self.member.pk}/reveal/',{},content_type='application/json')
        self.assertEqual(response.status_code,403)
        self.assertNotIn('correct secret',response.content.decode())
    def test_authenticated_write_and_password_reveal_require_csrf(self):
        c=Client(enforce_csrf_checks=True)
        token=c.get('/api/auth/session/').json()['csrfToken']
        self.assertEqual(c.post('/api/auth/local/',HTTP_X_CSRFTOKEN=token).status_code,200)
        for path,body in [(f'/api/members/{self.member.pk}/reveal/',{}),('/api/families/',{'name':'Injected','paid_until':'2027-01-01'})]:
            self.assertEqual(c.post(path,body,content_type='application/json').status_code,403)
    def test_password_never_in_lists_and_is_audited_on_reveal(self):
        self.client.post('/api/auth/local/')
        response=self.client.get('/api/members/')
        self.assertNotIn('correct secret',response.content.decode())
        self.assertNotIn('password_cipher',response.content.decode())
        revealed=self.client.post(f'/api/members/{self.member.pk}/reveal/',{},content_type='application/json')
        self.assertEqual(revealed.json()['password'],'  correct secret  ')
        self.assertIn('no-store',revealed['Cache-Control'])
        self.assertEqual(Audit.objects.count(),1)
    def test_password_whitespace_preserved_on_write(self):
        serializer=MemberSerializer(self.member,data={'password':'  spaced  '},partial=True)
        self.assertTrue(serializer.is_valid(),serializer.errors)
        self.assertEqual(serializer.save().get_password(),'  spaced  ')
    def test_second_owner_rejected_by_api_and_database(self):
        self.client.post('/api/auth/local/')
        response=self.client.post('/api/members/',{'name':'Other','email':'other@example.com','family':self.family.pk,'is_owner':True},content_type='application/json')
        self.assertEqual(response.status_code,400)
        with self.assertRaises(IntegrityError),transaction.atomic():
            Member.objects.create(family=self.family,name='Other',email='other@example.com',is_owner=True)
    def test_renew_months_calculated_server_side(self):
        self.client.post('/api/auth/local/')
        response=self.client.post(f'/api/families/{self.family.pk}/renew/',{'months':1,'amount':'10','currency':'BYN','paid_on':'2026-10-27','paid_until':'2099-01-01'},content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response.json()['paid_until'],'2027-02-28')
    def test_invalid_month_counts_rejected(self):
        self.client.post('/api/auth/local/')
        for months in [0,-1,121,'wrong',1.5]:
            response=self.client.post(f'/api/families/{self.family.pk}/renew/',{'months':months,'amount':'10','currency':'BYN','paid_on':'2026-10-27'},content_type='application/json')
            self.assertEqual(response.status_code,400,response.content)
    def test_logout_revokes_session(self):
        self.client.post('/api/auth/local/')
        self.assertEqual(self.client.get('/api/members/').status_code,200)
        self.client.post('/api/auth/logout/')
        self.assertEqual(self.client.get('/api/members/').status_code,403)
    def test_no_cache_on_session_and_denied_records(self):
        for url in ['/api/auth/session/','/api/members/']:
            self.assertIn('no-store',self.client.get(url)['Cache-Control'])

@override_settings(LOCAL_DEV_LOGIN=False, OWNER_TELEGRAM_ID='123', TELEGRAM_CLIENT_ID='456', TELEGRAM_CLIENT_SECRET='test-only')
class SignedTelegramTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    def callback(self,claims=None,wrong_key=False,age=0):
        session=self.client.session
        session['oidc']={'state':'state-test','nonce':'nonce-test','verifier':'verifier-test','created_at':time.time()-age}
        session.save()
        payload={'sub':'oidc-subject-123','id':123,'iss':'https://oauth.telegram.org','aud':'456','iat':int(time.time()),'exp':int(time.time())+300,'nonce':'nonce-test'}|(claims or {})
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048) if wrong_key else self.private
        token=jwt.encode(payload,key,algorithm='RS256')
        with patch('ledger.auth.requests.post',return_value=Mock(json=lambda:{'id_token':token})),patch('ledger.auth.jwt.PyJWKClient') as jwks:
            jwks.return_value.get_signing_key_from_jwt.return_value=Mock(key=self.private.public_key())
            return self.client.get('/api/auth/callback/?code=test-code&state=state-test')
    def test_signed_owner_allowed(self):
        self.assertNotIn('auth_error',self.callback().url)
        self.assertEqual(self.client.get('/api/families/').status_code,200)
    def test_other_telegram_user_denied(self):
        self.assertIn('auth_error',self.callback({'id':999}).url)
        self.assertEqual(self.client.get('/api/families/').status_code,403)
    def test_invalid_signature_denied(self):
        self.assertIn('auth_error=token',self.callback(wrong_key=True).url)
    def test_invalid_claims_denied(self):
        for claims in [{'aud':'other'},{'iss':'https://attacker.example'},{'exp':int(time.time())-30},{'nonce':'wrong'},{'id':None}]:
            with self.subTest(claims=claims):
                self.assertIn('auth_error',self.callback(claims).url)
                self.assertEqual(self.client.get('/api/families/').status_code,403)
    def test_old_flow_denied(self):
        self.assertIn('auth_error=state',self.callback(age=601).url)
    def test_callback_cannot_be_replayed(self):
        self.callback()
        self.assertIn('auth_error=state',self.client.get('/api/auth/callback/?code=test-code&state=state-test').url)
