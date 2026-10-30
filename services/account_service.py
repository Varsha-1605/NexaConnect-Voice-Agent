import hashlib
import re

from db.pool import get_pool, read_row, read_rows, read_value
from config import LOCKOUT_HOURS, MAX_FAILED_VERIFICATIONS
from services import availability, validation

CANCELLED_STATUS = "cancellation_requested"

# The only columns `update_account` may write; keys of `changes` are checked against it.
UPDATABLE_COLUMNS = {
    "customer_name", "phone_number", "email", "service_address", "city", "state",
    "postal_code", "plan_name", "monthly_plan_price",
}

# Spoken and stored addresses differ in suffixes ("Street" vs "St"), so both are shortened.
_ADDRESS_WORDS = {
    "street": "st", "avenue": "ave", "road": "rd", "drive": "dr", "boulevard": "blvd",
    "lane": "ln", "court": "ct", "apartment": "apt", "suite": "ste",
    "north": "n", "south": "s", "east": "e", "west": "w",
}


def _normalize_address(text: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", text.lower()).split()
    return " ".join(_ADDRESS_WORDS.get(w, w) for w in words)


async def find_account(
    customer_name: str,
    service_address: str,
    email: str | None = None,
    phone_number: str | None = None,
) -> str | None:
    """Return the enrollment reference matching the name, address and (email or phone), else None.

    Prefers an account that is not already cancelled.
    """
    phone = validation.validate(phone_number=phone_number)["normalized"].get("phone_number")
    rows = await read_rows(
        """
        SELECT enrollment_reference, service_address
        FROM enrollments
        WHERE lower(customer_name) = lower($1) AND (lower(email) = lower($2) OR phone_number = $3)
        ORDER BY (enrollment_status = $4), created_at DESC
        """,
        " ".join(customer_name.split()),
        email.strip() if email else None,
        phone,
        CANCELLED_STATUS,
    )
    spoken = _normalize_address(service_address)
    for row in rows:
        stored = _normalize_address(row["service_address"])
        # Exact match. The caller may add the city after the street ("21 jane st new york"),
        # but "12 main st" must never match "112 main st".
        if spoken == stored or spoken.startswith(stored + " "):
            return row["enrollment_reference"]
    return None


def _address_hash(service_address: str) -> str:
    """Failed attempts are stored by hash, so no raw address is kept for them."""
    return hashlib.sha256(_normalize_address(service_address).encode()).hexdigest()


async def verification_locked(service_address: str) -> bool:
    """True if this address had too many failed verifications in the last LOCKOUT_HOURS."""
    failures = await read_value(
        """
        SELECT count(*) FROM verification_failures
        WHERE address_hash = $1 AND failed_at > NOW() - make_interval(hours => $2)
        """,
        _address_hash(service_address),
        LOCKOUT_HOURS,
    )
    return failures >= MAX_FAILED_VERIFICATIONS


async def record_failed_verification(service_address: str) -> None:
    await (await get_pool()).execute(
        "INSERT INTO verification_failures (address_hash) VALUES ($1)",
        _address_hash(service_address),
    )


async def get_account(enrollment_reference: str) -> dict:
    row = await read_row(
        """
        SELECT plan_name, monthly_plan_price, router_rental_selected, city, state,
               enrollment_status, created_at
        FROM enrollments WHERE enrollment_reference = $1
        """,
        enrollment_reference,
    )
    return {
        "plan_name": row["plan_name"],
        "monthly_plan_price": float(row["monthly_plan_price"]),
        "router_rental_selected": row["router_rental_selected"],
        "city": row["city"],
        "state": row["state"],
        "status": row["enrollment_status"],
        "enrolled_on": row["created_at"].date().isoformat(),
    }


def _invalid(**errors: str) -> dict:
    return {"valid": False, "errors": errors, "changes": {}}


def _valid(changes: dict) -> dict:
    return {"valid": True, "errors": {}, "changes": changes}


def _plan_change(account: dict, new_value: str) -> dict:
    result = validation.validate(plan_name=new_value)
    if not result["valid"]:
        return _invalid(**result["errors"])
    plan = result["normalized"]["plan_name"]
    available = availability.check_availability(account["city"], account["state"]).get("plans", [])
    if plan not in available:
        return _invalid(
            plan_name=f"{plan} is not available in {account['city']}. Available: {', '.join(available)}."
        )
    if plan == account["plan_name"]:
        return _invalid(plan_name=f"The customer is already on {plan}.")
    return _valid({"plan_name": plan, "monthly_plan_price": availability.plan_prices()[plan]})


def _address_change(
    account: dict, new_value: str, city: str | None, state: str | None, postal_code: str | None
) -> dict:
    result = validation.validate(service_address=new_value, postal_code=postal_code or "")
    errors = dict(result["errors"])
    if not (city and state):
        errors["city"] = "City and state are needed with a new address."
    if errors:
        return _invalid(**errors)

    area = availability.check_availability(city, state)
    if not area["available"]:
        return _invalid(
            service_address="NexaConnect does not serve that city. "
            f"Served cities: {', '.join(area['served_cities'])}."
        )
    if account["plan_name"] not in area["plans"]:
        return _invalid(
            service_address=f"{account['plan_name']} is not available in {area['city']}. "
            f"Available: {', '.join(area['plans'])}."
        )
    return _valid({**result["normalized"], "city": area["city"], "state": area["state"]})


def validate_change(
    account: dict,
    field: str,
    new_value: str,
    city: str | None = None,
    state: str | None = None,
    postal_code: str | None = None,
) -> dict:
    """Check one requested change against the account. Returns {valid, errors, changes}.

    `changes` holds the column values that `update_account` would write.
    """
    if account["status"] == CANCELLED_STATUS:
        return _invalid(**{field: "This account has a cancellation request, so it can't be changed."})
    if field == "plan_name":
        return _plan_change(account, new_value)
    if field == "service_address":
        return _address_change(account, new_value, city, state, postal_code)

    result = validation.validate(**{field: new_value})
    if not result["valid"] or field not in result["normalized"]:
        return _invalid(**{field: result["errors"].get(field, "No value was given.")})
    return _valid(result["normalized"])


def _describe(field: str, values) -> str:
    if field == "service_address":
        return f"{values['service_address']}, {values['city']}, {values['state']} {values['postal_code']}"
    return str(values[field])


async def update_account(enrollment_reference: str, field: str, changes: dict) -> None:
    """Save the validated `changes` for one field and record the change, in one transaction."""
    if not changes or not set(changes) <= UPDATABLE_COLUMNS:
        raise ValueError("unsupported columns")
    assignments = ", ".join(f"{column} = ${i}" for i, column in enumerate(changes, start=2))

    async with (await get_pool()).acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            "SELECT * FROM enrollments WHERE enrollment_reference = $1 FOR UPDATE",
            enrollment_reference,
        )
        if row["enrollment_status"] == CANCELLED_STATUS:
            raise ValueError("account has a cancellation request")
        await conn.execute(
            f"UPDATE enrollments SET {assignments} WHERE id = $1", row["id"], *changes.values()
        )
        await conn.execute(
            """
            INSERT INTO account_changes (enrollment_id, field_name, old_value, new_value, consent_given_at)
            VALUES ($1, $2, $3, $4, NOW())
            """,
            row["id"],
            field,
            _describe(field, row),
            _describe(field, changes),
        )
