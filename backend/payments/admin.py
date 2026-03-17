from django.contrib import admin

from .models import PaymentRecord, ProcessedWebhookEvent, SettlementBatch, SettlementItem


@admin.register(PaymentRecord)
class PaymentRecordAdmin(admin.ModelAdmin):
    list_display = (
        "transaction_reference",
        "payment_provider",
        "order_reference",
        "producer_reference",
        "gross_amount",
        "commission_amount",
        "net_amount",
        "status",
        "paid_at",
    )
    list_filter = ("status", "currency")
    search_fields = (
        "transaction_reference",
        "order_reference",
        "producer_reference",
        "checkout_session_id",
        "provider_payment_id",
    )
    readonly_fields = ("commission_amount", "net_amount", "created_at", "updated_at")


@admin.register(SettlementBatch)
class SettlementBatchAdmin(admin.ModelAdmin):
    list_display = (
        "producer_reference",
        "week_start",
        "week_end",
        "total_gross",
        "total_commission",
        "total_net",
        "status",
    )
    list_filter = ("status",)
    search_fields = ("producer_reference",)


@admin.register(SettlementItem)
class SettlementItemAdmin(admin.ModelAdmin):
    list_display = ("id", "settlement", "payment_record", "created_at")
    search_fields = ("settlement__producer_reference", "payment_record__transaction_reference")


@admin.register(ProcessedWebhookEvent)
class ProcessedWebhookEventAdmin(admin.ModelAdmin):
    list_display = ("event_id", "event_type", "processed_at")
    search_fields = ("event_id", "event_type")
