import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from asgiref.sync import sync_to_async
from django.db import models
from django.db import transaction
from django.db.models import F
from ninja import Router
from ninja import Schema
from ninja.security import HttpBearer
from pydantic import Field
from rest_framework.authtoken.models import Token

from tbdl.charge.models import ChargeSale
from tbdl.charge.models import CreditRequest
from tbdl.charge.models import PhoneNumber
from tbdl.users.models import User

logger = logging.getLogger(__name__)


class Error(Schema):
    detail: str


class AuthBearer(HttpBearer):
    async def authenticate(self, request, token):
        try:
            token_obj = await Token.objects.aget(key=token)
            user = await User.objects.aget(id=token_obj.user_id)
            return user
        except Token.DoesNotExist:
            return None


router = Router(auth=AuthBearer())


class PhoneNumberResponseSchema(Schema):
    id: int
    number: str
    is_active: bool


class PhoneNumberSchema(Schema):
    id: int
    number: str
    is_active: bool
    current_charge: int


class CreditRequestSchema(Schema):
    id: int
    amount: int
    status: str
    processed: bool
    created_at: datetime


class CreditRequestCreateSchema(Schema):
    amount: int = Field(..., gt=0)


class ChargeSaleSchema(Schema):
    id: int
    amount: int
    status: str
    phone_number_id: int
    created_at: datetime


class ChargeSaleCreateSchema(Schema):
    amount: int = Field(..., gt=0)
    phone_number_id: int


class ValidationResultSchema(Schema):
    total_approved_credits: int
    current_user_credits: int
    total_spent_credits: int
    total_charge_sales: int
    is_consistent: bool
    details: str


class UserValidationResultSchema(Schema):
    total_approved_credits: int
    current_user_credits: int
    total_spent_credits: int
    total_charge_sales: int
    is_consistent: bool
    details: str


@router.get("/phone-numbers", response=list[PhoneNumberResponseSchema])
async def list_phone_numbers(request):
    return [phone async for phone in PhoneNumber.objects.filter(is_active=True)]


@router.get("/phone-numbers/{phone_id}", response=PhoneNumberSchema)
async def get_phone_number(request, phone_id: int):
    logger.info(f"User requesting phone number details for ID: {phone_id}")
    try:
        return await PhoneNumber.objects.aget(id=phone_id)
    except PhoneNumber.DoesNotExist:
        logger.exception(f"Phone number with ID {phone_id} not found")
        raise


# Credit Request endpoints
@router.get("/credit-requests", response=list[CreditRequestSchema])
async def list_credit_requests(request):
    user = request.auth
    logger.info(f"User {user.id} requesting credit requests list")
    return [req async for req in CreditRequest.objects.filter(user=user)]


@router.post("/credit-requests", response=CreditRequestSchema)
async def create_credit_request(request, data: CreditRequestCreateSchema):
    # user = await sync_to_async(get_user)(request)
    user = request.auth
    logger.info(f"User {user.id} creating credit request for amount: {data.amount}")
    return await CreditRequest.objects.acreate(
        user=user,
        amount=data.amount,
    )


def approve_transaction(request, request_id: int):
    logger.info(f"Processing credit request approval for request ID: {request_id}")
    try:
        with transaction.atomic():
            # Lock the credit request row
            credit_request = CreditRequest.objects.select_for_update().get(
                id=request_id,
            )

            if credit_request.processed:
                logger.warning(f"Credit request {request_id} was already processed")
                return {"detail": "Already processed"}

            # Update credit request status
            credit_request.status = "APPROVED"
            credit_request.processed = True
            credit_request.save()

            # Update user credit using F() expression to prevent race conditions
            User.objects.filter(id=request.auth.id).select_for_update().update(
                credit=F("credit") + credit_request.amount,
            )

            logger.info(
                f"Successfully approved credit request {request_id} for user {request.auth.id}",
            )

            # Refresh from db to get updated state
            return CreditRequest.objects.get(id=request_id)

    except Exception as e:
        logger.exception(f"Error processing credit request {request_id}: {e!s}")
        raise


@router.post("/credit-requests/{request_id}/approve", response=CreditRequestSchema)
async def approve_credit_request(request, request_id: int):
    # we could write custom exception handling here

    return await sync_to_async(approve_transaction)(request, request_id)


# Charge Sale endpoints
@router.get("/charge-sales", response=list[ChargeSaleSchema])
async def list_charge_sales(request):
    user = request.auth
    logger.info(f"User {user} requesting charge sales list")
    return [sale async for sale in ChargeSale.objects.filter(user=user)]


def create_charge(request, data):
    logger.info(
        f"Creating charge sale for user {request.auth.id}, amount: {data.amount}, phone: {data.phone_number_id}",
    )

    try:
        with transaction.atomic():
            # First get and lock the user row
            user = User.objects.select_for_update().get(id=request.auth.id)

            # Check credit AFTER getting lock
            if user.credit < data.amount:
                logger.warning(
                    f"Insufficient credit for user {user.id}. Required: {data.amount}, Available: {user.credit}",
                )
                return {"detail": "Insufficient credit"}

            # Proceed with the update using F expressions
            User.objects.filter(id=user.id).update(
                credit=F("credit") - data.amount,
            )

            PhoneNumber.objects.filter(
                id=data.phone_number_id,
            ).select_for_update().update(
                current_charge=F("current_charge") + data.amount,
            )

            charge_sale = ChargeSale.objects.create(
                user=user,
                phone_number_id=data.phone_number_id,
                amount=data.amount,
                processed=True,
                status="APPROVED",
            )
            logger.info(f"Successfully created charge sale for user {user.id}")
            return charge_sale

    except Exception as e:
        logger.exception(f"Error creating charge sale: {e}")
        raise


@router.post("/charge-sales", response=ChargeSaleSchema)
async def create_charge_sale(request, data: ChargeSaleCreateSchema):
    return await sync_to_async(create_charge)(request, data)


def create_charge_threaded(request, data):
    logger.info(
        f"[Threaded] Creating charge sale for user {request.auth.id}, amount: {data.amount}, phone: {data.phone_number_id}",
    )

    try:
        with transaction.atomic():
            # First get and lock the user row
            user = User.objects.select_for_update().get(id=request.auth.id)

            if user.credit < data.amount:
                logger.warning(
                    f"[Threaded] Insufficient credit for user {user.id}. Required: {data.amount}, Available: {user.credit}",
                )
                return {"detail": "Insufficient credit"}

            User.objects.filter(id=user.id).update(
                credit=F("credit") - data.amount,
            )

            PhoneNumber.objects.filter(
                id=data.phone_number_id,
            ).select_for_update().update(
                current_charge=F("current_charge") + data.amount,
            )

            charge_sale = ChargeSale.objects.create(
                user=user,
                phone_number_id=data.phone_number_id,
                amount=data.amount,
                processed=True,
                status="APPROVED",
            )
            logger.info(
                f"[Threaded] Successfully created charge sale for user {user.id}"
            )
            return charge_sale

    except Exception as e:
        logger.exception(f"[Threaded] Error creating charge sale: {e}")
        raise


@router.post("/charge-sales/threaded", response=ChargeSaleSchema)
def create_charge_sale_threaded(request, data: ChargeSaleCreateSchema):
    with ThreadPoolExecutor(max_workers=20) as executor:
        future = executor.submit(create_charge_threaded, request, data)
        return future.result()


@router.get("/validate", response=ValidationResultSchema)
async def validate_transactions(request):
    """Validate that all spent credits match with charge sales"""
    logger.info("Running transaction validation")

    try:
        # Get total approved credits (what users received)
        approved_credits = await CreditRequest.objects.filter(
            status="APPROVED",
            processed=True,
        ).aaggregate(total=models.Sum("amount"))
        total_approved_credits = approved_credits["total"] or 0

        # Get current remaining credits across all users
        current_credits = await User.objects.aaggregate(
            total=models.Sum("credit"),
        )
        current_user_credits = current_credits["total"] or 0

        # Calculate how much credit was spent
        total_spent_credits = total_approved_credits - current_user_credits

        # Get total successful charge sales
        charge_sales = await ChargeSale.objects.filter(
            status="APPROVED",
            processed=True,
        ).aaggregate(total=models.Sum("amount"))
        total_charge_sales = charge_sales["total"] or 0

        # Validate that spent credits match charge sales
        is_consistent = (
            abs(total_spent_credits - total_charge_sales) == 0
        )  # this could be compared with a threshold

        details = (
            "All transactions are consistent"
            if is_consistent
            else f"Mismatch: Users spent {total_spent_credits} but charge sales total is {total_charge_sales}"
        )

        return {
            "total_approved_credits": total_approved_credits,
            "current_user_credits": current_user_credits,
            "total_spent_credits": total_spent_credits,
            "total_charge_sales": total_charge_sales,
            "is_consistent": is_consistent,
            "details": details,
        }

    except Exception:
        logger.exception("Error during transaction validation")
        raise


@router.get(
    "/users/{user_id}/validate",
    response={200: UserValidationResultSchema, 404: Error},
)
async def validate_user_transactions(request, user_id: int):
    try:
        user = await User.objects.aget(id=user_id)

        # Get total approved credits (what users received)
        approved_credits = await CreditRequest.objects.filter(
            user=user,
            status="APPROVED",
            processed=True,
        ).aaggregate(total=models.Sum("amount"))
        total_approved_credits = approved_credits["total"] or 0

        total_spent_credits = total_approved_credits - user.credit

        # Get total successful charge sales
        charge_sales = await ChargeSale.objects.filter(
            user=user,
            status="APPROVED",
            processed=True,
        ).aaggregate(total=models.Sum("amount"))

        total_charge_sales = charge_sales["total"] or 0

        # Validate that spent credits match charge sales
        is_consistent = (
            abs(total_spent_credits - total_charge_sales) == 0
        )  # this could be compared with a threshold

        details = (
            "All transactions are consistent"
            if is_consistent
            else f"Mismatch: User spent {total_spent_credits} but charge sales total is {total_charge_sales}"
        )

        return {
            "total_approved_credits": total_approved_credits,
            "current_user_credits": user.credit,
            "total_spent_credits": total_spent_credits,
            "total_charge_sales": total_charge_sales,
            "is_consistent": is_consistent,
            "details": details,
        }

    except User.DoesNotExist:
        logger.error(f"User {user_id} not found")
        return 404, {"detail": "User not found"}
    except Exception:
        logger.exception(f"Error validating user transactions for user ID {user_id}")
        raise
