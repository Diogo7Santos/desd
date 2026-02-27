from django.urls import path

from .views import (
    CommissionReportAPIView,
    PaymentRecordListCreateAPIView,
    SettlementGenerationAPIView,
    SettlementListAPIView,
    commission_report_page,
    payment_records_page,
    payments_dashboard,
    settlements_page,
)

urlpatterns = [
    path("api/payments/records/", PaymentRecordListCreateAPIView.as_view(), name="payment-records"),
    path("api/payments/settlements/", SettlementListAPIView.as_view(), name="settlement-list"),
    path(
        "api/payments/settlements/generate/",
        SettlementGenerationAPIView.as_view(),
        name="settlement-generate",
    ),
    path(
        "api/payments/reports/commission/",
        CommissionReportAPIView.as_view(),
        name="commission-report",
    ),
    path("payments/", payments_dashboard, name="payments-dashboard"),
    path("payments/records/", payment_records_page, name="payments-records-page"),
    path("payments/settlements/", settlements_page, name="payments-settlements-page"),
    path("payments/reports/commission/", commission_report_page, name="payments-report-page"),
]
