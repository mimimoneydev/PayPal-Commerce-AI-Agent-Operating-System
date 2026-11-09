"""Mount only behind the application's authenticated merchant dependency."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from commerce_common.payments import PaymentError


class SellerConsent(BaseModel):
    data_sharing_consent: bool


def build_onboarding_router(partners, authenticated_merchant):
    """authenticated_merchant must return the current authorized merchant's internal id.
    Neither a query parameter nor a body field can choose the target merchant.
    """
    router = APIRouter(prefix="/api/merchant/paypal", tags=["seller onboarding"])
    merchant_dependency = Depends(authenticated_merchant)

    @router.post("/connect")
    async def connect(consent: SellerConsent, merchant_id=merchant_dependency):
        try:
            return {
                "url": await partners.start(
                    merchant_id, data_sharing_consent=consent.data_sharing_consent
                )
            }
        except PaymentError:
            raise HTTPException(409, "PayPal onboarding could not be started") from None

    @router.get("/status")
    async def status(merchant_id=merchant_dependency):
        try:
            config = await partners.seller_config(merchant_id)
            return {"connected": True, "seller_id": config.seller_merchant_id}
        except PaymentError:
            return {"connected": False}

    return router
