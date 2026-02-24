from django.urls import path
from .views import RegisterCustomerView, RegisterProducerView, LoginView, MeView

urlpatterns = [
    path("register/producer/", RegisterProducerView.as_view()),
    path("register/customer/", RegisterCustomerView.as_view()),
    path("login/", LoginView.as_view()),
    path("me/", MeView.as_view()),
]