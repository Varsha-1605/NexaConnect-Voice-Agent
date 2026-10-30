import json
import secrets
from datetime import date

from db.pool import get_pool
from services.enrollment_service import REFERENCE_ALPHABET


async def get_bill(enrollment_reference: str) -> dict | None:
    """The account's bill with its line items and payment status, or None if it has none."""
    row = await (await get_pool()).fetchrow(
        """
        SELECT b.period_start, b.period_end, b.due_date, b.total_amount, b.line_items,
               b.payment_status, b.amount_paid, b.paid_on
        FROM bills b JOIN enrollments e ON e.id = b.enrollment_id
        WHERE e.enrollment_reference = $1
        """,
        enrollment_reference,
    )
    if not row:
        return None
    total, paid = float(row["total_amount"]), float(row["amount_paid"])
    return {
        "billing_period": f"{row['period_start'].isoformat()} to {row['period_end'].isoformat()}",
        "due_date": row["due_date"].isoformat(),
        "total_amount": total,
        "charges": json.loads(row["line_items"]),
        "payment_status": row["payment_status"],
        "amount_paid": paid,
        "amount_outstanding": round(total - paid, 2),
        "paid_on": row["paid_on"].isoformat() if row["paid_on"] else None,
    }


async def create_ticket(enrollment_reference: str, billing_issue: str, details: str) -> str:
    """Save a billing support ticket and return its reference."""
    suffix = "".join(secrets.choice(REFERENCE_ALPHABET) for _ in range(6))
    reference = f"TKT-{date.today():%Y%m%d}-{suffix}"
    await (await get_pool()).execute(
        """
        INSERT INTO support_tickets (ticket_reference, enrollment_id, billing_issue, issue_details)
        SELECT $1, id, $3, $4 FROM enrollments WHERE enrollment_reference = $2
        """,
        reference,
        enrollment_reference,
        billing_issue,
        details,
    )
    return reference
