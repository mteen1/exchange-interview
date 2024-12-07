from django.core.validators import MinValueValidator
from django.db import models

from tbdl.users.models import User


class PhoneNumber(models.Model):
    number = models.CharField(max_length=20, unique=True)
    title = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    current_charge = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "phone_numbers"
        indexes = [
            models.Index(fields=["number"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return f"{self.number} - {self.title}"


class BaseTransaction(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
    )
    amount = models.IntegerField(validators=[MinValueValidator(0)])
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="PENDING",
    )
    processed = models.BooleanField(default=False)
    admin_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class CreditRequest(BaseTransaction):
    class Meta:
        db_table = "credit_requests"
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"{self.user} - {self.amount}"


class ChargeSale(BaseTransaction):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("COMPLETED", "Completed"),
        ("FAILED", "Failed"),
    ]

    phone_number = models.ForeignKey(
        PhoneNumber,
        on_delete=models.PROTECT,
        related_name="charges",
    )
    api_response = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "charge_sales"
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["phone_number"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"{self.user} - {self.amount} - {self.phone_number.number}"
