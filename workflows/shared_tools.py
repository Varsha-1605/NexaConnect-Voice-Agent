"""Tools used by more than one agent or workflow."""

import asyncio
import random
import time
from datetime import date

from livekit.agents import RunContext, ToolError, function_tool

from config import FILLER_DELAY, MAX_VERIFICATION_ATTEMPTS
from services import account_service, availability, knowledge_base, validation
from utils import spoken_date

from .workflow_task import CallState

# Spoken while a search runs, so the customer isn't left in silence.
SEARCH_ACKNOWLEDGEMENTS = [
    "Let me check that for you.",
    "Sure, one moment while I look that up.",
    "Good question, let me find that for you.",
]

VERIFICATION_LOCKED = (
    "Verification failed too many times. Do not try again; tell the customer kindly "
    "and finish the workflow with `escalate`."
)


async def run_with_filler(context: RunContext[CallState], line: str, work):
    """Await `work`, speaking `line` only if it is still running after FILLER_DELAY.

    Fast lookups stay silent. Lookups started together share one line.
    """
    task = asyncio.ensure_future(work)
    try:
        done, _ = await asyncio.wait({task}, timeout=FILLER_DELAY)
        state = context.userdata
        if not done and time.monotonic() - state.last_filler_at > 2:
            state.last_filler_at = time.monotonic()
            context.session.say(line)
        return await task
    except asyncio.CancelledError:
        task.cancel()
        raise


def verified_reference(context: RunContext[CallState]) -> str:
    """The verified customer's account, or a ToolError if they haven't been verified."""
    if not context.userdata.customer_verified:
        raise ToolError("The customer is not verified yet. Call `verify_customer` first.")
    return context.userdata.enrollment_reference


@function_tool()
async def verify_customer(
    context: RunContext[CallState],
    customer_name: str,
    service_address: str,
    email: str | None = None,
    phone_number: str | None = None,
) -> str:
    """Verify the caller's identity. Call before reading or changing account data.
    Needs the name, the service address, and the email address or phone number on the account.

    Args:
        customer_name: Customer's full name.
        service_address: Street address of the service.
        email: Email address on the account.
        phone_number: Phone number on the account, if they have no email on file.
    """
    state = context.userdata
    if state.verification_attempts >= MAX_VERIFICATION_ATTEMPTS:
        raise ToolError(VERIFICATION_LOCKED)
    if not (email or phone_number):
        raise ToolError("Ask the customer for the email address or phone number on the account.")

    async def look_up() -> str | None:
        if await account_service.verification_locked(service_address):
            raise ToolError(VERIFICATION_LOCKED)
        return await account_service.find_account(customer_name, service_address, email, phone_number)

    reference = await run_with_filler(
        context, "Thank you. One moment while I look up your account.", look_up()
    )
    if not reference:
        await account_service.record_failed_verification(service_address)
        state.verification_attempts += 1
        if state.verification_attempts >= MAX_VERIFICATION_ATTEMPTS:
            raise ToolError(f"The details did not match our records. {VERIFICATION_LOCKED}")
        raise ToolError(
            "The details did not match our records. Do not say which detail was wrong. "
            "Ask the customer to try again."
        )

    state.customer_verified = True
    state.enrollment_reference = reference
    return "The customer is verified."


@function_tool()
async def get_account_details(context: RunContext[CallState]) -> dict:
    """Retrieve the verified customer's account details: plan, monthly price,
    router rental, city, status, and `available_plans` offered in their city."""
    account = await account_service.get_account(verified_reference(context))
    area = availability.check_availability(account["city"], account["state"])
    return {**account, "available_plans": area.get("plans", [])}


@function_tool()
async def validate_customer_details(
    context: RunContext[CallState],
    customer_name: str | None = None,
    phone_number: str | None = None,
    email: str | None = None,
    service_address: str | None = None,
    postal_code: str | None = None,
    plan_name: str | None = None,
    preferred_installation_date: str | None = None,
) -> dict:
    """Validate customer details. Pass only the fields being checked.
    "Let me check those details" is spoken automatically: say nothing before calling this.
    Returns `valid`, per-field `errors` to resolve with the customer, `normalized` values and,
    for an installation date, `installation_date_spoken` (the weekday and date to say aloud).

    Args:
        customer_name: Customer's full name.
        phone_number: US phone number.
        email: Email address.
        service_address: Street address.
        postal_code: 5-digit ZIP code.
        plan_name: Selected plan name, e.g. "Home 500".
        preferred_installation_date: Preferred installation date as YYYY-MM-DD.
    """
    context.session.say("Let me check those details.")
    result = validation.validate(
        customer_name=customer_name,
        phone_number=phone_number,
        email=email,
        service_address=service_address,
        postal_code=postal_code,
        plan_name=plan_name,
        preferred_installation_date=preferred_installation_date,
    )
    if chosen := result["normalized"].get("preferred_installation_date"):
        result["installation_date_spoken"] = spoken_date(date.fromisoformat(chosen))
    return result

@function_tool()
async def search_knowledge_base(context: RunContext[CallState], query: str) -> list[dict] | str:
    """Search NexaConnect's knowledge base for plan, price, fee, installation,
    router, data, contract or service area information. Use it whenever the
    customer asks about these topics, and answer only from the results.

    Args:
        query: The customer's question, rephrased as a short search query.
    """
    # The waiting line is only spoken if the search takes longer than FILLER_DELAY.
    return await run_with_filler(
        context, random.choice(SEARCH_ACKNOWLEDGEMENTS), knowledge_base.search_or_unavailable(query)
    )
