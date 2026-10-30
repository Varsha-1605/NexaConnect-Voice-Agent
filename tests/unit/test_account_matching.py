"""Address matching and the lockout, with the database mocked."""

import pytest

from services import account_service


def rows_for(*stored_addresses):
    return [
        {"enrollment_reference": f"ENR-20261030-AAAA{i}", "service_address": address}
        for i, address in enumerate(stored_addresses)
    ]


@pytest.fixture
def stored(monkeypatch):
    """Set the addresses the 'database' returns for the name/email/phone match."""

    def set_rows(*addresses):
        async def fake_read_rows(query, *args):
            return rows_for(*addresses)

        monkeypatch.setattr(account_service, "read_rows", fake_read_rows)

    return set_rows


async def find(address):
    return await account_service.find_account("Maria Lopez", address, email="m@example.com")


@pytest.mark.parametrize(
    "spoken",
    ["21 Jane Street", "21 jane st", "21 Jane St.", "21 JANE STREET", "21 Jane Street New York", "21 Jane Street, Apt 4"],
)
async def test_same_address_matches(stored, spoken):
    stored("21 Jane Street")
    assert await find(spoken) == "ENR-20261030-AAAA0"


@pytest.mark.parametrize("spoken", ["121 Jane Street", "1 Jane Street", "21 Jane Avenue", "2 Jane Street", "Jane Street"])
async def test_different_address_does_not_match(stored, spoken):
    stored("21 Jane Street")
    assert await find(spoken) is None


async def test_12_main_never_matches_112_main(stored):
    stored("112 Main Street")
    assert await find("12 Main St") is None


async def test_first_matching_account_is_returned(stored):
    stored("5 Oak Road", "21 Jane Street")
    assert await find("21 Jane St") == "ENR-20261030-AAAA1"


async def test_no_accounts(stored):
    stored()
    assert await find("21 Jane Street") is None


def test_address_hash_ignores_spelling_differences():
    assert account_service._address_hash("21 Jane Street") == account_service._address_hash("21 JANE ST.")
    assert account_service._address_hash("21 Jane Street") != account_service._address_hash("22 Jane Street")


async def test_lockout_starts_at_the_limit(monkeypatch):
    async def failures(limit_count):
        async def fake_read_value(query, *args):
            return limit_count

        monkeypatch.setattr(account_service, "read_value", fake_read_value)
        return await account_service.verification_locked("21 Jane Street")

    assert not await failures(account_service.MAX_FAILED_VERIFICATIONS - 1)
    assert await failures(account_service.MAX_FAILED_VERIFICATIONS)
