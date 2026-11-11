
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import (
    PurchaseRequest,
    Package,
    PaymentEvidence,
    ShareBatch,
    SellerListing,
)


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = (
            "username",
            "email",
            "password1",
            "password2",
        )


class BuyForm(forms.Form):
    """
    Primary-market purchase form.
    Members buy shares from administrator-released batches.
    """

    batch = forms.ModelChoiceField(
        queryset=ShareBatch.objects.none(),
        label="Available share batch",
        empty_label="Select a share batch",
    )

    shares = forms.IntegerField(
        min_value=1,
        label="Number of shares",
        widget=forms.NumberInput(attrs={
            "placeholder": "e.g. 100",
            "min": "1",
            "step": "1",
        }),
    )

    package = forms.ModelChoiceField(
        queryset=Package.objects.filter(active=True),
        label="Maturity package",
        empty_label="Select a maturity package",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["batch"].queryset = (
            ShareBatch.objects.filter(
                status="released",
                available_shares__gt=0,
            ).order_by("-released_at")
        )


class SecondaryBuyForm(forms.Form):
    """
    Secondary-market purchase form.
    Members buy matured shares from other members.
    """

    listing = forms.ModelChoiceField(
        queryset=SellerListing.objects.none(),
        label="Available seller listing",
        empty_label="Select a listing",
    )

    shares = forms.IntegerField(
        min_value=1,
        label="Number of shares",
        widget=forms.NumberInput(attrs={
            "placeholder": "e.g. 50",
            "min": "1",
            "step": "1",
        }),
    )

    package = forms.ModelChoiceField(
        queryset=Package.objects.filter(active=True),
        label="New maturity package",
        empty_label="Select a maturity package",
    )

    def __init__(self, *args, buyer=None, **kwargs):
        super().__init__(*args, **kwargs)

        listings = SellerListing.objects.filter(
            status__in=["available", "partial"],
            holding__status="listed",
            total_shares__gt=0,
        ).order_by("created_at")

        if buyer is not None:
            listings = listings.exclude(seller=buyer)

        self.fields["listing"].queryset = listings

    def clean(self):
        cleaned_data = super().clean()

        listing = cleaned_data.get("listing")
        shares = cleaned_data.get("shares")

        if listing and shares:
            if shares > listing.remaining_shares:
                self.add_error(
                    "shares",
                    f"Only {listing.remaining_shares:,} shares "
                    "are currently available in this listing.",
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
        widgets = {
            "note": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "Optional payment note",
            })
        }
