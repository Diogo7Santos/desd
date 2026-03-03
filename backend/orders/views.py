from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Order, ProducerOrder, OrderItem, OrderStatusHistory
from .serializers import OrderSerializer, ProducerOrderSerializer, OrderItemSerializer, OrderStatusHistorySerializer

class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.all()
    serializer_class = OrderSerializer
    
    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        """Update order status and log to history"""
        order = self.get_object()
        new_status = request.data.get('status')
        changed_by = request.user if request.user.is_authenticated else None
        
        # Create status history entry
        OrderStatusHistory.objects.create(
            order=order,
            previous_status=order.order_status,
            new_status=new_status,
            changed_by=changed_by
        )
        
        # Update order status
        order.order_status = new_status
        order.save()
        
        serializer = self.get_serializer(order)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def by_customer(self, request):
        """Get all orders for a specific customer"""
        customer_id = request.query_params.get('customer_id')
        if not customer_id:
            return Response({'error': 'customer_id required'}, status=status.HTTP_400_BAD_REQUEST)
        
        orders = Order.objects.filter(customer_id=customer_id)
        serializer = self.get_serializer(orders, many=True)
        return Response(serializer.data)

class ProducerOrderViewSet(viewsets.ModelViewSet):
    queryset = ProducerOrder.objects.all()
    serializer_class = ProducerOrderSerializer
    
    @action(detail=False, methods=['get'])
    def by_producer(self, request):
        """Get all orders for a specific producer"""
        producer_id = request.query_params.get('producer_id')
        if not producer_id:
            return Response({'error': 'producer_id required'}, status=status.HTTP_400_BAD_REQUEST)
        
        producer_orders = ProducerOrder.objects.filter(producer_id=producer_id)
        serializer = self.get_serializer(producer_orders, many=True)
        return Response(serializer.data)

class OrderItemViewSet(viewsets.ModelViewSet):
    queryset = OrderItem.objects.all()
    serializer_class = OrderItemSerializer

class OrderStatusHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = OrderStatusHistory.objects.all()
    serializer_class = OrderStatusHistorySerializer