from django.urls import path
from django.contrib import admin
from .views import (
    login_page, register_page, logout_page,
    customer_home, producer_home, admin_home,
    account_page,
)

urlpatterns = [
    path("", login_page, name="login"),
    path("register/", register_page, name="register"),
    path("logout/", logout_page, name="logout"),
    path("account/", account_page, name="account"),

    path("catalog/", customer_home, name="customer_home"),
    path("catalog/producer/products/", producer_home, name="producer_home"),
    path("admin/", admin_home, name="admin_home"),
]