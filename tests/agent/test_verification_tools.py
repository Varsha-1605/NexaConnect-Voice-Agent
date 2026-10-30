"""Customer verification: no account data before it, 3 tries per call, lockout across calls."""

import pytest
from livekit.agents import ToolError

from config import MAX_VERIFICATION_ATTEMPTS
from workflows import shared_tools

WHO = dict(customer_name="Maria Lopez", service_address="21 Jane Street", email="maria@example.com")


@pytest.fixture
def accounts(monkeypatch):
    """Fake account lookups. `match` is the reference found (None = no match)."""

    class Accounts:
        match = None
        locked = False
        lookups = 0
        failures = []

    state = Accounts()

    async def find_account(name, address, email=None, phone_number=None):
        state.lookups += 1
        return state.match

    async def verification_locked(address):
        return state.locked

    async def record_failed_verification(address):
        state.failures.append(address)

    monkeypatch.setattr(shared_tools.account_service, "find_account", find_account)
    monkeypatch.setattr(shared_tools.account_service, "verification_locked", verification_locked)
    monkeypatch.setattr(shared_tools.account_service, "record_failed_verification", record_failed_verification)
    return state


async def test_account_details_need_verification_first(context):
    with pytest.raises(ToolError, match="not verified"):
        await shared_tools.get_account_details(context)


async def test_matching_details_verify_the_customer(context, accounts):
    accounts.match = "ENR-20261030-ABC234"
    assert "verified" in await shared_tools.verify_customer(context, **WHO)
    assert context.userdata.customer_verified
    assert context.userdata.enrollment_reference == "ENR-20261030-ABC234"


async def test_wrong_details_do_not_verify_and_do_not_say_what_was_wrong(context, accounts):
    with pytest.raises(ToolError, match="Do not say which detail was wrong"):
        await shared_tools.verify_customer(context, **WHO)
    assert not context.userdata.customer_verified
    assert accounts.failures == ["21 Jane Street"]


async def test_three_wrong_tries_end_verification(context, accounts):
    for attempt in range(1, MAX_VERIFICATION_ATTEMPTS + 1):
        with pytest.raises(ToolError) as error:
            await shared_tools.verify_customer(context, **WHO)
    assert "escalate" in str(error.value)
    assert context.userdata.verification_attempts == MAX_VERIFICATION_ATTEMPTS


async def test_after_the_last_try_nothing_is_looked_up(context, accounts):
    context.userdata.verification_attempts = MAX_VERIFICATION_ATTEMPTS
    with pytest.raises(ToolError, match="escalate"):
        await shared_tools.verify_customer(context, **WHO)
    assert accounts.lookups == 0


async def test_an_address_locked_by_earlier_calls_is_refused(context, accounts):
    accounts.locked = True
    accounts.match = "ENR-20261030-ABC234"  # even correct details are refused
    with pytest.raises(ToolError, match="escalate"):
        await shared_tools.verify_customer(context, **WHO)
    assert not context.userdata.customer_verified and accounts.lookups == 0


async def test_email_or_phone_is_required(context, accounts):
    with pytest.raises(ToolError, match="email address or phone number"):
        await shared_tools.verify_customer(context, customer_name="Maria Lopez", service_address="21 Jane Street")
    assert accounts.lookups == 0
