from django.conf import settings
from rest_framework.routers import DefaultRouter
from rest_framework.routers import SimpleRouter

from tbdl.charge.api.views import ChargeSaleViewSet
from tbdl.charge.api.views import CreditRequestViewSet
from tbdl.charge.api.views import PhoneNumberViewSet
from tbdl.users.api.views import UserViewSet

router = DefaultRouter() if settings.DEBUG else SimpleRouter()

router.register("users", UserViewSet)

# Charge routes
router.register("phone-numbers", PhoneNumberViewSet, basename="phone-numbers")
router.register("credit-requests", CreditRequestViewSet, basename="credit-requests")
router.register("charge-sales", ChargeSaleViewSet, basename="charge-sales")


app_name = "api"
urlpatterns = router.urls
