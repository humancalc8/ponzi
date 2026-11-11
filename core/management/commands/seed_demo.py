from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from core.models import Package, BiddingSession, SharePool, Holding, PurchaseRequest, SellerListing

class Command(BaseCommand):
    help = "Create clearly labelled demonstration data"
    def handle(self, *args, **kwargs):
        packages = [
            ("Class 1 · 3 days", 3, Decimal("0.06")),
            ("Class 2 · 7 days", 7, Decimal("0.12")),
            ("Class 3 · 14 days", 14, Decimal("0.20")),
        ]
        for name, days, rate in packages:
            Package.objects.get_or_create(name=name, defaults={"days":days,"rate":rate})
        now = timezone.now()
        BiddingSession.objects.get_or_create(name="Demo morning session", defaults={"opens_at":now-timedelta(hours=1),"closes_at":now+timedelta(hours=5),"status":"open"})
        SharePool.objects.get_or_create(title="Demo available pool", defaults={"total_amount":Decimal("500000"),"remaining_amount":Decimal("500000"),"active":True})
        demo, _ = User.objects.get_or_create(username="demo_member", defaults={"email":"demo@example.test"})
        demo.set_password("DemoPass123!")
        demo.save()
        if not Holding.objects.filter(owner=demo).exists():
            pkg = Package.objects.first()
            req = PurchaseRequest.objects.create(buyer=demo, session=BiddingSession.objects.first(), package=pkg, amount=Decimal("20000"), status="accepted")
            maturity = now + timedelta(days=2)
            h = Holding.objects.create(owner=demo, purchase=req, principal=Decimal("20000"), rate_snapshot=pkg.rate, days_snapshot=pkg.days, activated_at=now, maturity_at=maturity, maturity_value=Decimal("21200"))
        self.stdout.write(self.style.SUCCESS("Demo data ready. Login: demo_member / DemoPass123!"))
