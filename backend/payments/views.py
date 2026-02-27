from django.db import transaction
from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import PaymentRecord, SettlementBatch, SettlementItem
from .serializers import (
    CommissionReportQuerySerializer,
    PaymentRecordSerializer,
    SettlementBatchSerializer,
    SettlementGenerationRequestSerializer,
    commission_report_payload,
)


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
