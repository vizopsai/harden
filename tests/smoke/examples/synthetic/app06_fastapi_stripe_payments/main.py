"""
FastAPI + Stripe Payments Integration
Simple checkout and webhook handling
"""
from fastapi import FastAPI, HTTPException, Request, Header
from pydantic import BaseModel
import stripe
import os
from typing import Optional

app = FastAPI(title="Stripe Payments API")

# Load Stripe API keys from environment
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")


class CheckoutRequest(BaseModel):
    amount: int  # in cents
    currency: str = "usd"
    product_name: str
    success_url: str
    cancel_url: str


class PaymentIntentRequest(BaseModel):
    amount: int
    currency: str = "usd"
    description: Optional[str] = None


@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "Stripe Payments API",
        "stripe_configured": bool(stripe.api_key)
    }


@app.post("/create-checkout")
async def create_checkout_session(request: CheckoutRequest):
    """
    Create a Stripe Checkout Session
    """
    try:
        # works fine for now, basic checkout flow
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[
                {
                    'price_data': {
                        'currency': request.currency,
                        'product_data': {
                            'name': request.product_name,
                        },
                        'unit_amount': request.amount,
                    },
                    'quantity': 1,
                }
            ],
            mode='payment',
            success_url=request.success_url,
            cancel_url=request.cancel_url,
        )

        return {
            "session_id": session.id,
            "url": session.url
        }

    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # TODO: add proper error logging
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/create-payment-intent")
async def create_payment_intent(request: PaymentIntentRequest):
    """
    Create a Payment Intent for custom payment flow
    """
    try:
        intent = stripe.PaymentIntent.create(
            amount=request.amount,
            currency=request.currency,
            description=request.description,
            automatic_payment_methods={
                'enabled': True,
            },
        )

        return {
            "client_secret": intent.client_secret,
            "payment_intent_id": intent.id
        }

    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    """
    Handle Stripe webhook events
    TODO: add proper event processing and storage
    """
    payload = await request.body()

    try:
        # Verify webhook signature
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, STRIPE_WEBHOOK_SECRET
        )

        # Handle the event
        if event['type'] == 'payment_intent.succeeded':
            payment_intent = event['data']['object']
            print(f"Payment succeeded: {payment_intent['id']}")
            # TODO: fulfill the order here

        elif event['type'] == 'payment_intent.payment_failed':
            payment_intent = event['data']['object']
            print(f"Payment failed: {payment_intent['id']}")
            # TODO: notify customer

        elif event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            print(f"Checkout completed: {session['id']}")
            # TODO: process the order

        else:
            print(f"Unhandled event type: {event['type']}")

        return {"status": "success"}

    except ValueError as e:
        # Invalid payload
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        raise HTTPException(status_code=400, detail="Invalid signature")


@app.get("/health")
def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    # works fine for now
    uvicorn.run(app, host="0.0.0.0", port=8000)
