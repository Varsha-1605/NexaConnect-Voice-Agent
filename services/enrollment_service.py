"""Enrollment storage in Neon PostgreSQL."""

import secrets
from datetime import date
from decimal import Decimal

from db.pool import get_pool
from utils import business_today

# No 0/O or 1/I, so references are easy to read out on a call.
REFERENCE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_reference(prefix: str) -> str:
    """e.g. ENR-20261030-TAK9F2. The date is the business date, not the server's UTC date."""
    suffix = "".join(secrets.choice(REFERENCE_ALPHABET) for _ in range(6))
    return f"{prefix}-{business_today():%Y%m%d}-{suffix}"


async def save_enrollment(
    *,
    idempotency_key: str,
    customer_name: str,
    phone_number: str,
    email: str | None,
    service_address: str,
    city: str,
    state: str,
    postal_code: str,
    plan_name: str,
    monthly_plan_price: float,
    router_rental_selected: bool,
    preferred_installation_date: str | None,
) -> str:
    """Save the enrollment and return its reference. Raises if the save fails.

    A repeat call with the same idempotency key saves nothing new and returns the first reference.
    """
    pool = await get_pool()
    return await pool.fetchval(
        """
        INSERT INTO enrollments (
            enrollment_reference, customer_name, phone_number, email,
            service_address, city, state, postal_code, plan_name,
            monthly_plan_price, router_rental_selected,
            preferred_installation_date, consent_given_at, idempotency_key
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW(), $13)
        ON CONFLICT (idempotency_key)
            DO UPDATE SET idempotency_key = EXCLUDED.idempotency_key
        RETURNING enrollment_reference
        """,
        new_reference("ENR"),
        customer_name,
        phone_number,
        email,
        service_address,
        city,
        state,
        postal_code,
        plan_name,
        Decimal(str(monthly_plan_price)),
        router_rental_selected,
        date.fromisoformat(preferred_installation_date) if preferred_installation_date else None,
        idempotency_key,
    )
