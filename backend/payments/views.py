from django.db import transaction
from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import PaymentRecord, ProcessedWebhookEvent, SettlementBatch, SettlementItem
from .services import create_checkout_session_for_order
from .serializers import (
    CommissionReportQuerySerializer,
    PaymentRecordSerializer,
    SettlementBatchSerializer,
    SettlementGenerationRequestSerializer,
    StripeCheckoutSessionCreateSerializer,
    commission_report_payload,
)
from .stripe_gateway import StripeGateway


class PaymentRecordListCreateAPIView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PaymentRecordSerializer

    def get_queryset(self):
        queryset = PaymentRecord.objects.all()
        user = self.request.user

        role = getattr(user, "role", "")
        if role == "CUSTOMER":
            queryset = queryset.filter(customer_reference=str(user.id))
        elif role == "PRODUCER":
            queryset = queryset.filter(producer_reference=str(user.id))

        producer_reference = self.request.query_params.get("producer_reference")
        status_filter = self.request.query_params.get("status")
        order_reference = self.request.query_params.get("order_reference")

        if producer_reference:
            queryset = queryset.filter(producer_reference=producer_reference)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if order_reference:
            queryset = queryset.filter(order_reference=order_reference)
        return queryset


class SettlementListAPIView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SettlementBatchSerializer

    def get_queryset(self):
        queryset = SettlementBatch.objects.prefetch_related("items__payment_record")
        if getattr(self.request.user, "role", "") == "PRODUCER":
            queryset = queryset.filter(producer_reference=str(self.request.user.id))
        producer_reference = self.request.query_params.get("producer_reference")
        if producer_reference:
            queryset = queryset.filter(producer_reference=producer_reference)
        return queryset


class SettlementGenerationAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SettlementGenerationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        week_start = serializer.validated_data["week_start"]
        week_end = serializer.validated_data["week_end"]

        paid_records = (
            PaymentRecord.objects.filter(
                status=PaymentRecord.Status.PAID,
                paid_at__date__gte=week_start,
                paid_at__date__lte=week_end,
                settlement_item__isnull=True,
            )
            .values("producer_reference")
            .annotate(
                gross=Sum("gross_amount"),
                commission=Sum("commission_amount"),
                net=Sum("net_amount"),
            )
        )

        created_batches = []
        with transaction.atomic():
            for producer_group in paid_records:
                settlement, created = SettlementBatch.objects.get_or_create(
                    producer_reference=producer_group["producer_reference"],
                    week_start=week_start,
                    week_end=week_end,
                    defaults={
                        "total_gross": producer_group["gross"] or 0,
                        "total_commission": producer_group["commission"] or 0,
                        "total_net": producer_group["net"] or 0,
                    },
                )

                if created:
                    producer_records = PaymentRecord.objects.filter(
                        status=PaymentRecord.Status.PAID,
                        paid_at__date__gte=week_start,
                        paid_at__date__lte=week_end,
                        producer_reference=producer_group["producer_reference"],
                        settlement_item__isnull=True,
                    )
                    for record in producer_records:
                        SettlementItem.objects.create(settlement=settlement, payment_record=record)
                    created_batches.append(settlement.id)

        return Response(
            {"created_settlement_ids": created_batches, "count": len(created_batches)},
            status=status.HTTP_201_CREATED,
        )


class CommissionReportAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        role = getattr(request.user, "role", "")
        if role == "CUSTOMER":
            return Response({"detail": "Customers cannot access commission reports."}, status=status.HTTP_403_FORBIDDEN)

        query_serializer = CommissionReportQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)

        report = commission_report_payload(
            start_date=query_serializer.validated_data["start_date"],
            end_date=query_serializer.validated_data["end_date"],
        )
        return Response(report, status=status.HTTP_200_OK)


class StripeCheckoutSessionCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = StripeCheckoutSessionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        try:
            checkout = create_checkout_session_for_order(
                order_reference=payload["order_reference"],
                success_url=payload["success_url"],
                cancel_url=payload["cancel_url"],
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception:
            return Response(
                {"detail": "Unable to create Stripe checkout session."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "order_reference": payload["order_reference"],
                "checkout_session_id": checkout["checkout_session_id"],
                "checkout_url": checkout["checkout_url"],
                "payment_record_ids": checkout["payment_record_ids"],
            },
            status=status.HTTP_201_CREATED,
        )


class StripeWebhookAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        signature = request.headers.get("Stripe-Signature")
        if not signature:
            return Response({"detail": "Missing Stripe-Signature header."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            gateway = StripeGateway()
            event = gateway.construct_webhook_event(request.body, signature)
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception:
            return Response({"detail": "Invalid Stripe webhook payload or signature."}, status=status.HTTP_400_BAD_REQUEST)

        event_type = event.get("type", "")
        event_id = event.get("id", "")
        obj = event.get("data", {}).get("object", {})
        if not event_id:
            return Response({"detail": "Missing webhook event id."}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            processed, created = ProcessedWebhookEvent.objects.get_or_create(
                event_id=event_id,
                defaults={"event_type": event_type},
            )
            if not created:
                return Response({"received": True, "duplicate": True}, status=status.HTTP_200_OK)

            if event_type in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
                self._apply_status_for_checkout_session(
                    checkout_session_id=obj.get("id", ""),
                    new_status=PaymentRecord.Status.PAID,
                    provider_payment_id=obj.get("payment_intent", ""),
                )
            elif event_type in ("checkout.session.expired", "checkout.session.async_payment_failed"):
                self._apply_status_for_checkout_session(
                    checkout_session_id=obj.get("id", ""),
                    new_status=PaymentRecord.Status.FAILED,
                    provider_payment_id=obj.get("payment_intent", ""),
                )

        return Response({"received": True}, status=status.HTTP_200_OK)

    def _apply_status_for_checkout_session(self, *, checkout_session_id: str, new_status: str, provider_payment_id: str):
        if not checkout_session_id:
            return

        with transaction.atomic():
            records = list(
                PaymentRecord.objects.select_for_update().filter(checkout_session_id=checkout_session_id)
            )
            if not records:
                return

            paid_at_value = timezone.now() if new_status == PaymentRecord.Status.PAID else None
            for record in records:
                record.status = new_status
                if paid_at_value:
                    record.paid_at = paid_at_value
                if provider_payment_id:
                    record.provider_payment_id = provider_payment_id
                fields = ["status", "updated_at"]
                if paid_at_value:
                    fields.append("paid_at")
                if provider_payment_id:
                    fields.append("provider_payment_id")
                record.save(update_fields=fields)

            if new_status == PaymentRecord.Status.PAID:
                from orders.models import Order

                order_refs = {r.order_reference for r in records}
                Order.objects.filter(order_number__in=order_refs).update(status=Order.Status.PENDING)


def payments_dashboard(request):
    context = {
        "record_count": PaymentRecord.objects.count(),
        "open_settlement_count": SettlementBatch.objects.filter(
            status=SettlementBatch.Status.OPEN
        ).count(),
        "paid_settlement_count": SettlementBatch.objects.filter(
            status=SettlementBatch.Status.PAID
        ).count(),
    }
    return render(request, "frontend/payments/dashboard.html", context)


def payment_records_page(request):
    records = PaymentRecord.objects.all()[:50]
    return render(request, "frontend/payments/payment_records.html", {"records": records})


def settlements_page(request):
    settlements = SettlementBatch.objects.prefetch_related("items__payment_record").all()[:30]
    return render(request, "frontend/payments/settlements.html", {"settlements": settlements})


def commission_report_page(request):
    today = timezone.now().date()
    month_start = today.replace(day=1)
    report = commission_report_payload(start_date=month_start, end_date=today)
    return render(request, "frontend/payments/commission_report.html", {"report": report})
