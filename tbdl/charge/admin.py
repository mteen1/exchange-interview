from django.contrib import admin

from .models import ChargeSale
from .models import CreditRequest
from .models import PhoneNumber

admin.site.register(PhoneNumber)
admin.site.register(CreditRequest)
admin.site.register(ChargeSale)
