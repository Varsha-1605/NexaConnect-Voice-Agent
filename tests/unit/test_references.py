import re
from datetime import date

from services import enrollment_service


def test_reference_format(monkeypatch):
    monkeypatch.setattr(enrollment_service, "business_today", lambda: date(2026, 10, 30))
    reference = enrollment_service.new_reference("ENR")
    assert re.fullmatch(r"ENR-20261030-[A-HJ-NP-Z2-9]{6}", reference)


def test_reference_uses_the_business_date(monkeypatch):
    monkeypatch.setattr(enrollment_service, "business_today", lambda: date(2027, 1, 2))
    assert enrollment_service.new_reference("CAN").startswith("CAN-20270102-")


def test_references_are_not_repeated():
    assert len({enrollment_service.new_reference("ENR") for _ in range(1000)}) == 1000


def test_alphabet_has_no_confusing_characters():
    for character in "01OI":
        assert character not in enrollment_service.REFERENCE_ALPHABET
