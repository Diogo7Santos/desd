from decimal import Decimal
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponseForbidden
from django.shortcuts import render

from accounts.models import User
from orders.models import Order
from payments.models import PaymentRecord, SettlementBatch


def admin_role_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if getattr(request.user, "role", None) != User.Role.ADMIN:
            return HttpResponseForbidden("Forbidden: admin only.")
        return view_func(request, *args, **kwargs)

    return _wrapped


@login_required
@admin_role_required
def dashboard(request):
    total_users = User.objects.count()
    total_producers = User.objects.filter(role=User.Role.PRODUCER).count()
    total_customers = User.objects.filter(role=User.Role.CUSTOMER).count()

    payment_totals = PaymentRecord.objects.aggregate(
        total_payment_value=Coalesce(Sum("gross_amount"), Decimal("0.00")),
        total_commission=Coalesce(Sum("commission_amount"), Decimal("0.00")),
    )
    pending_payments = PaymentRecord.objects.filter(status=PaymentRecord.Status.PENDING).count()
    failed_payments = PaymentRecord.objects.filter(status=PaymentRecord.Status.FAILED).count()

    context = {
        "total_users": total_users,
        "total_producers": total_producers,
        "total_customers": total_customers,
        "total_orders": Order.objects.count(),
        "total_payment_value": payment_totals["total_payment_value"],
        "total_commission": payment_totals["total_commission"],
        "pending_payments": pending_payments,
        "failed_payments": failed_payments,
        "settlement_count": SettlementBatch.objects.count(),
        "recent_orders": Order.objects.select_related("customer").order_by("-created_at")[:5],
        "recent_payment_records": PaymentRecord.objects.order_by("-created_at")[:5],
        "recent_settlement_batches": SettlementBatch.objects.order_by("-created_at")[:5],
    }
    return render(request, "admin_dashboard/dashboard.html", context)


@login_required
@admin_role_required
def orders_overview(request):
    orders = Order.objects.select_related("customer").order_by("-created_at")
    return render(request, "admin_dashboard/orders_overview.html", {"orders": orders})
