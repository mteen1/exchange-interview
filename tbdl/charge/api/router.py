import logging
from datetime import datetime
from ninja.security import HttpBearer
from django.contrib.auth.models import AnonymousUser

from asgiref.sync import sync_to_async
from django.contrib.auth import get_user
from django.db import transaction
from django.db.models import F
from ninja import Router
from ninja import Schema
from pydantic import Field

from tbdl.charge.models import ChargeSale
from tbdl.charge.models import CreditRequest
from tbdl.charge.models import PhoneNumber
from tbdl.users.models import User

logger = logging.getLogger(__name__)

class AuthBearer(HttpBearer):
    async def authenticate(self, request, token):
        from rest_framework.authtoken.models import Token
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
    credit_request = CreditRequest.objects.get(id=request_id)
    if credit_request.processed:
        logger.warning(f"Credit request {request_id} was already processed")
        return {"detail": "Already processed"}

    try:
        with transaction.atomic():
            credit_request.status = "APPROVED"
            credit_request.processed = True
            credit_request.save()
            # You could test this by raising an exception here
            request.auth.credit += credit_request.amount
            request.auth.save()
            logger.info(
                f"Successfully approved credit request {request_id} for user {request.auth.id}",
            )
    except Exception as e:
        logger.exception(f"Error processing credit request {request_id}: {e!s}")
        raise

    return credit_request


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

    if request.auth.credit < data.amount:
        logger.warning(
            f"Insufficient credit for user {request.auth.id}. Required: {data.amount}, Available: {request.auth.credit}",
        )
        return {"detail": "Insufficient credit"}

    try:
        with transaction.atomic():
            # Perform updates on user credit and phone number in a single atomic transaction
            # This avoids race conditions, it directly updates the database without loading to memory
            # Select for update locks the row until the transaction is committed
            User.objects.filter(id=request.auth.id).select_for_update().update(
                credit=F("credit") - data.amount,
            )
            # You could test this by raising an exception
            PhoneNumber.objects.filter(
                id=data.phone_number_id
            ).select_for_update().update(
                current_charge=F("current_charge") + data.amount,
            )
            # Create charge sale in a single query
            charge_sale = ChargeSale.objects.create(
                user=request.auth,
                phone_number_id=data.phone_number_id,
                amount=data.amount,
                processed=True,
                status="APPROVED",
            )
            logger.info(f"Successfully created charge sale for user {request.auth.id}")
    except Exception as e:
        logger.exception(f"Error creating charge sale: {e}")
        raise

    return charge_sale


@router.post("/charge-sales", response=ChargeSaleSchema)
async def create_charge_sale(request, data: ChargeSaleCreateSchema):
    return await sync_to_async(create_charge)(request, data)
