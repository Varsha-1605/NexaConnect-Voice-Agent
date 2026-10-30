from datetime import date

import pytest

from services import validation

TODAY = date(2026, 10, 30)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(validation, "business_today", lambda: TODAY)


def errors(**fields):
    return validation.validate(**fields)["errors"]


def normalized(**fields):
    return validation.validate(**fields)["normalized"]


# phone
@pytest.mark.parametrize(
    "phone",
    ["7974517506", "(797) 451-7506", "+1 797 451 7506", "1-797-451-7506", "797.451.7506"],
)
def test_phone_good(phone):
    assert normalized(phone_number=phone) == {"phone_number": "+17974517506"}


@pytest.mark.parametrize("phone", ["", "12345", "797451750", "0974517506", "1974517506", "abcdefghij"])
def test_phone_bad(phone):
    assert "phone_number" in errors(phone_number=phone)


# email
def test_email_is_lowercased():
    assert normalized(email=" Maria@Example.COM ") == {"email": "maria@example.com"}


@pytest.mark.parametrize("email", ["maria", "maria@", "@example.com", "maria@example", "ma ria@x.com"])
def test_email_bad(email):
    assert "email" in errors(email=email)


def test_email_is_optional():
    assert validation.validate(email=None)["valid"]
    assert validation.validate(email="")["valid"]


# name, address, ZIP
def test_name_spaces_are_cleaned():
    assert normalized(customer_name="  Varsha   Dewangan ") == {"customer_name": "Varsha Dewangan"}


@pytest.mark.parametrize("name", ["", "A", "1234", "  "])
def test_name_bad(name):
    assert "customer_name" in errors(customer_name=name)


def test_address_good_and_bad():
    assert normalized(service_address="C 21  Jane Street") == {"service_address": "C 21 Jane Street"}
    assert "service_address" in errors(service_address="12")


@pytest.mark.parametrize("zip_code, ok", [("78701", True), ("78701-1234", True), ("7870", False), ("ABCDE", False), ("787011", False)])
def test_zip(zip_code, ok):
    assert ("postal_code" not in errors(postal_code=zip_code)) is ok


def test_zip_plus_four_is_shortened():
    assert normalized(postal_code="78701-1234") == {"postal_code": "78701"}


# plan
def test_plan_name_is_matched_ignoring_case():
    assert normalized(plan_name=" home 500 ") == {"plan_name": "Home 500"}


def test_unknown_plan_lists_the_real_ones():
    message = errors(plan_name="Home 900")["plan_name"]
    assert "Home 300" in message and "Home 500" in message and "Home Gigabit" in message


# installation date
@pytest.mark.parametrize(
    "value, ok",
    [
        ("2026-10-29", False),  # past
        ("2026-10-30", False),  # today
        ("2026-10-31", True),  # tomorrow
        ("2026-12-29", True),  # 60 days ahead
        ("2026-12-30", False),  # 61 days ahead
        ("11/08/2026", False),  # wrong format
        ("not a date", False),
    ],
)
def test_installation_date(value, ok):
    assert ("preferred_installation_date" not in errors(preferred_installation_date=value)) is ok


def test_only_the_fields_passed_in_are_checked():
    result = validation.validate(phone_number="7974517506")
    assert result["valid"] and list(result["normalized"]) == ["phone_number"]


def test_all_errors_are_reported_together():
    result = validation.validate(customer_name="", phone_number="1", postal_code="x")
    assert set(result["errors"]) == {"customer_name", "phone_number", "postal_code"}
    assert not result["valid"]
