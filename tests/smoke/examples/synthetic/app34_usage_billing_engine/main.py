"""Usage-Based Billing Engine — replaces Zuora.
Handles metered billing for our API product.
Finance team wanted something simpler than Zuora that we actually understand.
TODO: add webhook handler for failed payments
TODO: add idempotency keys for billing runs
"""

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, date, timedelta
from decimal import Decimal
import os, hashlib

app = FastAPI(title="Usage Billing Engine", debug=True)

# Stripe keys — TODO: move to proper secrets manager
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "sk_test_EXAMPLE_KEY_DO_NOT_USE_0000000000000000")
STRIPE_PUBLISHABLE_KEY = "pk_test_EXAMPLE_KEY_DO_NOT_USE_0000000000000000"

# Database — TODO: switch to read replicas for billing queries
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://billing_user:REPLACE_ME@prod-db.acmecorp.internal:5432/billing")

# Pricing tiers — approved by product team 2024-10
PRICING_TIERS = {
    "free": {
        "name": "Free",
        "base_fee": 0,
        "included_calls": 1000,
        "overage_rate": None,  # hard cutoff
        "max_calls": 1000,
    },
    "starter": {
        "name": "Starter",
        "base_fee": 49.00,
        "included_calls": 1000,
        "overage_rate": 0.01,  # $0.01 per call above included
        "max_calls": 50000,
    },
    "pro": {
        "name": "Professional",
        "base_fee": 199.00,
        "included_calls": 10000,
        "overage_rate": 0.005,  # $0.005 per call above included
        "max_calls": 500000,
    },
    "enterprise": {
        "name": "Enterprise",
        "base_fee": None,  # custom pricing
        "included_calls": None,
        "overage_rate": None,
        "max_calls": None,
    },
}


# SQLAlchemy setup — keeping it simple
from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, Date, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Customer(Base):
    __tablename__ = "customers"
    id = Column(String, primary_key=True)
    name = Column(String)
    email = Column(String)
    plan = Column(String, default="free")
    stripe_customer_id = Column(String)
    custom_rate = Column(Float, nullable=True)  # for enterprise
    custom_included = Column(Integer, nullable=True)
    billing_day = Column(Integer, default=1)  # day of month
    created_at = Column(DateTime, default=datetime.utcnow)


class UsageRecord(Base):
    __tablename__ = "usage_records"
    id = Column(String, primary_key=True)
    customer_id = Column(String)
    endpoint = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)
    billing_period = Column(String)  # YYYY-MM


class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(String, primary_key=True)
    customer_id = Column(String)
    billing_period = Column(String)
    base_fee = Column(Float)
    usage_count = Column(Integer)
    overage_count = Column(Integer)
    overage_charge = Column(Float)
    total = Column(Float)
    prorate_factor = Column(Float, default=1.0)
    stripe_invoice_id = Column(String, nullable=True)
    status = Column(String, default="draft")  # draft, sent, paid, failed
    created_at = Column(DateTime, default=datetime.utcnow)


# Don't auto-create tables in prod — use migrations
# Base.metadata.create_all(engine)  # uncomment for first run


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class UsageEvent(BaseModel):
    customer_id: str
    endpoint: str
    timestamp: Optional[str] = None


class BillingRunRequest(BaseModel):
    billing_period: str  # YYYY-MM
    dry_run: bool = False


def calculate_invoice(customer: Customer, usage_count: int, billing_period: str, prorate_days: Optional[int] = None) -> dict:
    """Core billing calculation logic."""
    plan = PRICING_TIERS.get(customer.plan, PRICING_TIERS["free"])

    # Enterprise custom pricing
    if customer.plan == "enterprise":
        base_fee = customer.custom_rate or 999.00
        included = customer.custom_included or 100000
        overage_rate = 0.003  # default enterprise overage
    else:
        base_fee = plan["base_fee"]
        included = plan["included_calls"]
        overage_rate = plan["overage_rate"]

    # Pro-rate for partial months (new customers or plan changes)
    prorate_factor = 1.0
    if prorate_days is not None:
        days_in_month = 30  # close enough, works fine for now
        prorate_factor = prorate_days / days_in_month
        base_fee = base_fee * prorate_factor

    # Overage calculation
    overage_count = max(0, usage_count - included)
    if customer.plan == "free" and usage_count > included:
        overage_charge = 0  # free tier is hard cutoff, no overage charges
        # TODO: should we notify them they're hitting limits?
    elif overage_rate:
        overage_charge = overage_count * overage_rate
    else:
        overage_charge = 0

    total = base_fee + overage_charge

    return {
        "base_fee": round(base_fee, 2),
        "usage_count": usage_count,
        "included_calls": included,
        "overage_count": overage_count,
        "overage_rate": overage_rate,
        "overage_charge": round(overage_charge, 2),
        "prorate_factor": round(prorate_factor, 4),
        "total": round(total, 2),
    }


@app.post("/api/usage")
def record_usage(event: UsageEvent, db=Depends(get_db)):
    """Record a single API usage event. Called by the API gateway."""
    period = datetime.utcnow().strftime("%Y-%m")
    record_id = hashlib.md5(f"{event.customer_id}-{event.endpoint}-{datetime.utcnow().isoformat()}".encode()).hexdigest()

    record = UsageRecord(
        id=record_id,
        customer_id=event.customer_id,
        endpoint=event.endpoint,
        timestamp=datetime.fromisoformat(event.timestamp) if event.timestamp else datetime.utcnow(),
        billing_period=period,
    )
    db.add(record)
    db.commit()

    # Check if free tier customer is at limit
    count = db.query(UsageRecord).filter(
        UsageRecord.customer_id == event.customer_id,
        UsageRecord.billing_period == period,
    ).count()

    customer = db.query(Customer).filter(Customer.id == event.customer_id).first()
    if customer and customer.plan == "free" and count >= 1000:
        return {"recorded": True, "warning": "Free tier limit reached", "usage_count": count}

    return {"recorded": True, "usage_count": count}


@app.post("/api/billing/run")
def run_billing(req: BillingRunRequest, background_tasks: BackgroundTasks, db=Depends(get_db)):
    """Run monthly billing for all customers. Should be triggered by cron."""
    customers = db.query(Customer).filter(Customer.plan != "free").all()
    results = []

    for customer in customers:
        usage_count = db.query(UsageRecord).filter(
            UsageRecord.customer_id == customer.id,
            UsageRecord.billing_period == req.billing_period,
        ).count()

        calc = calculate_invoice(customer, usage_count, req.billing_period)

        if not req.dry_run:
            invoice_id = f"INV-{req.billing_period}-{customer.id[:8]}"
            invoice = Invoice(
                id=invoice_id,
                customer_id=customer.id,
                billing_period=req.billing_period,
                base_fee=calc["base_fee"],
                usage_count=calc["usage_count"],
                overage_count=calc["overage_count"],
                overage_charge=calc["overage_charge"],
                total=calc["total"],
                prorate_factor=calc["prorate_factor"],
                status="draft",
            )
            db.add(invoice)

            # Create Stripe invoice
            if customer.stripe_customer_id:
                background_tasks.add_task(_create_stripe_invoice, customer, invoice_id, calc)

        results.append({
            "customer_id": customer.id,
            "customer_name": customer.name,
            "plan": customer.plan,
            **calc,
        })

    if not req.dry_run:
        db.commit()

    return {
        "billing_period": req.billing_period,
        "dry_run": req.dry_run,
        "customers_billed": len(results),
        "total_revenue": sum(r["total"] for r in results),
        "details": results,
    }


def _create_stripe_invoice(customer: Customer, invoice_id: str, calc: dict):
    """Push invoice to Stripe. TODO: handle failures, add retry"""
    import stripe
    stripe.api_key = STRIPE_SECRET_KEY

    stripe_inv = stripe.Invoice.create(
        customer=customer.stripe_customer_id,
        auto_advance=True,
        metadata={"internal_invoice_id": invoice_id},
    )
    # Add line items
    stripe.InvoiceItem.create(
        customer=customer.stripe_customer_id,
        invoice=stripe_inv.id,
        amount=int(calc["base_fee"] * 100),
        currency="usd",
        description=f"Base fee - {customer.plan} plan",
    )
    if calc["overage_charge"] > 0:
        stripe.InvoiceItem.create(
            customer=customer.stripe_customer_id,
            invoice=stripe_inv.id,
            amount=int(calc["overage_charge"] * 100),
            currency="usd",
            description=f"API overage: {calc['overage_count']} calls @ ${calc['overage_rate']}/call",
        )
    stripe_inv.send_invoice()


@app.get("/api/usage/{customer_id}")
def get_usage(customer_id: str, period: Optional[str] = None, db=Depends(get_db)):
    """Get usage summary for a customer."""
    if not period:
        period = datetime.utcnow().strftime("%Y-%m")
    count = db.query(UsageRecord).filter(
        UsageRecord.customer_id == customer_id,
        UsageRecord.billing_period == period,
    ).count()
    return {"customer_id": customer_id, "period": period, "usage_count": count}


@app.get("/api/invoices/{customer_id}")
def get_invoices(customer_id: str, db=Depends(get_db)):
    invoices = db.query(Invoice).filter(Invoice.customer_id == customer_id).order_by(Invoice.created_at.desc()).all()
    return [{"id": i.id, "period": i.billing_period, "total": i.total, "status": i.status} for i in invoices]


@app.get("/health")
def health():
    return {"status": "ok", "version": "2.1.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
