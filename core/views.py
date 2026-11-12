
from decimal import Decimal
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum, F, ExpressionWrapper, DecimalField
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import (
    Package,
    BiddingSession,
    ShareBatch,
    PurchaseRequest,
    Holding,
    SellerListing,
    Allocation,
    PaymentEvidence,
    AuditLog,
    ReferralProfile,
    MemberReferral,
    ReferralCommission,
    SHARE_PRICE,
)

from .forms import (
    RegisterForm,
    BuyForm,
    SecondaryBuyForm,
    PaymentForm,
)


# ---------------------------------------------------------
# HOME
# ---------------------------------------------------------

# ---------------------------------------------------------
# HOME
# ---------------------------------------------------------

def home(request):
    # Always display every released batch that still has shares,
    # whether bidding is currently open or closed.
    batches = ShareBatch.objects.filter(
        status="released",
        available_shares__gt=0,
    ).order_by("-released_at")

    # Calculate the total number of shares available across all batches.
    available_shares = batches.aggregate(
        total=Sum("available_shares")
    )["total"] or 0

    # Find the currently open bidding session, if one exists.
    session = BiddingSession.objects.filter(
        status="open"
    ).order_by("opens_at").first()

    # Determine whether bidding is currently open.
    session_is_open = (
        session.is_open()
        if session
        else False
    )

    # Retrieve active packages.
    packages = Package.objects.filter(
        active=True
    )

    return render(
        request,
        "core/home.html",
        {
            "batches": batches,
            "available_shares": available_shares,
            "session": session,
            "session_is_open": session_is_open,
            "packages": packages,
        }
    )


# ---------------------------------------------------------
# REGISTRATION AND REFERRALS
# ---------------------------------------------------------

def register(request):
    form = RegisterForm(
        request.POST or None,
        initial={
            "referral_code": request.GET.get("ref", "").strip().upper()
        },
    )

    if request.method == "POST" and form.is_valid():
        referral_code = form.cleaned_data.get("referral_code", "")

        try:
            with transaction.atomic():
                user = form.save()

                # Every member gets their own referral profile.
                ReferralProfile.objects.get_or_create(user=user)

                # Save the direct referral relationship, if a code was used.
                if referral_code:
                    referrer_profile = ReferralProfile.objects.select_for_update().get(
                        referral_code=referral_code
                    )

                    if referrer_profile.user_id == user.pk:
                        raise ValueError(
                            "You cannot use your own referral code."
                        )

                    MemberReferral.objects.create(
                        referrer=referrer_profile.user,
                        referred_user=user,
                        referral_code_used=referral_code,
                    )

            login(request, user)

            messages.success(
                request,
                "Your member account is ready."
            )

            return redirect("dashboard")

        except (ReferralProfile.DoesNotExist, ValueError) as error:
            messages.error(request, str(error))

    return render(request, "core/register.html", {
        "form": form,
    })


# ---------------------------------------------------------
# MEMBER DASHBOARD
# ---------------------------------------------------------

@login_required
def dashboard(request):

    # Ensure existing members who registered before referrals
    # were introduced also receive a referral profile.
    referral_profile, _ = ReferralProfile.objects.get_or_create(
        user=request.user
    )

    holdings = Holding.objects.filter(
        owner=request.user
    ).order_by("-activated_at")

    listings = SellerListing.objects.filter(
        seller=request.user,
        status__in=["available", "partial", "reserved"],
    ).annotate(
        remaining_amount=ExpressionWrapper(
            F("total_amount") - F("allocated_amount"),
            output_field=DecimalField(
                max_digits=14,
                decimal_places=2,
            ),
        )
    ).order_by("-created_at")

    allocations = (
        Allocation.objects.filter(buyer=request.user)
        | Allocation.objects.filter(seller=request.user)
    )

    active_shares = holdings.filter(
        status="active"
    ).aggregate(
        total=Sum("shares")
    )["total"] or 0

    listed_shares = holdings.filter(
        status="listed"
    ).aggregate(
        total=Sum("shares")
    )["total"] or 0

    active_total = holdings.filter(
        status="active"
    ).aggregate(
        total=Sum("principal")
    )["total"] or Decimal("0.00")

    matured_total = listings.aggregate(
        total=Sum("remaining_amount")
    )["total"] or Decimal("0.00")

    # Referral information.
    referrals = MemberReferral.objects.filter(
        referrer=request.user
    ).select_related(
        "referred_user"
    ).order_by("-created_at")

    referral_commissions = ReferralCommission.objects.filter(
        referral__referrer=request.user
    ).select_related(
        "referral",
        "matured_holding",
    ).order_by("-created_at")

    pending_commission = referral_commissions.filter(
        status="pending"
    ).aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0.00")

    paid_commission = referral_commissions.filter(
        status="paid"
    ).aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0.00")

    referral_link = (
        request.build_absolute_uri(reverse("register"))
        + f"?ref={referral_profile.referral_code}"
    )

    return render(request, "core/dashboard.html", {
        "holdings": holdings[:5],
        "listings": listings,
        "active_total": active_total,
        "matured_total": matured_total,
        "active_shares": active_shares,
        "listed_shares": listed_shares,
        "allocation_count": allocations.count(),

        # Referral dashboard data.
        "referral_profile": referral_profile,
        "referral_code": referral_profile.referral_code,
        "referral_link": referral_link,
        "referrals": referrals,
        "referral_count": referrals.count(),
        "referral_commissions": referral_commissions,
        "pending_commission": pending_commission,
        "paid_commission": paid_commission,
    })


# ---------------------------------------------------------
# PRIMARY MARKET: BUY FROM RELEASED SHARE BATCHES
# ---------------------------------------------------------

@login_required
def buy_shares(request):
    session = BiddingSession.objects.filter(
        status="open"
    ).order_by("opens_at").first()

    form = BuyForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        if not session or not session.is_open():
            messages.error(request, "Bidding is not currently open.")
        else:
            batch = form.cleaned_data["batch"]
            shares = form.cleaned_data["shares"]
            package = form.cleaned_data["package"]

            if batch.status != "released":
                messages.error(
                    request,
                    "This share batch is no longer available."
                )

            elif shares > batch.available_shares:
                messages.error(
                    request,
                    f"Only {batch.available_shares:,} shares are currently available."
                )

            else:
                request.session["pending_share_checkout"] = {
                    "batch_id": batch.pk,
                    "shares": shares,
                    "package_id": package.pk,
                    "session_id": session.pk,
                }

                return redirect("share_checkout")

    return render(request, "core/buy.html", {
        "form": form,
        "session": session,
    })


# ---------------------------------------------------------
# PRIMARY MARKET CHECKOUT
# ---------------------------------------------------------

@login_required
def share_checkout(request):

    pending = request.session.get("pending_share_checkout")

    if not pending:
        messages.error(request, "Please select your shares first.")
        return redirect("buy")

    try:
        batch = ShareBatch.objects.get(pk=pending["batch_id"])
        package = Package.objects.get(pk=pending["package_id"])
        session = BiddingSession.objects.get(pk=pending["session_id"])

    except (
        ShareBatch.DoesNotExist,
        Package.DoesNotExist,
        BiddingSession.DoesNotExist,
        KeyError,
        TypeError,
    ):
        request.session.pop("pending_share_checkout", None)
        messages.error(
            request,
            "Your checkout selection is no longer valid."
        )
        return redirect("buy")

    shares = int(pending["shares"])
    amount = Decimal(shares) * SHARE_PRICE

    if request.method == "POST":
        phone = request.POST.get("phone", "").strip()

        if not phone:
            messages.error(
                request,
                "Please enter your M-Pesa phone number."
            )

        elif not session.is_open():
            messages.error(
                request,
                "This bidding session is no longer open."
            )
            request.session.pop("pending_share_checkout", None)
            return redirect("buy")

        else:
            try:
                with transaction.atomic():
                    batch = ShareBatch.objects.select_for_update().get(
                        pk=pending["batch_id"]
                    )

                    if batch.status != "released":
                        raise ValueError(
                            "This share batch is no longer available."
                        )

                    if shares > batch.available_shares:
                        raise ValueError(
                            f"Only {batch.available_shares:,} shares remain available."
                        )

                    batch.available_shares -= shares
                    batch.save(
                        update_fields=["available_shares"]
                    )

                    purchase = PurchaseRequest.objects.create(
                        buyer=request.user,
                        session=session,
                        package=package,
                        batch=batch,
                        shares_requested=shares,
                        share_price_snapshot=SHARE_PRICE,
                        amount=amount,
                        status="submitted",
                    )

                    AuditLog.objects.create(
                        actor=request.user,
                        action="Submitted demo primary share purchase request",
                        object_type="PurchaseRequest",
                        object_id=str(purchase.pk),
                        reason=(
                            f"Demo checkout: {shares} shares at "
                            f"KSh {SHARE_PRICE} each. "
                            f"Phone entered: {phone}"
                        ),
                    )

                request.session.pop(
                    "pending_share_checkout",
                    None,
                )

                messages.success(
                    request,
                    "Demo purchase request submitted successfully. "
                    "Your request is awaiting administrator review. "
                    "No actual payment was made."
                )

                return redirect("transactions")

            except ValueError as error:
                messages.error(request, str(error))

    return render(request, "core/checkout.html", {
        "batch": batch,
        "package": package,
        "shares": shares,
        "amount": amount,
        "share_price": SHARE_PRICE,
    })


# ---------------------------------------------------------
# SECONDARY MARKET: AVAILABLE SELLER LISTINGS
# ---------------------------------------------------------

@login_required
def marketplace(request):
    listings = SellerListing.objects.filter(
        status__in=["available", "partial"],
        holding__status="listed",
        total_shares__gt=F("allocated_shares"),
    ).exclude(
        seller=request.user
    ).select_related(
        "seller",
        "holding",
    ).order_by("-created_at")

    return render(request, "core/marketplace.html", {
        "listings": listings,
        "share_price": SHARE_PRICE,
    })


# ---------------------------------------------------------
# SECONDARY MARKET: BUY SHARES FROM ANOTHER MEMBER
# ---------------------------------------------------------

@login_required
def buy_from_member(request, pk):
    listing = get_object_or_404(
        SellerListing.objects.select_related(
            "seller",
            "holding",
        ),
        pk=pk,
    )

    if listing.seller_id == request.user.pk:
        messages.error(
            request,
            "You cannot purchase your own listing."
        )
        return redirect("marketplace")

    # The current SecondaryBuyForm does not accept a buyer argument.
    form = SecondaryBuyForm(
        request.POST or None,
        initial={"listing": listing.pk},
    )

    if request.method == "POST" and form.is_valid():

        selected_listing = form.cleaned_data["listing"]
        shares = form.cleaned_data["shares"]
        package = form.cleaned_data["package"]

        try:
            with transaction.atomic():

                locked_listing = SellerListing.objects.select_for_update().get(
                    pk=selected_listing.pk
                )

                if locked_listing.seller_id == request.user.pk:
                    raise ValueError(
                        "You cannot purchase your own shares."
                    )

                if locked_listing.status not in ("available", "partial"):
                    raise ValueError(
                        "This listing is no longer available."
                    )

                if locked_listing.holding.status != "listed":
                    raise ValueError(
                        "The seller's holding is not available for sale."
                    )

                remaining = locked_listing.remaining_shares

                if shares > remaining:
                    raise ValueError(
                        f"Only {remaining:,} shares remain available."
                    )

                amount = Decimal(shares) * SHARE_PRICE

                allocation = Allocation.objects.create(
                    listing=locked_listing,
                    buyer=request.user,
                    seller=locked_listing.seller,
                    shares=shares,
                    share_price_snapshot=SHARE_PRICE,
                    amount=amount,
                    package=package,
                    status="awaiting_payment",
                )

                locked_listing.allocated_shares += shares
                locked_listing.allocated_amount += amount

                if (
                    locked_listing.allocated_shares
                    >= locked_listing.total_shares
                ):
                    locked_listing.status = "reserved"
                else:
                    locked_listing.status = "partial"

                locked_listing.save(
                    update_fields=[
                        "allocated_shares",
                        "allocated_amount",
                        "status",
                    ]
                )

                AuditLog.objects.create(
                    actor=request.user,
                    action="Reserved secondary-market shares",
                    object_type="Allocation",
                    object_id=str(allocation.pk),
                    reason=(
                        f"Reserved {shares} shares "
                        f"for KSh {amount:,.2f}."
                    ),
                )

            messages.success(
                request,
                f"You reserved {shares:,} shares for "
                f"KSh {amount:,.2f}. Submit payment evidence "
                "to continue."
            )

            return redirect("transactions")

        except ValueError as error:
            messages.error(request, str(error))

    return render(request, "core/secondary_buy.html", {
        "form": form,
        "listing": listing,
        "share_price": SHARE_PRICE,
    })


# ---------------------------------------------------------
# BOUGHT SHARES
# ---------------------------------------------------------

@login_required
def bought_shares(request):
    holdings = Holding.objects.filter(
        owner=request.user
    ).order_by("-activated_at")

    return render(request, "core/bought.html", {
        "holdings": holdings,
    })


# ---------------------------------------------------------
# SOLD SHARES AND ALLOCATIONS
# ---------------------------------------------------------

@login_required
def sold_shares(request):
    listings = SellerListing.objects.filter(
        seller=request.user
    ).prefetch_related(
        "allocations"
    ).order_by("-created_at")

    incoming = Allocation.objects.filter(
        seller=request.user
    ).select_related(
        "listing",
        "buyer",
        "package",
    ).order_by("-created_at")

    outgoing = Allocation.objects.filter(
        buyer=request.user
    ).select_related(
        "listing",
        "seller",
        "package",
    ).order_by("-created_at")

    return render(request, "core/sold.html", {
        "listings": listings,
        "incoming": incoming,
        "outgoing": outgoing,
    })


# ---------------------------------------------------------
# TRANSACTIONS
# ---------------------------------------------------------

@login_required
def transactions(request):
    purchase_requests = PurchaseRequest.objects.filter(
        buyer=request.user
    ).order_by("-created_at")

    allocations = (
        Allocation.objects.filter(buyer=request.user)
        | Allocation.objects.filter(seller=request.user)
    )

    return render(request, "core/transactions.html", {
        "requests": purchase_requests,
        "allocations": allocations.order_by("-created_at"),
    })


# ---------------------------------------------------------
# SUBMIT SECONDARY-MARKET PAYMENT EVIDENCE
# ---------------------------------------------------------

@login_required
def submit_payment(request, pk):

    form = PaymentForm(request.POST or None)

    if request.method == "POST" and form.is_valid():

        try:
            with transaction.atomic():

                allocation = Allocation.objects.select_for_update().get(
                    pk=pk,
                    buyer=request.user,
                )

                if allocation.status != "awaiting_payment":
                    raise ValueError(
                        "This allocation is not awaiting payment."
                    )

                if allocation.package_id is None:
                    raise ValueError(
                        "This allocation has no maturity package."
                    )

                if form.cleaned_data["amount"] != allocation.amount:
                    raise ValueError(
                        "The payment amount must match the allocation amount."
                    )

                if PaymentEvidence.objects.filter(
                    allocation=allocation
                ).exists():
                    raise ValueError(
                        "Payment evidence has already been submitted."
                    )

                evidence = form.save(commit=False)
                evidence.allocation = allocation
                evidence.save()

                allocation.status = "submitted"
                allocation.save(update_fields=["status"])

                AuditLog.objects.create(
                    actor=request.user,
                    action="Submitted payment evidence",
                    object_type="Allocation",
                    object_id=str(allocation.pk),
                    reason=(
                        f"Payment evidence submitted for "
                        f"KSh {allocation.amount:,.2f}."
                    ),
                )

            messages.success(
                request,
                "Payment evidence submitted. The seller must confirm receipt."
            )

            return redirect("sold")

        except ValueError as error:
            messages.error(request, str(error))

    allocation = get_object_or_404(
        Allocation.objects.select_related(
            "listing",
            "seller",
            "package",
        ),
        pk=pk,
        buyer=request.user,
    )

    return render(request, "core/payment.html", {
        "form": form,
        "allocation": allocation,
    })


# ---------------------------------------------------------
# CONFIRM PAYMENT AND TRANSFER OWNERSHIP
# ---------------------------------------------------------

@login_required
@require_POST
def confirm_payment(request, pk):

    try:
        with transaction.atomic():

            allocation = Allocation.objects.select_for_update().get(
                pk=pk,
                seller=request.user,
            )

            if allocation.status != "submitted":
                raise ValueError(
                    "This allocation is not awaiting seller confirmation."
                )

            if allocation.package_id is None:
                raise ValueError(
                    "The buyer's maturity package is missing."
                )

            evidence = PaymentEvidence.objects.select_for_update().get(
                allocation=allocation
            )

            if evidence.seller_confirmed:
                raise ValueError(
                    "Payment has already been confirmed."
                )

            if evidence.disputed or allocation.status == "disputed":
                raise ValueError(
                    "This allocation is disputed and cannot be transferred."
                )

            if evidence.amount != allocation.amount:
                raise ValueError(
                    "The payment evidence amount does not match the allocation."
                )

            listing = SellerListing.objects.select_for_update().get(
                pk=allocation.listing_id
            )

            seller_holding = Holding.objects.select_for_update().get(
                pk=listing.holding_id
            )

            if seller_holding.status != "listed":
                raise ValueError(
                    "The seller's holding is not available for transfer."
                )

            if allocation.shares <= 0:
                raise ValueError(
                    "The allocation has an invalid share quantity."
                )

            if seller_holding.shares < allocation.shares:
                raise ValueError(
                    "The seller no longer has enough shares."
                )

            if hasattr(allocation, "transferred_holding"):
                raise ValueError(
                    "These shares have already been transferred."
                )

            original_shares = seller_holding.shares

            seller_principal_per_share = (
                seller_holding.principal / Decimal(original_shares)
            )

            seller_maturity_per_share = (
                seller_holding.maturity_value / Decimal(original_shares)
            )

            principal_reduction = (
                seller_principal_per_share * Decimal(allocation.shares)
            )

            maturity_reduction = (
                seller_maturity_per_share * Decimal(allocation.shares)
            )

            now = timezone.now()
            package = allocation.package

            buyer_principal = (
                Decimal(allocation.shares)
                * allocation.share_price_snapshot
            )

            buyer_maturity_value = (
                buyer_principal
                * (Decimal("1") + package.rate)
            )

            buyer_holding = Holding.objects.create(
                owner=allocation.buyer,
                purchase=None,
                source_allocation=allocation,
                shares=allocation.shares,
                share_price_snapshot=allocation.share_price_snapshot,
                principal=buyer_principal,
                rate_snapshot=package.rate,
                days_snapshot=package.days,
                activated_at=now,
                maturity_value=buyer_maturity_value,
                status="active",
            )

            seller_holding.shares -= allocation.shares
            seller_holding.principal -= principal_reduction
            seller_holding.maturity_value -= maturity_reduction

            if seller_holding.shares == 0:
                seller_holding.status = "closed"

            seller_holding.save(
                update_fields=[
                    "shares",
                    "principal",
                    "maturity_value",
                    "status",
                ]
            )

            evidence.seller_confirmed = True
            evidence.save(update_fields=["seller_confirmed"])

            allocation.status = "confirmed"
            allocation.save(update_fields=["status"])

            listing.received_shares += allocation.shares
            listing.received_amount += allocation.amount

            if listing.received_shares >= listing.total_shares:
                listing.status = "completed"
            else:
                listing.status = "partial"

            listing.save(
                update_fields=[
                    "received_shares",
                    "received_amount",
                    "status",
                ]
            )

            AuditLog.objects.create(
                actor=request.user,
                action="Confirmed payment and transferred shares",
                object_type="Holding",
                object_id=str(buyer_holding.pk),
                reason=(
                    f"Transferred {allocation.shares} shares "
                    f"from seller {allocation.seller_id} "
                    f"to buyer {allocation.buyer_id}. "
                    f"New maturity: {package.days} days."
                ),
            )

        messages.success(
            request,
            f"Payment confirmed. {allocation.shares:,} shares "
            "have been transferred to the buyer."
        )

    except (ValueError, PaymentEvidence.DoesNotExist) as error:
        messages.error(request, str(error))

    return redirect("sold")


# ---------------------------------------------------------
# RAISE A PAYMENT DISPUTE
# ---------------------------------------------------------

@login_required
@require_POST
def raise_dispute(request, pk):

    try:
        with transaction.atomic():

            allocation = Allocation.objects.select_for_update().get(
                pk=pk
            )

            if request.user not in (
                allocation.buyer,
                allocation.seller,
            ):
                raise ValueError(
                    "You cannot access this allocation."
                )

            if allocation.status not in (
                "submitted",
                "awaiting_payment",
            ):
                raise ValueError(
                    "This allocation cannot be disputed in its current state."
                )

            allocation.status = "disputed"
            allocation.save(update_fields=["status"])

            PaymentEvidence.objects.filter(
                allocation=allocation
            ).update(disputed=True)

            AuditLog.objects.create(
                actor=request.user,
                action="Raised payment dispute",
                object_type="Allocation",
                object_id=str(allocation.pk),
                reason=request.POST.get("reason", ""),
            )

        messages.warning(
            request,
            "Dispute recorded. The allocation remains reserved pending review."
        )

    except ValueError as error:
        messages.error(request, str(error))

    return redirect("sold")
