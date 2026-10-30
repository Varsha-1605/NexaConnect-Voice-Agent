import asyncio
import json
import re
import sys
from datetime import timedelta

from dotenv import load_dotenv

from db.pool import close_pool, get_pool
from services import availability
from utils import business_today

SCENARIOS = ("normal", "high", "unpaid", "pending")


def faq_router_rental() -> float:
    with open(availability.FAQ_PATH, encoding="utf-8") as f:
        return float(re.search(r"Router rental is optional and costs \$(\d+(?:\.\d+)?)", f.read()).group(1))


def faq_installation_fee(plan_name: str) -> float:
    with open(availability.FAQ_PATH, encoding="utf-8") as f:
        match = re.search(
            rf"### Q: How much does {re.escape(plan_name)} cost per month\?.*?"
            r"[Ii]nstallation is listed at \$(\d+(?:\.\d+)?)",
            f.read(),
            re.DOTALL,
        )
    return float(match.group(1))


async def main(reference: str, scenario: str) -> None:
    load_dotenv()
    pool = await get_pool()
    account = await pool.fetchrow(
        "SELECT id, plan_name, router_rental_selected "
        "FROM enrollments WHERE enrollment_reference = $1",
        reference,
    )
    if not account:
        raise SystemExit(f"No enrollment {reference}")

    plan = account["plan_name"]
    items = [{"description": f"{plan} plan", "amount": availability.plan_prices()[plan]}]
    if account["router_rental_selected"]:
        items.append({"description": "Router rental", "amount": faq_router_rental()})
    # no taxes or fees in the FAQ; `high` adds installation
    if scenario == "high" and faq_installation_fee(plan) > 0:
        items.append({"description": "Technician installation fee", "amount": faq_installation_fee(plan)})
    total = round(sum(i["amount"] for i in items), 2)

    today = business_today()
    period_end = today.replace(day=1) - timedelta(days=1)
    received = scenario in ("normal", "high")
    status = "received" if received else "outstanding" if scenario == "unpaid" else "pending"
    await pool.execute(
        """
        INSERT INTO bills (enrollment_id, period_start, period_end, due_date, total_amount,
                           line_items, payment_status, amount_paid, paid_on)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9)
        ON CONFLICT (enrollment_id) DO UPDATE SET
            period_start = $2, period_end = $3, due_date = $4, total_amount = $5,
            line_items = $6::jsonb, payment_status = $7, amount_paid = $8, paid_on = $9
        """,
        account["id"],
        period_end.replace(day=1),
        period_end,
        today - timedelta(days=5) if scenario == "unpaid" else today + timedelta(days=10),
        total,
        json.dumps(items),
        status,
        total if received else 0,
        today - timedelta(days=2) if received else None,
    )
    print(f"{scenario} bill for {reference}: ${total}, payment {status}")
    await close_pool()


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[2] not in SCENARIOS:
        raise SystemExit(__doc__)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
