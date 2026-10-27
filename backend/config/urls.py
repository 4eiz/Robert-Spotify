from django.urls import path, include
from rest_framework.routers import DefaultRouter
from ledger import views, auth
router = DefaultRouter()
for name, view in [('families', views.FamilyViewSet), ('members', views.MemberViewSet), ('resources', views.ResourceViewSet), ('accounts', views.AccountViewSet), ('payments', views.PaymentViewSet), ('expenses', views.ExpenseViewSet), ('rates', views.RateViewSet)]:
    router.register(name, view)
urlpatterns = [path('api/auth/session/', auth.session_info), path('api/auth/local/', auth.local_login),
    path('api/auth/logout/', auth.sign_out), path('api/auth/start/', auth.auth_start), path('api/auth/callback/', auth.auth_callback),
    path('api/overview/', views.overview), path('api/', include(router.urls))]
