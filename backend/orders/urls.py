from django.urls import path
from . import views

app_name = 'orders'

urlpatterns = [
    path('checkout/', views.checkout, name='checkout'),
    path('place-order/', views.place_order, name='place_order'),
    path('confirmation/<int:order_id>/', views.order_confirmation, name='order_confirmation'),
    path('history/', views.order_history, name='order_history'),
    path('detail/<int:order_id>/', views.order_detail, name='order_detail'),
    path('reorder/<int:order_id>/', views.reorder, name='reorder'),
    path('producer/dashboard/', views.producer_dashboard, name='producer_dashboard'),
    path('producer/update-status/<int:order_id>/', views.update_order_status, name='update_status'),
]