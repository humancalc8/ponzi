
from datetime import timedelta
from decimal import Decimal
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

SHARE_PRICE = Decimal("1.00")

MIN_BID_AMOUNT = Decimal("1200.00")
MAX_BID_AMOUNT = Decimal("5000.00")

MIN_BID_SHARES = 1200
MAX_BID_SHARES = 5000

REFERRAL_COMMISSION_RATE = Decimal("0.0200")



class Package(models.Model):
    name = models.CharField(max_length=60)
    days = models.PositiveIntegerField()
    rate = models.DecimalField(max_digits=5, decimal_places=4)
    active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.days} days)"


class BiddingSession(models.Model):
    STATUS_CHOICES = [
        ("scheduled", "Scheduled"),
        ("open", "Open"),
        ("closed", "Closed"),
        ("paused", "Paused"),
    ]

    name = models.CharField(max_length=30)
    opens_at = models.DateTimeField()
    closes_at = models.DateTimeField()
    status = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default="scheduled",
    )

    def is_open(self):
        now = timezone.now()
        return (
            self.status == "open"
            and self.opens_at <= now <= self.closes_at
        )

    def __str__(self):
        return self.name


class SharePool(models.Model):
    title = models.CharField(
        max_length=100,
        default="Current share pool",
    )
    total_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
    )
    remaining_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
    )
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.title


class ShareBatch(models.Model):
    STATUS = [
        ("draft", "Draft"),
        ("released", "Released"),
        ("closed", "Closed"),
    ]

    reference = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    title = models.CharField(max_length=120)
    total_shares = models.PositiveIntegerField()
    available_shares = models.PositiveIntegerField(default=0)
    share_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=SHARE_PRICE,
        editable=False,
    )
    status = models.CharField(
        max_length=12,
        choices=STATUS,
        default="draft",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True, blank=True)
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="released_share_batches",
    )

    @property
    def total_value(self):
        return Decimal(self.total_shares) * self.share_price

    def save(self, *args, **kwargs):
        self.share_price = SHARE_PRICE
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} - {self.total_shares:,} shares"


class PurchaseRequest(models.Model):
    STATUS = [
        ("submitted", "Submitted"),
        ("accepted", "Accepted"),
        ("rejected", "Rejected"),
        ("cancelled", "Cancelled"),
    ]

    reference = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="purchase_requests",
    )
    session = models.ForeignKey(
        BiddingSession,
        on_delete=models.PROTECT,
    )
    package = models.ForeignKey(
        Package,
        on_delete=models.PROTECT,
    )
    batch = models.ForeignKey(
        ShareBatch,
        on_delete=models.PROTECT,
        related_name="purchase_requests",
        null=True,
        blank=True,
    )
    shares_requested = models.PositiveIntegerField(default=0)
    share_price_snapshot = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=SHARE_PRICE,
    )
    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
    )
    status = models.CharField(
        max_length=12,
        choices=STATUS,
        default="submitted",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.reference} - {self.amount}"


class Holding(models.Model):
    STATUS = [
        ("active", "Active"),
        ("matured", "Matured"),
        ("listed", "Listed"),
        ("closed", "Closed"),
    ]

    reference = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="holdings",
    )

    # Primary-market origin. Nullable for secondary-market holdings.
    purchase = models.OneToOneField(
        PurchaseRequest,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="holding",
    )

    # Secondary-market origin. Nullable for primary-market holdings.
    source_allocation = models.OneToOneField(
        "Allocation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="transferred_holding",
    )

    shares = models.PositiveIntegerField(default=0)
    share_price_snapshot = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=SHARE_PRICE,
    )
    principal = models.DecimalField(
        max_digits=14,
        decimal_places=2,
    )
    rate_snapshot = models.DecimalField(
        max_digits=5,
        decimal_places=4,
    )
    days_snapshot = models.PositiveIntegerField()
    activated_at = models.DateTimeField(default=timezone.now)
    maturity_at = models.DateTimeField()
    maturity_value = models.DecimalField(
        max_digits=14,
        decimal_places=2,
    )
    status = models.CharField(
        max_length=12,
        choices=STATUS,
        default="active",
    )

    def save(self, *args, **kwargs):
        # Preserve compatibility with older primary-market holdings.
        if self.purchase_id:
            if not self.shares:
                self.shares = self.purchase.shares_requested

            if not self.share_price_snapshot:
                self.share_price_snapshot = (
                    self.purchase.share_price_snapshot or SHARE_PRICE
                )

        if not self.maturity_at:
            self.maturity_at = (
                self.activated_at
                + timedelta(days=self.days_snapshot)
            )

        super().save(*args, **kwargs)

    @property
    def current_share_value(self):
        return Decimal(self.shares) * self.share_price_snapshot

    def __str__(self):
        return f"{self.owner} - {self.shares:,} shares"


class SellerListing(models.Model):
    STATUS = [
        ("available", "Available"),
        ("partial", "Partially allocated"),
        ("reserved", "Fully reserved"),
        ("completed", "Completed"),
        ("disputed", "Disputed"),
    ]

    holding = models.OneToOneField(
        Holding,
        on_delete=models.PROTECT,
        related_name="listing",
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="seller_listings",
    )

    # Quantity-based listing fields.
    total_shares = models.PositiveIntegerField(default=0)
    allocated_shares = models.PositiveIntegerField(default=0)
    received_shares = models.PositiveIntegerField(default=0)

    # Monetary fields retained for compatibility and payment records.
    total_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
    )
    allocated_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
    )
    received_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
    )

    status = models.CharField(
        max_length=12,
        choices=STATUS,
        default="available",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.total_shares and self.holding_id:
            self.total_shares = self.holding.shares

        super().save(*args, **kwargs)

    @property
    def remaining_shares(self):
        return max(
            self.total_shares - self.allocated_shares,
            0,
        )

    @property
    def remaining_amount(self):
        return max(
            self.total_amount - self.allocated_amount,
            Decimal("0.00"),
        )

    def __str__(self):
        return f"{self.seller} - {self.total_shares:,} shares"


class Allocation(models.Model):
    STATUS = [
        ("awaiting_payment", "Awaiting payment"),
        ("submitted", "Payment submitted"),
        ("confirmed", "Confirmed"),
        ("disputed", "Disputed"),
        ("expired", "Expired"),
    ]

    reference = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    listing = models.ForeignKey(
        SellerListing,
        on_delete=models.PROTECT,
        related_name="allocations",
    )
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="buyer_allocations",
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="seller_allocations",
    )

    # The quantity being purchased.
    shares = models.PositiveIntegerField(default=0)

    # Price and total are recorded when the allocation is created.
    share_price_snapshot = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=SHARE_PRICE,
    )
    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
    )

    # The buyer's selected new maturity package.
    package = models.ForeignKey(
        Package,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="secondary_allocations",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS,
        default="awaiting_payment",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.shares and not self.amount:
            self.amount = (
                Decimal(self.shares) * self.share_price_snapshot
            )

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} - {self.shares:,} shares"


class PaymentEvidence(models.Model):
    allocation = models.OneToOneField(
        Allocation,
        on_delete=models.PROTECT,
        related_name="payment",
    )
    mpesa_code = models.CharField(max_length=30)
    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    seller_confirmed = models.BooleanField(default=False)
    disputed = models.BooleanField(default=False)
    note = models.TextField(blank=True)

    def __str__(self):
        return f"{self.mpesa_code} - {self.amount}"


class AuditLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
    )
    action = models.CharField(max_length=100)
    object_type = models.CharField(max_length=60)
    object_id = models.CharField(max_length=60)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.action} - {self.object_type} #{self.object_id}"

def generate_referral_code():
    return uuid.uuid4().hex[:10].upper()


class ReferralProfile(models.Model):
    """
    Each member receives a unique referral code.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="referral_profile",
    )

    referral_code = models.CharField(
        max_length=20,
        unique=True,
        default=generate_referral_code,
        editable=False,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.referral_code}"

    @property
    def referral_count(self):
        return self.user.direct_referrals.count()


class MemberReferral(models.Model):
    """
    Records the direct relationship between a referrer
    and the member who registered through their link.
    """

    referrer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="direct_referrals",
    )

    referred_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="referral_record",
    )

    referral_code_used = models.CharField(max_length=20)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.referrer_id == self.referred_user_id:
            raise ValidationError(
                "Members cannot refer themselves."
            )

    def __str__(self):
        return (
            f"{self.referrer.username} referred "
            f"{self.referred_user.username}"
        )


class ReferralCommission(models.Model):
    """
    Company-funded commission generated by the first
    qualifying matured holding of a directly referred member.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("paid", "Paid"),
        ("cancelled", "Cancelled"),
    ]

    referral = models.OneToOneField(
        MemberReferral,
        on_delete=models.PROTECT,
        related_name="commission",
    )

    matured_holding = models.OneToOneField(
        "Holding",
        on_delete=models.PROTECT,
        related_name="referral_commission",
    )

    base_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
    )

    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=REFERRAL_COMMISSION_RATE,
    )

    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
    )

    status = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default="pending",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    paid_at = models.DateTimeField(null=True, blank=True)

    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="paid_referral_commissions",
    )

    payment_reference = models.CharField(
        max_length=100,
        blank=True,
    )

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"{self.referral.referrer.username} - "
            f"KSh {self.amount:,.2f} - {self.status}"
        )
