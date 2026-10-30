"""Cancellation requests, stored in the `cancellations` table in Neon PostgreSQL."""

import calendar
from datetime import date

from db.pool import get_pool, read_row
from services.account_service import CANCELLED_STATUS
from services.enrollment_service import new_reference
from utils import business_today


def effective_date() -> date:
    """Service ends on the last day of the current billing month (billing follows the calendar month)."""
    today = business_today()
    return today.replace(day=calendar.monthrange(today.year, today.month)[1])


async def submit_cancellation(enrollment_reference: str, reason: str) -> tuple[str, date, bool]:
    """Save the request and mark the account as cancelled.

    Returns (cancellation_reference, service_end_date, already_requested). An account that
    already has a request gets that request back instead of a second one.
    """
    async with (await get_pool()).acquire() as conn, conn.transaction():
        enrollment_id = await conn.fetchval(
            "SELECT id FROM enrollments WHERE enrollment_reference = $1 FOR UPDATE",
            enrollment_reference,
        )
        existing = await conn.fetchrow(
            "SELECT cancellation_reference, effective_date FROM cancellations WHERE enrollment_id = $1",
            enrollment_id,
        )
        if existing:
            return existing["cancellation_reference"], existing["effective_date"], True

        reference = new_reference("CAN")
        end_date = effective_date()
        await conn.execute(
            """
            INSERT INTO cancellations (
                cancellation_reference, enrollment_id, cancellation_reason,
                effective_date, consent_given_at
            )
            VALUES ($1, $2, $3, $4, NOW())
            """,
            reference,
            enrollment_id,
            reason,
            end_date,
        )
        await conn.execute(
            "UPDATE enrollments SET enrollment_status = $1 WHERE id = $2",
            CANCELLED_STATUS,
            enrollment_id,
        )
        return reference, end_date, False


async def get_status(enrollment_reference: str) -> dict | None:
    row = await read_row(
        """
        SELECT c.cancellation_reference, c.cancellation_status, c.effective_date, c.created_at
        FROM cancellations c JOIN enrollments e ON e.id = c.enrollment_id
        WHERE e.enrollment_reference = $1
        """,
        enrollment_reference,
    )
    if not row:
        return None
    return {
        "cancellation_reference": row["cancellation_reference"],
        "cancellation_status": row["cancellation_status"],
        "service_ends_on": row["effective_date"].isoformat(),
        "submitted_on": row["created_at"].date().isoformat(),
    }
