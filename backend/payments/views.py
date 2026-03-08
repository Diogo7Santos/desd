from decimal import Decimal
from uuid import uuid4

from django.db import transaction
from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import PaymentRecord, SettlementBatch, SettlementItem
from .serializers import (
    CommissionReportQuerySerializer,
    PaymentRecordSerializer,
    SettlementBatchSerializer,
    SettlementGenerationRequestSerializer,
    StripeCheckoutSessionCreateSerializer,
    commission_report_payload,
)
from .stripe_gateway import StripeGateway


def _to_minor_units(amount_major: Decimal) -> int:
    return int((amount_major * 100).to_integral_value())


class PaymentRecordListCreateAPIView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PaymentRecordSerializer

    def get_queryset(self):
        queryset = PaymentRecord.objects.all()
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

        record = PaymentRecord.objects.create(
            order_reference=payload["order_reference"],
            transaction_reference=f"TXN-{uuid4().hex[:16].upper()}",
            producer_reference=payload["producer_reference"],
            customer_reference=payload.get("customer_reference", ""),
            currency=payload["currency"],
            gross_amount=payload["gross_amount"],
            status=PaymentRecord.Status.PENDING,
            payment_provider="STRIPE_TEST",
        )

        try:
            gateway = StripeGateway()
            session = gateway.create_checkout_session(
                amount_minor_units=_to_minor_units(payload["gross_amount"]),
                currency=payload["currency"],
                success_url=payload["success_url"],
                cancel_url=payload["cancel_url"],
                transaction_reference=record.transaction_reference,
                payment_record_id=record.id,
                description=f"Order {record.order_reference}",
            )
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception:
            record.status = PaymentRecord.Status.FAILED
            record.save(update_fields=["status", "updated_at"])
            return Response(
                {"detail": "Unable to create Stripe checkout session."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        record.checkout_session_id = session.session_id
        record.checkout_session_url = session.checkout_url
        record.provider_payment_id = session.payment_intent_id or ""
        record.save(update_fields=["checkout_session_id", "checkout_session_url", "provider_payment_id"])

        return Response(
            {
                "payment_record_id": record.id,
                "transaction_reference": record.transaction_reference,
                "checkout_session_id": session.session_id,
                "checkout_url": session.checkout_url,
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
        obj = event.get("data", {}).get("object", {})

        if event_type in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
            record = self._find_record(obj)
            if record:
                record.status = PaymentRecord.Status.PAID
                record.paid_at = timezone.now()
                record.provider_payment_id = obj.get("payment_intent", "") or record.provider_payment_id
                record.save(update_fields=["status", "paid_at", "provider_payment_id", "updated_at"])
        elif event_type in ("checkout.session.expired", "checkout.session.async_payment_failed"):
            record = self._find_record(obj)
            if record:
                record.status = PaymentRecord.Status.FAILED
                record.save(update_fields=["status", "updated_at"])

        return Response({"received": True}, status=status.HTTP_200_OK)

    def _find_record(self, stripe_object):
        session_id = stripe_object.get("id", "")
        metadata = stripe_object.get("metadata", {}) or {}
        txn_reference = metadata.get("transaction_reference")
        if session_id:
            record = PaymentRecord.objects.filter(checkout_session_id=session_id).first()
            if record:
                return record
        if txn_reference:
            return PaymentRecord.objects.filter(transaction_reference=txn_reference).first()
        return None


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
    return render(request, "payments/dashboard.html", context)


def payment_records_page(request):
    records = PaymentRecord.objects.all()[:50]
    return render(request, "payments/payment_records.html", {"records": records})


def settlements_page(request):
    settlements = SettlementBatch.objects.prefetch_related("items__payment_record").all()[:30]
    return render(request, "payments/settlements.html", {"settlements": settlements})


def commission_report_page(request):
    today = timezone.now().date()
    month_start = today.replace(day=1)
    report = commission_report_payload(start_date=month_start, end_date=today)
    return render(request, "payments/commission_report.html", {"report": report})
