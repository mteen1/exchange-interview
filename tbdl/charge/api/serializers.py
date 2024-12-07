from rest_framework import serializers

from tbdl.charge.models import ChargeSale
from tbdl.charge.models import CreditRequest
from tbdl.charge.models import PhoneNumber


class PhoneNumberSerializer(serializers.ModelSerializer):
    class Meta:
        model = PhoneNumber
        fields = ["id", "number", "title", "is_active", "current_charge"]
        read_only_fields = ["current_charge"]


class CreditRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditRequest
        fields = ["id", "user", "amount", "status", "admin_notes", "created_at"]
        read_only_fields = ["status", "processed"]


class ChargeSaleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChargeSale
        fields = [
            "id",
            "user",
            "phone_number",
            "amount",
            "status",
            "api_response",
            "created_at",
        ]
        read_only_fields = ["status", "processed", "api_response"]
