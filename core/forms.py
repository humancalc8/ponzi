
from decimal import Decimal
from django.db.models import F
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import (
    SHARE_PRICE,
    MIN_BID_AMOUNT,
    MAX_BID_AMOUNT,
    MIN_BID_SHARES,
    MAX_BID_SHARES,
    Package,
    ShareBatch,
    PurchaseRequest,
    PaymentEvidence,
    SharePool,
    SellerListing,
    ReferralProfile,
)


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)

    referral_code = forms.CharField(
        required=False,
        max_length=20,
        label="Referral code",
        help_text="Optional. Enter the referral code of the member who invited you.",
    )

    class Meta:
        model = User
        fields = (
            "username",
            "email",
            "password1",
            "password2",
        )

    def clean_referral_code(self):
        code = self.cleaned_data.get("referral_code", "").strip().upper()

        if code and not ReferralProfile.objects.filter(
            referral_code=code
        ).exists():
            raise forms.ValidationError(
                "That referral code is invalid. Check the code and try again."
            )

        return code


class BuyForm(forms.Form):
    batch = forms.ModelChoiceField(
        queryset=ShareBatch.objects.none(),
        label="Available share batch",
    )

    shares = forms.IntegerField(
        min_value=MIN_BID_SHARES,
        max_value=MAX_BID_SHARES,
        label="Number of shares",
        help_text="Minimum 1,200 shares. Maximum 5,000 shares.",
    )

    package = forms.ModelChoiceField(
        queryset=Package.objects.none(),
        label="Investment package",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["batch"].queryset = ShareBatch.objects.filter(
            status="released",
            available_shares__gt=0,
        ).order_by("-released_at")

        self.fields["package"].queryset = Package.objects.filter(
            active=True
        ).order_by("days")

    def clean_shares(self):
        shares = self.cleaned_data["shares"]
        amount = Decimal(shares) * SHARE_PRICE

        if amount < MIN_BID_AMOUNT:
            raise forms.ValidationError(
                f"The minimum bid is KSh {MIN_BID_AMOUNT:,.2f}."
            )

        if amount > MAX_BID_AMOUNT:
            raise forms.ValidationError(
                f"The maximum bid is KSh {MAX_BID_AMOUNT:,.2f}."
            )

        return shares


class SecondaryBuyForm(forms.Form):
    listing = forms.ModelChoiceField(
        queryset=SellerListing.objects.none(),
        label="Available seller listing",
    )

    shares = forms.IntegerField(
        min_value=MIN_BID_SHARES,
        max_value=MAX_BID_SHARES,
        label="Number of shares",
        help_text="Minimum 1,200 shares. Maximum 5,000 shares.",
    )

    package = forms.ModelChoiceField(
        queryset=Package.objects.none(),
        label="Investment package",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["listing"].queryset = (
            SellerListing.objects.filter(
                status__in=["available", "partial"],
                holding__status="listed",
                total_shares__gt=0,
            )
            .exclude(allocated_shares__gte=F("total_shares"))
        )

        self.fields["package"].queryset = Package.objects.filter(
            active=True
        ).order_by("days")

    def clean(self):
        cleaned_data = super().clean()
        listing = cleaned_data.get("listing")
        shares = cleaned_data.get("shares")

        if listing and shares:
            remaining_shares = listing.remaining_shares

            if shares > remaining_shares:
                self.add_error(
                    "shares",
                    f"Only {remaining_shares:,} shares are currently available in this listing.",
                )

            amount = Decimal(shares) * SHARE_PRICE

            if amount < MIN_BID_AMOUNT:
                self.add_error(
                    "shares",
                    f"The minimum bid is KSh {MIN_BID_AMOUNT:,.2f}.",
                )

            if amount > MAX_BID_AMOUNT:
                self.add_error(
                    "shares",
                    f"The maximum bid is KSh {MAX_BID_AMOUNT:,.2f}.",
                )

        return cleaned_data


class PaymentForm(forms.ModelForm):
    class Meta:
        model = PaymentEvidence
        fields = (
            "mpesa_code",
            "amount",
            "note",
        )
