"""Enrollment storage in Neon PostgreSQL."""

import asyncio
import logging
import secrets
from datetime import date
from decimal import Decimal

from db.pool import get_pool

logger = logging.getLogger("voice-agent")

# No 0/O or 1/I, so references are easy to read out on a call.
REFERENCE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

# Idempotency key -> reference already given out; the task set keeps running saves alive.
_references: dict[str, str] = {}
_tasks: set[asyncio.Task] = set()


def _new_reference() -> str:
    suffix = "".join(secrets.choice(REFERENCE_ALPHABET) for _ in range(6))
    return f"ENR-{date.today():%Y%m%d}-{suffix}"


async def _save(
    reference: str,
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
) -> None:
    try:
        pool = await get_pool()
        await pool.execute(
            """
            INSERT INTO enrollments (
                enrollment_reference, customer_name, phone_number, email,
                service_address, city, state, postal_code, plan_name,
                monthly_plan_price, router_rental_selected,
                preferred_installation_date, consent_given_at, idempotency_key
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW(), $13)
            ON CONFLICT (idempotency_key) DO NOTHING
            """,
            reference,
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
        logger.info("Enrollment %s saved", reference)
    except Exception as e:
        logger.error("Enrollment %s could not be saved: %s", reference, type(e).__name__)


def submit_enrollment_in_background(*, idempotency_key: str, **fields) -> str:
    """Return the enrollment reference now and insert the row in the background."""
    if idempotency_key in _references:
        return _references[idempotency_key]

    reference = _references[idempotency_key] = _new_reference()
    task = asyncio.create_task(_save(reference, idempotency_key=idempotency_key, **fields))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return reference
