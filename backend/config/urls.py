from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("p/", include("payments.urls")),
    path("", include("accounts.urls")), # Web views for accounts (login, register, dashboards)
    path("api/accounts/", include("accounts.urls")), #DRF endpoints for accounts

]
