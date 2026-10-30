import asyncio

import asyncpg
import pytest

from config import MAX_FAILED_VERIFICATIONS
from db.pool import get_pool
from services import account_service, billing_service, cancellation_service, enrollment_service

CUSTOMER = dict(
    customer_name="Maria Lopez",
    phone_number="+17974517506",
    email="maria@example.com",
    service_address="21 Jane Street",
    city="Austin",
    state="TX",
    postal_code="78701",
    plan_name="Home 500",
    monthly_plan_price=55.0,
    router_rental_selected=True,
    preferred_installation_date=None,
)


async def enroll(key="call-1:+17974517506", **changes) -> str:
    return await enrollment_service.save_enrollment(idempotency_key=key, **{**CUSTOMER, **changes})


async def count(table: str) -> int:
    return await (await get_pool()).fetchval(f"SELECT count(*) FROM {table}")


# enrollments
async def test_enrollment_is_saved():
    reference = await enroll()
    row = await (await get_pool()).fetchrow("SELECT * FROM enrollments WHERE enrollment_reference = $1", reference)
    assert row["customer_name"] == "Maria Lopez" and row["plan_name"] == "Home 500"
    assert float(row["monthly_plan_price"]) == 55.0 and row["enrollment_status"] == "submitted"


async def test_same_key_saves_once_and_returns_the_first_reference():
    first, second = await enroll(), await enroll()
    assert first == second and await count("enrollments") == 1


async def test_five_saves_at_the_same_moment_make_one_enrollment():
    references = await asyncio.gather(*[enroll() for _ in range(5)])
    assert len(set(references)) == 1 and await count("enrollments") == 1


async def test_different_keys_make_different_enrollments():
    first = await enroll("call-1:+17974517506")
    second = await enroll("call-2:+17974517506")
    assert first != second and await count("enrollments") == 2


# finding an account
async def test_account_is_found_by_name_address_and_email():
    reference = await enroll()
    assert await account_service.find_account("Maria Lopez", "21 Jane Street", email="maria@example.com") == reference


async def test_account_is_found_by_phone_ignoring_case_and_street_spelling():
    reference = await enroll()
    found = await account_service.find_account("MARIA LOPEZ", "21 jane st", phone_number="(797) 451-7506")
    assert found == reference


@pytest.mark.parametrize("address", ["121 Jane Street", "1 Jane Street", "21 Jane Avenue", "Jane Street"])
async def test_a_similar_address_is_not_a_match(address):
    await enroll()
    assert await account_service.find_account("Maria Lopez", address, email="maria@example.com") is None


async def test_wrong_name_email_or_phone_is_not_a_match():
    await enroll()
    assert await account_service.find_account("Maria Lopes", "21 Jane Street", email="maria@example.com") is None
    assert await account_service.find_account("Maria Lopez", "21 Jane Street", email="other@example.com") is None
    assert await account_service.find_account("Maria Lopez", "21 Jane Street", phone_number="7974510000") is None


async def test_a_cancelled_account_is_found_after_an_active_one_with_the_same_details():
    old = await enroll("call-1:x")
    await cancellation_service.submit_cancellation(old, "moving")
    new = await enroll("call-2:x")
    assert await account_service.find_account("Maria Lopez", "21 Jane Street", email="maria@example.com") == new


# lockout
async def test_address_locks_at_the_limit_and_only_that_address():
    address = "21 Jane Street"
    for _ in range(MAX_FAILED_VERIFICATIONS - 1):
        await account_service.record_failed_verification(address)
    assert not await account_service.verification_locked(address)
    await account_service.record_failed_verification("21 JANE ST.")  # same address, spoken differently
    assert await account_service.verification_locked(address)
    assert not await account_service.verification_locked("22 Jane Street")


async def test_old_failures_do_not_count():
    pool = await get_pool()
    address = "21 Jane Street"
    for _ in range(MAX_FAILED_VERIFICATIONS):
        await account_service.record_failed_verification(address)
    await pool.execute("UPDATE verification_failures SET failed_at = NOW() - interval '25 hours'")
    assert not await account_service.verification_locked(address)


async def test_no_raw_address_is_stored_for_failures():
    await account_service.record_failed_verification("21 Jane Street")
    row = await (await get_pool()).fetchrow("SELECT * FROM verification_failures")
    assert "jane" not in str(dict(row)).lower()


# tickets
async def test_ticket_is_saved_once_per_key():
    reference = await enroll()
    first = await billing_service.create_ticket(reference, "high bill", "details", "call-1:" + reference)
    second = await billing_service.create_ticket(reference, "high bill", "details", "call-1:" + reference)
    assert first == second and await count("support_tickets") == 1


async def test_two_tickets_in_one_call_with_different_keys():
    reference = await enroll()
    first = await billing_service.create_ticket(reference, "high bill", "a", "call-1:a")
    second = await billing_service.create_ticket(reference, "double charge", "b", "call-1:b")
    assert first != second and await count("support_tickets") == 2


async def test_ticket_for_an_unknown_account_is_an_error():
    with pytest.raises(LookupError):
        await billing_service.create_ticket("ENR-20000101-NOPE22", "x", "y", "call-1:z")
    assert await count("support_tickets") == 0


async def test_new_account_has_no_bill():
    assert await billing_service.get_bill(await enroll()) is None


# cancellations
async def test_cancelling_twice_returns_the_first_reference():
    reference = await enroll()
    first = await cancellation_service.submit_cancellation(reference, "moving")
    second = await cancellation_service.submit_cancellation(reference, "price")
    assert first[2] is False and second[2] is True
    assert first[0] == second[0] and first[1] == second[1]
    assert await count("cancellations") == 1


async def test_two_cancellations_at_the_same_moment_make_one():
    reference = await enroll()
    results = await asyncio.gather(*[cancellation_service.submit_cancellation(reference, "moving") for _ in range(3)])
    assert len({r[0] for r in results}) == 1 and await count("cancellations") == 1


async def test_cancelling_marks_the_account_and_sets_the_service_end_date():
    reference = await enroll()
    _, end_date, _ = await cancellation_service.submit_cancellation(reference, "moving")
    assert (await account_service.get_account(reference))["status"] == account_service.CANCELLED_STATUS
    assert end_date == cancellation_service.effective_date()
    status = await cancellation_service.get_status(reference)
    assert status["service_ends_on"] == end_date.isoformat()


# account changes
async def test_account_update_changes_the_account_and_writes_an_audit_row():
    reference = await enroll()
    await account_service.update_account(reference, "email", {"email": "new@example.com"})
    pool = await get_pool()
    assert await pool.fetchval("SELECT email FROM enrollments WHERE enrollment_reference = $1", reference) == "new@example.com"
    audit = await pool.fetchrow("SELECT * FROM account_changes")
    assert (audit["field_name"], audit["old_value"], audit["new_value"]) == ("email", "maria@example.com", "new@example.com")


async def test_plan_change_updates_the_price():
    reference = await enroll()
    account = await account_service.get_account(reference)
    change = account_service.validate_change(account, "plan_name", "Home Gigabit")
    assert change["valid"]
    await account_service.update_account(reference, "plan_name", change["changes"])
    updated = await account_service.get_account(reference)
    assert updated["plan_name"] == "Home Gigabit" and updated["monthly_plan_price"] == 75.0


async def test_a_cancelled_account_cannot_be_changed():
    reference = await enroll()
    await cancellation_service.submit_cancellation(reference, "moving")
    with pytest.raises(ValueError):
        await account_service.update_account(reference, "email", {"email": "new@example.com"})
    assert await count("account_changes") == 0


async def test_only_known_columns_can_be_written():
    reference = await enroll()
    with pytest.raises(ValueError):
        await account_service.update_account(reference, "enrollment_status", {"enrollment_status": "free"})


# the database itself
async def test_every_table_and_index_the_agent_needs_exists():
    pool = await get_pool()
    tables = {r["table_name"] for r in await pool.fetch("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")}
    assert {"enrollments", "cancellations", "account_changes", "bills", "support_tickets", "verification_failures"} <= tables
    indexes = {r["indexname"] for r in await pool.fetch("SELECT indexname FROM pg_indexes WHERE schemaname='public'")}
    assert {"enrollments_name_lower", "enrollments_email_lower", "enrollments_phone", "verification_failures_lookup"} <= indexes


async def test_the_pool_stays_within_two_connections():
    pool = await get_pool()
    assert pool.get_max_size() == 2


async def test_app_user_cannot_delete_or_change_tables():
    pool = await get_pool()
    assert await pool.fetchval("SELECT current_user") == "app_user"
    await enroll()
    for statement in (
        "DELETE FROM enrollments",
        "TRUNCATE enrollments",
        "DROP TABLE enrollments",
        "ALTER TABLE enrollments ADD COLUMN x int",
        "CREATE TABLE sneaky (id int)",
    ):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await pool.execute(statement)
    assert await count("enrollments") == 1
