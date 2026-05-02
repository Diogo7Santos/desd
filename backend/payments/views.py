import logging
import csv
from collections import defaultdict
from datetime import timedelta
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum, Count
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseForbidden
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
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
)
from .stripe_gateway import StripeGateway

logger = logging.getLogger(__name__)


def admin_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated or getattr(request.user, "role", None) != "ADMIN":
            raise PermissionDenied("Admin access required.")
        return view_func(request, *args, **kwargs)

    return _wrapped


def _role(user) -> str:
    return getattr(user, "role", "")


def _is_admin(user) -> bool:
    return _role(user) == "ADMIN"


def _is_producer(user) -> bool:
    return _role(user) == "PRODUCER"


def _payments_access_allowed(user) -> bool:
    return _is_admin(user) or _is_producer(user)


def _payment_records_for_user(user):
    queryset = PaymentRecord.objects.all()
    if _is_producer(user):
        queryset = queryset.filter(producer_reference=str(user.id))
    return queryset


def _settlements_for_user(user):
    queryset = SettlementBatch.objects.prefetch_related("items__payment_record")
    if _is_producer(user):
        queryset = queryset.filter(producer_reference=str(user.id))
    return queryset


def _commission_report_for_user(user, start_date, end_date):
    records = PaymentRecord.objects.filter(
        paid_at__date__gte=start_date,
        paid_at__date__lte=end_date,
        status=PaymentRecord.Status.PAID,
    )
    if _is_producer(user):
        records = records.filter(producer_reference=str(user.id))

    totals = records.aggregate(
        gross=Sum("gross_amount"),
        commission=Sum("commission_amount"),
        net=Sum("net_amount"),
    )

    by_producer = (
        records.values("producer_reference")
        .annotate(
            gross=Sum("gross_amount"),
            commission=Sum("commission_amount"),
            net=Sum("net_amount"),
        )
        .order_by("producer_reference")
    )

    return {
        "start_date": start_date,
        "end_date": end_date,
        "totals": {
            "gross": totals["gross"] or 0,
            "commission": totals["commission"] or 0,
            "net": totals["net"] or 0,
        },
        "by_producer": by_producer,
    }


def _parse_date(value):
    if not value:
        return None
    try:
        return timezone.datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _resolve_date_range(params):
    today = timezone.now().date()
    range_mode = params.get("range", "current_month")
    start_date = None
    end_date = today

    if range_mode == "previous_2_weeks":
        start_date = today - timedelta(days=13)
    elif range_mode == "ytd":
        start_date = today.replace(month=1, day=1)
    elif range_mode == "custom":
        start_date = _parse_date(params.get("start_date"))
        custom_end = _parse_date(params.get("end_date"))
        end_date = custom_end or today
        if not start_date:
            start_date = today.replace(day=1)
    else:  # current_month default
        range_mode = "current_month"
        start_date = today.replace(day=1)

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    return range_mode, start_date, end_date


def _build_financial_report(params):
    from orders.models import Order, OrderItem

    range_mode, start_date, end_date = _resolve_date_range(params)
    producer_reference = (params.get("producer_reference") or "").strip()
    payment_status = (params.get("payment_status") or PaymentRecord.Status.PAID).strip()
    order_status = (params.get("order_status") or "").strip()

    records = PaymentRecord.objects.filter(
        paid_at__date__gte=start_date,
        paid_at__date__lte=end_date,
    ).order_by("-paid_at", "-created_at")
    if payment_status and payment_status != "ALL":
        records = records.filter(status=payment_status)
    if producer_reference:
        records = records.filter(producer_reference=producer_reference)

    order_numbers = list(records.values_list("order_reference", flat=True).distinct())
    orders = {
        o.order_number: o
        for o in Order.objects.filter(order_number__in=order_numbers)
    }

    if order_status:
        allowed_order_numbers = {
            o.order_number
            for o in orders.values()
            if o.status == order_status
        }
        records = records.filter(order_reference__in=allowed_order_numbers)
        order_numbers = list(records.values_list("order_reference", flat=True).distinct())
        orders = {k: v for k, v in orders.items() if k in allowed_order_numbers}

    producer_totals = (
        OrderItem.objects.filter(order__order_number__in=order_numbers)
        .values("order__order_number", "producer_id")
        .annotate(subtotal=Sum("subtotal"))
    )
    order_producer_shares = {
        (item["order__order_number"], str(item["producer_id"])): item["subtotal"]
        for item in producer_totals
    }
    order_producer_counts = defaultdict(int)
    for item in producer_totals:
        order_producer_counts[item["order__order_number"]] += 1

    report_rows = []
    totals = {"gross": 0, "commission": 0, "net": 0}
    order_refs = set()
    for record in records:
        order_refs.add(record.order_reference)
        order_obj = orders.get(record.order_reference)
        producer_share = order_producer_shares.get(
            (record.order_reference, record.producer_reference),
            record.gross_amount,
        )
        order_url = reverse("admin:orders_order_change", args=[order_obj.id]) if order_obj else ""
        payment_url = reverse("admin:payments_paymentrecord_change", args=[record.id])

        totals["gross"] += record.gross_amount
        totals["commission"] += record.commission_amount
        totals["net"] += record.net_amount

        report_rows.append(
            {
                "payment_id": record.id,
                "transaction_reference": record.transaction_reference,
                "order_reference": record.order_reference,
                "order_status": getattr(order_obj, "status", "UNKNOWN"),
                "producer_reference": record.producer_reference,
                "producer_share": producer_share,
                "gross_amount": record.gross_amount,
                "commission_amount": record.commission_amount,
                "net_amount": record.net_amount,
                "status": record.status,
                "paid_at": record.paid_at,
                "is_multi_vendor": order_producer_counts.get(record.order_reference, 0) > 1,
                "order_admin_url": order_url,
                "payment_admin_url": payment_url,
            }
        )

    ytd_start = timezone.now().date().replace(month=1, day=1)
    ytd_records = PaymentRecord.objects.filter(
        paid_at__date__gte=ytd_start,
        paid_at__date__lte=timezone.now().date(),
    )
    if payment_status and payment_status != "ALL":
        ytd_records = ytd_records.filter(status=payment_status)
    if producer_reference:
        ytd_records = ytd_records.filter(producer_reference=producer_reference)

    ytd_totals = ytd_records.aggregate(
        gross=Sum("gross_amount"),
        commission=Sum("commission_amount"),
        net=Sum("net_amount"),
    )

    monthly = (
        records.values("paid_at__year", "paid_at__month")
        .annotate(
            gross=Sum("gross_amount"),
            commission=Sum("commission_amount"),
            net=Sum("net_amount"),
            payments=Count("id"),
        )
        .order_by("paid_at__year", "paid_at__month")
    )
    monthly_rows = []
    for item in monthly:
        monthly_rows.append(
            {
                "month": f"{item['paid_at__year']}-{item['paid_at__month']:02d}",
                "gross": item["gross"] or 0,
                "commission": item["commission"] or 0,
                "net": item["net"] or 0,
                "payments": item["payments"] or 0,
            }
        )

    producer_breakdown = (
        records.values("producer_reference")
        .annotate(
            gross=Sum("gross_amount"),
            commission=Sum("commission_amount"),
            net=Sum("net_amount"),
            payments=Count("id"),
        )
        .order_by("producer_reference")
    )

    return {
        "range_mode": range_mode,
        "start_date": start_date,
        "end_date": end_date,
        "producer_reference": producer_reference,
        "payment_status": payment_status,
        "order_status": order_status,
        "totals": totals,
        "ytd_totals": {
            "gross": ytd_totals["gross"] or 0,
            "commission": ytd_totals["commission"] or 0,
            "net": ytd_totals["net"] or 0,
        },
        "processed_payment_count": len(report_rows),
        "processed_order_count": len(order_refs),
        "rows": report_rows,
        "producer_breakdown": producer_breakdown,
        "monthly_rows": monthly_rows,
    }


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
        if not _payments_access_allowed(request.user):
            return Response({"detail": "Customers cannot access commission reports."}, status=status.HTTP_403_FORBIDDEN)

        query_serializer = CommissionReportQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)

        report = _commission_report_for_user(
            user=request.user,
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
            logger.warning("Stripe webhook finalisation skipped: missing checkout_session_id.")
            return

        with transaction.atomic():
            records = list(
                PaymentRecord.objects.select_for_update().filter(checkout_session_id=checkout_session_id)
            )
            if not records:
                logger.warning(
                    "Stripe webhook finalisation skipped: no PaymentRecord found for checkout_session_id=%s",
                    checkout_session_id,
                )
                return

            had_non_paid_record = any(r.status != PaymentRecord.Status.PAID for r in records)
            paid_at_value = timezone.now() if new_status == PaymentRecord.Status.PAID else None
            for record in records:
                if new_status == PaymentRecord.Status.FAILED and record.status == PaymentRecord.Status.PAID:
                    logger.info(
                        "Ignoring FAILED status update for already-paid PaymentRecord id=%s (checkout_session_id=%s).",
                        record.id,
                        checkout_session_id,
                    )
                    continue
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

            if new_status == PaymentRecord.Status.PAID and had_non_paid_record:
                order_refs = {r.order_reference for r in records}
                self._finalise_paid_orders(order_refs=order_refs, checkout_session_id=checkout_session_id)
            elif new_status == PaymentRecord.Status.PAID:
                logger.info(
                    "Stripe webhook finalisation skipped: checkout_session_id=%s already finalised (all records were PAID).",
                    checkout_session_id,
                )

    def _finalise_paid_orders(self, *, order_refs: set[str], checkout_session_id: str) -> None:
        from cart.models import Cart
        from orders.models import Order
        from orders.models import OrderStatusHistory

        orders = list(
            Order.objects.select_for_update().filter(order_number__in=order_refs).prefetch_related("items__product")
        )
        if not orders:
            logger.warning(
                "Stripe webhook finalisation skipped: no Order found for checkout_session_id=%s and refs=%s",
                checkout_session_id,
                sorted(order_refs),
            )
            return

        for order in orders:
            for item in order.items.all():
                product = item.product
                product.stock_quantity -= item.quantity
                product.save(update_fields=["stock_quantity"])

            try:
                cart = Cart.objects.select_for_update().get(user=order.customer)
                cart.items.all().delete()
            except Cart.DoesNotExist:
                pass

            if order.status != Order.Status.PENDING:
                order.status = Order.Status.PENDING
                order.save(update_fields=["status", "updated_at"])

            OrderStatusHistory.objects.create(
                order=order,
                status=Order.Status.PENDING,
                changed_by=None,
                notes="Payment confirmed via Stripe webhook; stock decremented and cart cleared.",
            )


@login_required
def payments_dashboard(request):
    if not _payments_access_allowed(request.user):
        return HttpResponseForbidden("Customers cannot access payment pages.")

    records = _payment_records_for_user(request.user)
    settlements = _settlements_for_user(request.user)
    report = _commission_report_for_user(
        user=request.user,
        start_date=(timezone.now().date().replace(day=1)),
        end_date=timezone.now().date(),
    )
    context = {
        "record_count": records.count(),
        "open_settlement_count": settlements.filter(status=SettlementBatch.Status.OPEN).count(),
        "paid_settlement_count": settlements.filter(status=SettlementBatch.Status.PAID).count(),
        "total_commission": report["totals"]["commission"],
        "is_admin": _is_admin(request.user),
    }
    return render(request, "payments/dashboard.html", context)


@login_required
def payment_records_page(request):
    if not _payments_access_allowed(request.user):
        return HttpResponseForbidden("Customers cannot access payment pages.")

    records = _payment_records_for_user(request.user).order_by("-created_at")[:50]
    return render(request, "payments/payment_records.html", {"records": records})


@login_required
def settlements_page(request):
    if not _payments_access_allowed(request.user):
        return HttpResponseForbidden("Customers cannot access payment pages.")

    settlements = _settlements_for_user(request.user).order_by("-week_end", "-created_at")[:30]
    return render(request, "payments/settlements.html", {"settlements": settlements})


@login_required
def commission_report_page(request):
    if not _payments_access_allowed(request.user):
        return HttpResponseForbidden("Customers cannot access payment pages.")

    today = timezone.now().date()
    month_start = today.replace(day=1)
    report = _commission_report_for_user(user=request.user, start_date=month_start, end_date=today)
    return render(request, "payments/commission_report.html", {"report": report})


@admin_required
def admin_financial_report_page(request):
    report = _build_financial_report(request.GET)
    return render(request, "payments/admin_financial_report.html", {"report": report})


@admin_required
def admin_financial_report_csv(request):
    report = _build_financial_report(request.GET)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="network_commission_report.csv"'
    writer = csv.writer(response)

    writer.writerow(["FoodNet Network Commission Report"])
    writer.writerow(["Range", report["range_mode"]])
    writer.writerow(["Start Date", report["start_date"]])
    writer.writerow(["End Date", report["end_date"]])
    writer.writerow(["Total Gross", f"{report['totals']['gross']:.2f}"])
    writer.writerow(["Total Commission (5%)", f"{report['totals']['commission']:.2f}"])
    writer.writerow(["Total Producer Payout (95%)", f"{report['totals']['net']:.2f}"])
    writer.writerow(["Processed Payments", report["processed_payment_count"]])
    writer.writerow(["Processed Orders", report["processed_order_count"]])
    writer.writerow([])
    writer.writerow(
        [
            "Payment ID",
            "Transaction",
            "Order Ref",
            "Order Status",
            "Producer Ref",
            "Producer Share",
            "Gross",
            "Commission",
            "Payout",
            "Payment Status",
            "Paid At",
            "Multi Vendor",
        ]
    )
    for row in report["rows"]:
        writer.writerow(
            [
                row["payment_id"],
                row["transaction_reference"],
                row["order_reference"],
                row["order_status"],
                row["producer_reference"],
                f"{row['producer_share']:.2f}",
                f"{row['gross_amount']:.2f}",
                f"{row['commission_amount']:.2f}",
                f"{row['net_amount']:.2f}",
                row["status"],
                row["paid_at"].isoformat() if row["paid_at"] else "",
                "Yes" if row["is_multi_vendor"] else "No",
            ]
        )

    return response
