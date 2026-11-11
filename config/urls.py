
from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views

from core import views


urlpatterns = [
    path("admin/", admin.site.urls),

    # Public pages
    path("", views.home, name="home"),
    path("register/", views.register, name="register"),

    # Authentication
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="core/login.html"
        ),
        name="login",
    ),
    path(
        "logout/",
        auth_views.LogoutView.as_view(),
        name="logout",
    ),

    # Member dashboard
    path("dashboard/", views.dashboard, name="dashboard"),

    # Primary market
    path("buy/", views.buy_shares, name="buy"),

    # Secondary market
    path(
        "marketplace/",
        views.marketplace,
        name="marketplace",
    ),
    path(
        "marketplace/buy/<int:pk>/",
        views.buy_from_member,
        name="buy_from_member",
    ),

    # Member holdings and sales
    path("bought/", views.bought_shares, name="bought"),
    path("sold/", views.sold_shares, name="sold"),
    path("transactions/", views.transactions, name="transactions"),

    # Allocation payment workflow
    path(
        "allocation/<int:pk>/payment/",
        views.submit_payment,
        name="submit_payment",
    ),
    path(
        "allocation/<int:pk>/confirm/",
        views.confirm_payment,
        name="confirm_payment",
    ),
    path(
        "allocation/<int:pk>/dispute/",
        views.raise_dispute,
        name="raise_dispute",
    ),
    path(
    "allocation/<int:pk>/payment/",
    views.submit_payment,
    name="submit_payment",
),
path("checkout/", views.share_checkout, name="share_checkout"),
]
