
from datetime import timedelta
from decimal import Decimal

from django.contrib import admin, messages
from django.db import transaction
from django.utils import timezone

from .models import (
    SHARE_PRICE,
    Package,
    BiddingSession,
    SharePool,
    ShareBatch,
    PurchaseRequest,
    Holding,
    SellerListing,
    Allocation,
    PaymentEvidence,
    AuditLog,
)


@admin.register(PurchaseRequest)
class PurchaseRequestAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "buyer",
        "batch",
        "shares_requested",
        "amount",
        "package",
        "status",
        "created_at",
    )

    list_filter = ("status", "package", "batch")
    search_fields = ("buyer__username", "reference")
    readonly_fields = ("reference", "created_at")

    actions = ["accept_requests", "reject_requests"]

    @admin.action(description="Accept selected requests and create holdings")
    def accept_requests(self, request, queryset):
        accepted = 0
        skipped = 0

        for selected in queryset:
            with transaction.atomic():
                item = (
                    PurchaseRequest.objects
                    .select_for_update()
                    .select_related("buyer", "package", "batch")
                    .get(pk=selected.pk)
                )

                if item.status != "submitted":
                    skipped += 1
                    continue

                if (
                    not item.batch_id
                    or not item.package_id
                    or item.shares_requested <= 0
                    or item.amount <= 0
                ):
                    skipped += 1
                    continue

                if Holding.objects.filter(purchase=item).exists():
                    skipped += 1
                    continue

                now = timezone.now()
                maturity = now + timedelta(days=item.package.days)

                maturity_value = item.amount * (
                    Decimal("1.00") + item.package.rate
                )

                holding = Holding.objects.create(
                    owner=item.buyer,
                    purchase=item,
                    shares=item.shares_requested,
                    share_price_snapshot=item.share_price_snapshot,
                    principal=item.amount,
                    rate_snapshot=item.package.rate,
                    days_snapshot=item.package.days,
                    activated_at=now,
                    maturity_at=maturity,
                    maturity_value=maturity_value,
                    status="active",
                )

                item.status = "accepted"
                item.save(update_fields=["status"])

                AuditLog.objects.create(
                    actor=request.user,
                    action="Accepted purchase and activated holding",
                    object_type="Holding",
                    object_id=str(holding.pk),
                    reason=(
                        f"Accepted {item.shares_requested} shares "
                        f"from batch {item.batch.title}."
                    ),
                )

                accepted += 1

        self.message_user(
            request,
            f"{accepted} request(s) accepted. {skipped} skipped.",
            messages.SUCCESS if accepted else messages.WARNING,
        )

    @admin.action(description="Reject selected requests and return reserved shares")
    def reject_requests(self, request, queryset):
        rejected = 0
        skipped = 0

        for selected in queryset:
            with transaction.atomic():
                item = (
                    PurchaseRequest.objects
                    .select_for_update()
                    .select_related("batch")
                    .get(pk=selected.pk)
                )

                if item.status != "submitted" or not item.batch_id:
                    skipped += 1
                    continue

                batch = (
                    ShareBatch.objects
                    .select_for_update()
                    .get(pk=item.batch_id)
                )

                if batch.status != "released":
                    skipped += 1
                    continue

                batch.available_shares = min(
                    batch.total_shares,
                    batch.available_shares + item.shares_requested,
                )
                batch.save(update_fields=["available_shares"])

                item.status = "rejected"
                item.save(update_fields=["status"])

                AuditLog.objects.create(
                    actor=request.user,
                    action="Purchase request rejected",
                    object_type="PurchaseRequest",
                    object_id=str(item.pk),
                    reason=(
                        f"Rejected request for {item.shares_requested} "
                        f"shares. Shares returned to batch {batch.title}."
                    ),
                )

                rejected += 1

        self.message_user(
            request,
            f"{rejected} request(s) rejected and shares returned. "
            f"{skipped} skipped.",
            messages.SUCCESS if rejected else messages.WARNING,
        )


@admin.register(Holding)
class HoldingAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "owner",
        "shares",
        "principal",
        "maturity_value",
        "maturity_at",
        "status",
    )

    list_filter = ("status",)
    search_fields = ("owner__username", "reference")
    readonly_fields = ("reference",)

    actions = ["process_maturities"]

    @admin.action(
        description="Process matured holdings and create seller listings"
    )
    def process_maturities(self, request, queryset):
        count = 0
        skipped = 0

        for selected in queryset:
            with transaction.atomic():
                holding = (
                    Holding.objects
                    .select_for_update()
                    .select_related("owner")
                    .get(pk=selected.pk)
                )

                if (
                    holding.status != "active"
                    or holding.maturity_at > timezone.now()
                    or holding.shares <= 0
                ):
                    skipped += 1
                    continue

                listing, created = SellerListing.objects.get_or_create(
                    holding=holding,
                    defaults={
                        "seller": holding.owner,
                        "total_shares": holding.shares,
                        "allocated_shares": 0,
                        "received_shares": 0,
                        "total_amount": (
                            Decimal(holding.shares) * SHARE_PRICE
                        ),
                        "allocated_amount": Decimal("0.00"),
                        "received_amount": Decimal("0.00"),
                        "status": "available",
                    },
                )

                if not created:
                    skipped += 1
                    continue

                holding.status = "listed"
                holding.save(update_fields=["status"])

                AuditLog.objects.create(
                    actor=request.user,
                    action="Matured holding listed on marketplace",
                    object_type="SellerListing",
                    object_id=str(listing.pk),
                    reason=(
                        f"Listed {holding.shares} shares belonging "
                        f"to {holding.owner.username}."
                    ),
                )

                count += 1

        self.message_user(
            request,
            f"{count} matured holding(s) listed. {skipped} skipped.",
            messages.SUCCESS if count else messages.WARNING,
        )


@admin.register(SellerListing)
class SellerListingAdmin(admin.ModelAdmin):
    list_display = (
        "holding",
        "seller",
        "total_shares",
        "allocated_shares",
        "remaining_shares",
        "total_amount",
        "status",
        "created_at",
    )

    list_filter = ("status",)
    search_fields = ("seller__username", "holding__reference")

    readonly_fields = (
        "holding",
        "seller",
        "total_shares",
        "allocated_shares",
        "received_shares",
        "total_amount",
        "allocated_amount",
        "received_amount",
        "created_at",
    )


@admin.register(Allocation)
class AllocationAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "listing",
        "buyer",
        "seller",
        "shares",
        "amount",
        "package",
        "status",
        "created_at",
    )

    list_filter = ("status", "package")
    search_fields = (
        "buyer__username",
        "seller__username",
        "reference",
    )

    readonly_fields = (
        "reference",
        "listing",
        "buyer",
        "seller",
        "shares",
        "share_price_snapshot",
        "amount",
        "package",
        "status",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ShareBatch)
class ShareBatchAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "total_shares",
        "available_shares",
        "share_price",
        "status",
        "created_at",
        "released_at",
    )

    list_filter = ("status", "created_at")
    search_fields = ("title", "reference")

    readonly_fields = (
        "reference",
        "share_price",
        "available_shares",
        "released_at",
        "released_by",
        "created_at",
    )

    actions = ["release_selected_batches"]

    @admin.action(description="Release selected share batches")
    def release_selected_batches(self, request, queryset):
        released = 0

        with transaction.atomic():
            batches = queryset.select_for_update()

            for batch in batches:
                if batch.status != "draft" or batch.total_shares <= 0:
                    continue

                batch.available_shares = batch.total_shares
                batch.status = "released"
                batch.released_at = timezone.now()
                batch.released_by = request.user
                batch.save()

                AuditLog.objects.create(
                    actor=request.user,
                    action="Share batch released",
                    object_type="ShareBatch",
                    object_id=str(batch.pk),
                    reason=(
                        f"Released {batch.total_shares} shares "
                        f"at KSh {SHARE_PRICE} per share."
                    ),
                )

                released += 1

        self.message_user(
            request,
            f"{released} batch(es) released.",
            messages.SUCCESS if released else messages.WARNING,
        )


admin.site.register([
    Package,
    BiddingSession,
    SharePool,
    PaymentEvidence,
    AuditLog,
])
