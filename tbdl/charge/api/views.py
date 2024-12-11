import logging

from adrf.mixins import ListModelMixin
from adrf.viewsets import GenericViewSet
from asgiref.sync import sync_to_async
from django.db import models
from django.db import transaction
from django.db.models import F
from drf_spectacular.utils import OpenApiExample
from drf_spectacular.utils import OpenApiParameter
from drf_spectacular.utils import OpenApiResponse
from drf_spectacular.utils import extend_schema
from drf_spectacular.utils import extend_schema_view
from drf_spectacular.utils import inline_serializer
from rest_framework import serializers
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from tbdl.charge.models import ChargeSale
from tbdl.charge.models import CreditRequest
from tbdl.charge.models import PhoneNumber
from tbdl.users.models import User

from .serializers import ChargeSaleSerializer
from .serializers import CreditRequestSerializer
from .serializers import PhoneNumberSerializer

logger = logging.getLogger(__name__)


@extend_schema_view(
    list=extend_schema(
        summary="List active phone numbers",
        description="Returns a list of all active phone numbers available for charging",
        responses={200: PhoneNumberSerializer(many=True)},
    ),
    retrieve=extend_schema(
        summary="Get phone number details",
        description="Returns details for a specific phone number",
        responses={
            200: PhoneNumberSerializer,
            404: OpenApiResponse(description="Phone number not found"),
        },
    ),
    active=extend_schema(
        summary="List active phone numbers",
        description="Alternative endpoint to list active phone numbers",
    ),
)
class PhoneNumberViewSet(GenericViewSet):
    serializer_class = PhoneNumberSerializer
    queryset = PhoneNumber.objects.all()

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

    @action(detail=False, methods=["get"])
    async def active(self, request):
        phone_numbers = [
            phone_number
            async for phone_number in PhoneNumber.objects.filter(
                is_active=True,
            ).select_related()
        ]
        serializer = PhoneNumberSerializer(phone_numbers, many=True)
        return Response(serializer.data)


@sync_to_async
def create_credit_request(user, amount):
    with transaction.atomic():
        credit_request = CreditRequest.objects.create(
            user=user,
            amount=amount,
        )
        return credit_request


@extend_schema_view(
    list=extend_schema(
        summary="List user credit requests",
        description="Returns all credit requests for the authenticated user",
    ),
    create=extend_schema(
        summary="Create credit request",
        description="Create a new credit request for the authenticated user",
        request=inline_serializer(
            name="CreditRequestCreate",
            fields={
                "amount": serializers.IntegerField(
                    help_text="Amount must be greater than 0",
                ),
            },
        ),
        examples=[
            OpenApiExample(
                "Valid Request",
                value={"amount": 100},
                request_only=True,
            ),
        ],
    ),
    approve=extend_schema(
        summary="Approve credit request",
        description="Approve a credit request and add credits to user's account",
        responses={
            200: CreditRequestSerializer,
            400: OpenApiResponse(description="Already processed"),
            404: OpenApiResponse(description="Credit request not found"),
        },
    ),
)
class CreditRequestViewSet(GenericViewSet, ListModelMixin):
    serializer_class = CreditRequestSerializer
    queryset = CreditRequest.objects.all()
    lookup_field = "pk"
    lookup_url_kwarg = "pk"

    async def create(self, request):
        serializer = CreditRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            credit_request = await create_credit_request(
                request.user,
                serializer.validated_data["amount"],
            )
            return Response(
                CreditRequestSerializer(credit_request).data,
                status=status.HTTP_201_CREATED,
            )
        except Exception:
            logger.exception("Error creating credit request")
            return Response(
                {"detail": "Error processing request"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    async def list(self, request):
        credit_requests = [
            request async for request in CreditRequest.objects.filter(user=request.user)
        ]
        serializer = CreditRequestSerializer(credit_requests, many=True)
        return Response(serializer.data)

    def perform_approve(self, credit_request):
        with transaction.atomic():
            # Lock both records
            credit_request = CreditRequest.objects.select_for_update().get(
                id=credit_request.id,
            )
            user = User.objects.select_for_update().get(id=credit_request.user_id)

            if credit_request.processed:
                return None, "Already processed"

            credit_request.status = "APPROVED"
            credit_request.processed = True
            credit_request.save()

            # Use F() to prevent race conditions
            User.objects.filter(id=user.id).update(
                credit=F("credit") + credit_request.amount,
            )

            return credit_request, None

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="pk",
                type=int,
                location=OpenApiParameter.PATH,
                description="Credit request ID",
            ),
        ],
    )
    @action(detail=True, methods=["post"])
    async def approve(self, request, pk=None):
        try:
            credit_request = await CreditRequest.objects.aget(pk=pk)
            result, error = await sync_to_async(self.perform_approve)(credit_request)

            if error:
                return Response(
                    {"detail": error},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            return Response(CreditRequestSerializer(result).data)
        except CreditRequest.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)


@sync_to_async
def create_charge_sale(user, amount, phone_number_id):
    with transaction.atomic():
        user = User.objects.select_for_update().get(id=user.id)
        if user.credit < amount:
            return None, "Insufficient credit"

        # Update user credit using F() expression
        User.objects.filter(id=user.id).update(credit=F("credit") - amount)

        # Update phone number charge using F() expression
        PhoneNumber.objects.filter(id=phone_number_id).select_for_update().update(
            current_charge=F("current_charge") + amount,
        )

        charge_sale = ChargeSale.objects.create(
            user=user,
            phone_number_id=phone_number_id,
            amount=amount,
            status="APPROVED",
            processed=True,
        )

        user.refresh_from_db()
        return charge_sale, None


@extend_schema_view(
    list=extend_schema(
        summary="List charge sales",
        description="Returns all charge sales for the authenticated user",
        responses={200: ChargeSaleSerializer(many=True)},
    ),
    create=extend_schema(
        summary="Create charge sale",
        description="Create a new charge sale transaction",
        request=inline_serializer(
            name="ChargeSaleCreate",
            fields={
                "amount": serializers.IntegerField(
                    help_text="Amount must be greater than 0",
                ),
                "phone_number_id": serializers.IntegerField(
                    help_text="ID of active phone number",
                ),
            },
        ),
        examples=[
            OpenApiExample(
                "Valid Request",
                value={
                    "amount": 50,
                    "phone_number_id": 1,
                },
                request_only=True,
            ),
        ],
        responses={
            201: ChargeSaleSerializer,
            400: OpenApiResponse(description="Invalid data or insufficient credit"),
        },
    ),
    validate_all=extend_schema(
        summary="Validate all transactions",
        description="Validate consistency between credit requests and charge sales across all users",
    ),
    validate_user=extend_schema(
        summary="Validate user transactions",
        description="Validate consistency between credit requests and charge sales for a specific user",
        parameters=[
            OpenApiParameter(
                name="user_id",
                type=int,
                location=OpenApiParameter.PATH,
                description="User ID to validate",
            ),
        ],
        responses={404: OpenApiResponse(description="User not found")},
    ),
)
class ChargeSaleViewSet(GenericViewSet):
    serializer_class = ChargeSaleSerializer
    queryset = ChargeSale.objects.all()

    async def get_queryset(self):
        # This helps with schema generation
        return self.queryset.filter(user=self.request.user)

    async def create(self, request):
        try:
            serializer = ChargeSaleSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            validated_data = await serializer.validated_data
            charge_sale, error = await create_charge_sale(
                request.user,
                validated_data["amount"],
                validated_data["phone_number_id"],
            )
            if error:
                return Response(
                    {"detail": error},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response(
                ChargeSaleSerializer(charge_sale).data,
                status=status.HTTP_201_CREATED,
            )
        except PhoneNumber.DoesNotExist:
            return Response(
                {"detail": "Phone number not found"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    async def list(self, request):
        charge_sales = [
            sale async for sale in ChargeSale.objects.filter(user=request.user)
        ]
        serializer = ChargeSaleSerializer(charge_sales, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    async def validate_all(self, request):
        try:
            approved_credits = await CreditRequest.objects.filter(
                status="APPROVED",
                processed=True,
            ).aaggregate(total=models.Sum("amount"))

            current_credits = await User.objects.aaggregate(
                total=models.Sum("credit"),
            )

            total_approved = approved_credits["total"] or 0
            current_total = current_credits["total"] or 0
            total_spent = total_approved - current_total

            charge_sales = await ChargeSale.objects.filter(
                status="APPROVED",
                processed=True,
            ).aaggregate(total=models.Sum("amount"))
            total_sales = charge_sales["total"] or 0

            is_consistent = abs(total_spent - total_sales) == 0

            return Response(
                {
                    "total_approved_credits": total_approved,
                    "current_user_credits": current_total,
                    "total_spent_credits": total_spent,
                    "total_charge_sales": total_sales,
                    "is_consistent": is_consistent,
                    "details": "All transactions are consistent"
                    if is_consistent
                    else f"Mismatch: Users spent {total_spent} but charge sales total is {total_sales}",
                },
            )
        except Exception:
            logger.exception("Error during transaction validation")
            raise

    @action(detail=False, methods=["get"], url_path="validate/(?P<user_id>[^/.]+)")
    async def validate_user(self, request, user_id=None):
        try:
            user = await User.objects.aget(id=user_id)

            approved = await CreditRequest.objects.filter(
                user=user,
                status="APPROVED",
                processed=True,
            ).aaggregate(total=models.Sum("amount"))

            total_approved = approved["total"] or 0
            total_spent = total_approved - user.credit

            sales = await ChargeSale.objects.filter(
                user=user,
                status="APPROVED",
                processed=True,
            ).aaggregate(total=models.Sum("amount"))
            total_sales = sales["total"] or 0

            is_consistent = abs(total_spent - total_sales) == 0

            return Response(
                {
                    "total_approved_credits": total_approved,
                    "current_user_credits": user.credit,
                    "total_spent_credits": total_spent,
                    "total_charge_sales": total_sales,
                    "is_consistent": is_consistent,
                    "details": "All transactions are consistent"
                    if is_consistent
                    else f"Mismatch: User spent {total_spent} but charge sales total is {total_sales}",
                },
            )
        except User.DoesNotExist:
            return Response(
                {"detail": "User not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception:
            logger.exception(
                f"Error validating user transactions for user ID {user_id}",
            )
            raise
