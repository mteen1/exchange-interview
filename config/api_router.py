from django.conf import settings
from rest_framework.routers import DefaultRouter
from rest_framework.routers import SimpleRouter

from tbdl.charge.api.views import ChargeSaleViewSet
from tbdl.charge.api.views import CreditRequestViewSet
from tbdl.charge.api.views import PhoneNumberViewSet
from tbdl.users.api.views import UserViewSet

router = DefaultRouter() if settings.DEBUG else SimpleRouter()

router.register("users", UserViewSet, basename="users")
router.register("phone", PhoneNumberViewSet, basename="phone-numbers")
router.register("credit", CreditRequestViewSet, basename="credit-requests")
router.register("charge", ChargeSaleViewSet, basename="charge-sales")

# Add tags for API grouping
PhoneNumberViewSet.__doc__ = "Phone number management"
CreditRequestViewSet.__doc__ = "Credit request management"
ChargeSaleViewSet.__doc__ = "Charge sale management"

app_name = "api"
urlpatterns = router.urls
