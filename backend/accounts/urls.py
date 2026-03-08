from django.urls import path
from .views import (
    login_page, register_page, logout_page,
    customer_home, producer_home, admin_home
)
urlpatterns = [
    path("", login_page, name="login"),
    path("register/", register_page, name="register"),
    path("logout/", logout_page, name="logout"),

  
    path("customer/", customer_home, name="customer_home"),
    path("producer/", producer_home, name="producer_home"),
    path("admin-home/", admin_home, name="admin_home"),
]