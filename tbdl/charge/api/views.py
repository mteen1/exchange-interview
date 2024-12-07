from adrf.mixins import ListModelMixin
from adrf.viewsets import ViewSet
from django.db import transaction
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from tbdl.charge.models import ChargeSale
from tbdl.charge.models import CreditRequest
from tbdl.charge.models import PhoneNumber

from .serializers import ChargeSaleSerializer
from .serializers import CreditRequestSerializer
from .serializers import PhoneNumberSerializer


class PhoneNumberViewSet(ViewSet):
    async def list(self, request):
        phone_numbers = [
            phone_number
            async for phone_number in PhoneNumber.objects.filter(is_active=True)
        ]
        serializer = PhoneNumberSerializer(phone_numbers, many=True)
        return Response(serializer.data)

    async def retrieve(self, request, pk=None):
        try:
            phone_number = await PhoneNumber.objects.aget(pk=pk)
            serializer = PhoneNumberSerializer(phone_number)
            return Response(serializer.data)
        except PhoneNumber.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)


class CreditRequestViewSet(ViewSet, ListModelMixin):
    async def create(self, request):
        # Add amount to request data without user field
        data = {"amount": request.data.get("amount")}
        serializer = CreditRequestSerializer(data=data)

        if serializer.is_valid():
            async with transaction.atomic():
                credit_request = await CreditRequest.objects.acreate(
                    user=request.user,  # Always use authenticated user
                    amount=serializer.validated_data["amount"],
                )
            return Response(
                CreditRequestSerializer(credit_request).data,
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    async def list(self, request):
        credit_requests = await CreditRequest.objects.filter(user=request.user).aget()
        serializer = CreditRequestSerializer(credit_requests, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    async def approve(self, request, pk=None):
        try:
            credit_request = await CreditRequest.objects.aget(pk=pk)
            if credit_request.processed:
                return Response(
                    {"detail": "Already processed"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            async with transaction.atomic():
                credit_request.status = "APPROVED"
                credit_request.processed = True
                await credit_request.asave()

                request.user.credit += credit_request.amount
                await request.user.asave()

            return Response(CreditRequestSerializer(credit_request).data)
        except CreditRequest.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)


class ChargeSaleViewSet(ViewSet):
    async def create(self, request):
        serializer = ChargeSaleSerializer(data=request.data)
        if serializer.is_valid():
            if request.user.credit < serializer.validated_data["amount"]:
                return Response(
                    {"detail": "Insufficient credit"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            async with transaction.atomic():
                charge_sale = await ChargeSale.objects.acreate(
                    user=request.user,
                    phone_number=serializer.validated_data["phone_number"],
                    amount=serializer.validated_data["amount"],
                )

                request.user.credit -= charge_sale.amount
                await request.user.asave()

                # Here you would integrate with actual charging API
                # For now just mark as completed
                charge_sale.status = "COMPLETED"
                await charge_sale.asave()

            return Response(
                ChargeSaleSerializer(charge_sale).data,
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    async def list(self, request):
        charge_sales = await ChargeSale.objects.filter(user=request.user).aget()
        serializer = ChargeSaleSerializer(charge_sales, many=True)
        return Response(serializer.data)
