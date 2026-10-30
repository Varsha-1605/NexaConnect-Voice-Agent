"""Validation for customer and enrollment details. Only fields passed in are checked."""

import re
from datetime import date, timedelta

from config import MAX_INSTALLATION_DAYS_AHEAD
from services.availability import all_plan_names
from utils import business_today

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")


def validate(
    customer_name: str | None = None,
    phone_number: str | None = None,
    email: str | None = None,
    service_address: str | None = None,
    postal_code: str | None = None,
    plan_name: str | None = None,
    preferred_installation_date: str | None = None,
) -> dict:
    """Return {"valid": bool, "errors": {field: message}, "normalized": {field: value}}."""
    errors: dict[str, str] = {}
    normalized: dict[str, str] = {}

    if customer_name is not None:
        name = " ".join(customer_name.split())
        if len(name) < 2 or not re.search(r"[A-Za-z]", name):
            errors["customer_name"] = "Please provide the customer's full name."
        else:
            normalized["customer_name"] = name

    if phone_number is not None:
        digits = re.sub(r"\D", "", phone_number)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) != 10 or digits[0] in "01":
            errors["phone_number"] = "Phone number must be a valid 10-digit US number."
        else:
            normalized["phone_number"] = f"+1{digits}"

    if email:
        value = email.strip().lower()
        if not EMAIL_RE.match(value):
            errors["email"] = "Email address format is not valid."
        else:
            normalized["email"] = value

    if service_address is not None:
        address = " ".join(service_address.split())
        if len(address) < 5:
            errors["service_address"] = "Please provide the full street address."
        else:
            normalized["service_address"] = address

    if postal_code is not None:
        value = postal_code.strip()
        if not ZIP_RE.match(value):
            errors["postal_code"] = "ZIP code must be 5 digits."
        else:
            normalized["postal_code"] = value[:5]

    if plan_name is not None:
        match = {p.lower(): p for p in all_plan_names()}.get(plan_name.strip().lower())
        if not match:
            errors["plan_name"] = f"Plan must be one of: {', '.join(sorted(all_plan_names()))}."
        else:
            normalized["plan_name"] = match

    if preferred_installation_date:
        try:
            chosen = date.fromisoformat(preferred_installation_date.strip())
        except ValueError:
            errors["preferred_installation_date"] = "Date must be in YYYY-MM-DD format."
        else:
            today = business_today()
            if chosen <= today:
                errors["preferred_installation_date"] = "Date must be after today."
            elif chosen > today + timedelta(days=MAX_INSTALLATION_DAYS_AHEAD):
                errors["preferred_installation_date"] = (
                    f"Date must be within {MAX_INSTALLATION_DAYS_AHEAD} days from today."
                )
            else:
                normalized["preferred_installation_date"] = chosen.isoformat()

    return {"valid": not errors, "errors": errors, "normalized": normalized}
