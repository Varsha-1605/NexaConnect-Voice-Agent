import json

from db.pool import get_pool, read_row
from services.enrollment_service import new_reference


async def get_bill(enrollment_reference: str) -> dict | None:
    row = await read_row(
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


async def create_ticket(
    enrollment_reference: str, billing_issue: str, details: str, idempotency_key: str
) -> str:
    reference = await (await get_pool()).fetchval(
        """
        INSERT INTO support_tickets
            (ticket_reference, enrollment_id, billing_issue, issue_details, idempotency_key)
        SELECT $1, id, $3, $4, $5 FROM enrollments WHERE enrollment_reference = $2
        ON CONFLICT (idempotency_key) DO UPDATE SET idempotency_key = EXCLUDED.idempotency_key
        RETURNING ticket_reference
        """,
        new_reference("TKT"),
        enrollment_reference,
        billing_issue,
        details,
        idempotency_key,
    )
    if reference is None:
        raise LookupError("account not found")
    return reference
