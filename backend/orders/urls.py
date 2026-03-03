from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import OrderViewSet, ProducerOrderViewSet, OrderItemViewSet, OrderStatusHistoryViewSet

router = DefaultRouter()
router.register(r'orders', OrderViewSet, basename='order')
router.register(r'producer-orders', ProducerOrderViewSet, basename='producerorder')
router.register(r'order-items', OrderItemViewSet, basename='orderitem')
router.register(r'order-history', OrderStatusHistoryViewSet, basename='orderhistory')

urlpatterns = [
    path('', include(router.urls)),
]