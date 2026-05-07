from django.urls import path

from .views import (
    admin_financial_report_csv,
    admin_financial_report_page,
    CommissionReportAPIView,
    PaymentRecordListCreateAPIView,
    SettlementGenerationAPIView,
    SettlementListAPIView,
    StripeCheckoutSessionCreateAPIView,
    StripeWebhookAPIView,
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
    path(
        "api/payments/stripe/checkout-session/",
        StripeCheckoutSessionCreateAPIView.as_view(),
        name="stripe-checkout-session",
    ),
    path(
        "api/payments/stripe/webhook/",
        StripeWebhookAPIView.as_view(),
        name="stripe-webhook",
    ),
    path("payments/", payments_dashboard, name="payments-dashboard"),
    path("payments/records/", payment_records_page, name="payments-records-page"),
    path("payments/settlements/", settlements_page, name="payments-settlements-page"),
    path("payments/reports/commission/", commission_report_page, name="payments-report-page"),
    path("payments/reports/network-commission/", admin_financial_report_page, name="admin-financial-report"),
    path("payments/reports/network-commission.csv", admin_financial_report_csv, name="admin-financial-report-csv"),
]
