from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

import utils


# ---------------------------------------------------------------- masking personal details
@pytest.mark.parametrize(
    "text, expected",
    [
        ("mail maria@example.com now", "mail m***@example.com now"),
        ("call +1 (555) 123-4567", "call *******4567"),
        ("call 5551234567", "call ******4567"),
        ("ZIP 78701 and $55 per month", "ZIP 78701 and $55 per month"),
        ("date 2026-11-08", "date 2026-11-08"),
        ("reference ENR-20261030-U63CHY", "reference ENR-20261030-U63CHY"),
        ("nothing to hide", "nothing to hide"),
    ],
)
def test_mask_personal_details(text, expected):
    assert utils.mask_personal_details(text) == expected


def test_mask_personal_details_hides_every_email_and_phone():
    masked = utils.mask_personal_details("a@x.com, b.c@y.org and 555-123-4567 or 555 987 6543")
    assert "a@x.com" not in masked and "b.c@y.org" not in masked
    assert "4567" in masked and "123-4567" not in masked and "987 6543" not in masked


def test_initials():
    assert utils.initials("Maria Lopez") == "M. L."
    assert utils.initials("varsha  dewangan") == "V. D."


# ---------------------------------------------------------------- spoken text
def test_spell_reference():
    assert (
        utils.spell_reference("ENR-20261030-U63CHY")
        == "E, N, R, two zero two six one zero three zero, U, six, three, C, H, Y"
    )


def test_spoken_date():
    assert utils.spoken_date(date(2026, 11, 8)) == "Sunday, November 8"


# ---------------------------------------------------------------- business time zone
def freeze_utc(monkeypatch, *args):
    """Make utils think the current time is this UTC time."""
    moment = datetime(*args, tzinfo=ZoneInfo("UTC"))

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz)

    monkeypatch.setattr(utils, "datetime", FakeDatetime)


def test_business_today_is_still_yesterday_late_evening_in_new_york(monkeypatch):
    # 03:30 UTC on Oct 31 is 23:30 on Oct 30 in New York.
    freeze_utc(monkeypatch, 2026, 10, 31, 3, 30)
    assert utils.business_today() == date(2026, 10, 30)


def test_business_today_after_midnight_in_new_york(monkeypatch):
    freeze_utc(monkeypatch, 2026, 10, 31, 4, 30)
    assert utils.business_today() == date(2026, 10, 31)


# ---------------------------------------------------------------- prompts
@pytest.mark.parametrize(
    "name",
    [
        "triage_prompt.md",
        "enrollment_prompt.md",
        "billing_query_prompt.md",
        "cancellation_prompt.md",
        "account_update_prompt.md",
    ],
)
def test_prompt_loads(name):
    assert len(utils.load_prompt(name)) > 100


def test_missing_prompt_is_an_error():
    with pytest.raises(FileNotFoundError):
        utils.load_prompt("does_not_exist.md")


def test_call_id_outside_a_job():
    assert utils.call_id() == "no-job"
