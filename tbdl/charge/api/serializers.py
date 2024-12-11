from rest_framework import serializers

from tbdl.charge.models import ChargeSale
from tbdl.charge.models import CreditRequest
from tbdl.charge.models import PhoneNumber


class PhoneNumberSerializer(serializers.ModelSerializer):
    number = serializers.CharField(help_text="Phone number (digits only)")
    current_charge = serializers.IntegerField(
        help_text="Current charge balance for this number",
        read_only=True,
    )

    class Meta:
        model = PhoneNumber
        fields = ["id", "number", "title", "is_active", "current_charge"]
        read_only_fields = ["current_charge"]

    def validate_number(self, value):
        if not value.isdigit():
            raise serializers.ValidationError("Phone number must contain only digits")
        return value


class CreditRequestSerializer(serializers.ModelSerializer):
    amount = serializers.IntegerField(
        help_text="Amount of credit requested (must be greater than 0)",
    )
    status = serializers.CharField(
        help_text="Current status of the request",
        read_only=True,
    )
    processed = serializers.BooleanField(
        help_text="Whether the request has been processed",
        read_only=True,
    )

    class Meta:
        model = CreditRequest
        fields = ["id", "amount", "status", "processed", "created_at"]
        read_only_fields = ["status", "processed", "created_at"]

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than 0")
        return value


class ChargeSaleSerializer(serializers.ModelSerializer):
    phone_number_id = serializers.IntegerField(
        help_text="ID of the active phone number to charge",
    )
    amount = serializers.IntegerField(
        help_text="Amount to charge (must be greater than 0)",
    )

    class Meta:
        model = ChargeSale
        fields = [
            "id",
            "phone_number_id",
            "amount",
            "status",
            "processed",
            "created_at",
        ]
        read_only_fields = ["status", "processed", "created_at"]

    async def validate(self, attrs):
        phone_number = await PhoneNumber.objects.filter(
            id=attrs["phone_number_id"],
            is_active=True,
        ).afirst()
        if not phone_number:
            raise serializers.ValidationError("Invalid phone number")
        if attrs["amount"] <= 0:
            raise serializers.ValidationError("Amount must be greater than 0")
        attrs["phone_number"] = phone_number
        return attrs
