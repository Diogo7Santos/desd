from django.contrib import admin
from django.urls import include, path
from django.urls import path, include
from django.shortcuts import redirect
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("", lambda request: redirect("catalog:product_list")),
    path("admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("catalog/", include("catalog.urls")),
    path("p/", include("payments.urls")),
    path("", include("accounts.urls")), # Web views for accounts (login, register, dashboards)
    path("api/accounts/", include("accounts.urls")), #DRF endpoints for accounts
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)