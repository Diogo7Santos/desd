from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("", lambda request: redirect("catalog:product_list")),
    path("admin/", admin.site.urls),

    # Django built-in login/logout/password URLs
    path("accounts/", include("django.contrib.auth.urls")),

    # Catalog
    path("catalog/", include("catalog.urls")),

    # Your accounts API
    path("api/accounts/", include("accounts.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)