"""The enrollment submit tool: consent, checks, and that 'You're enrolled' only follows a real save."""

import pytest
from livekit.agents import ToolError
from livekit.agents.llm import ChatContext

from services import enrollment_service
from workflows import EnrollmentWorkflow, WorkflowOutcome
from workflows import enrollment as enrollment_module

GOOD = dict(
    customer_name="Maria Lopez",
    phone_number="(797) 451-7506",
    service_address="21 Jane Street",
    city="Austin",
    state="Texas",
    postal_code="78701",
    plan_name="Home 500",
    monthly_plan_price=55.0,
    router_rental_selected=True,
    consent_confirmed=True,
    email=None,
    preferred_installation_date=None,
)


@pytest.fixture
async def workflow():
    return EnrollmentWorkflow(chat_ctx=ChatContext())


@pytest.fixture
def saves(monkeypatch, context):
    """Replace the database save. Records each save, in order with the spoken lines."""
    keys = []

    async def fake_save(**fields):
        keys.append(fields["idempotency_key"])
        context.events.append(("save", fields["customer_name"]))
        return "ENR-20261030-ABC234"

    async def no_publish(kind, reference):
        pass

    monkeypatch.setattr(enrollment_service, "save_enrollment", fake_save)
    monkeypatch.setattr(enrollment_module, "publish_reference", no_publish)
    return keys


def said(context):
    return " ".join(context.session.said)


async def test_good_submit_saves_then_confirms(workflow, context, saves):
    await workflow.submit_enrollment(context, **GOOD)
    order = [kind for kind, _ in context.events]
    assert order == ["say", "save", "say"]  # "One moment…", save, "You're enrolled!"
    assert "You're enrolled" in context.session.said[-1]
    assert context.userdata.enrollment_completed
    assert workflow.done()  # the workflow ended


async def test_confirmation_spells_the_reference(workflow, context, saves):
    await workflow.submit_enrollment(context, **GOOD)
    assert "E, N, R, two zero two six one zero three zero, A, B, C, two, three, four" in said(context)


async def test_summary_returned_to_the_agent_has_initials_not_the_name(workflow, context, saves, monkeypatch):
    finished = []
    monkeypatch.setattr(workflow, "complete", finished.append)
    await workflow.submit_enrollment(context, **GOOD)
    (result,) = finished
    assert result.outcome == WorkflowOutcome.COMPLETED
    assert "M. L." in result.summary and "Maria" not in result.summary and "Lopez" not in result.summary


async def test_no_consent_means_no_save(workflow, context, saves):
    with pytest.raises(ToolError, match="consent"):
        await workflow.submit_enrollment(context, **{**GOOD, "consent_confirmed": False})
    assert saves == [] and not context.userdata.enrollment_completed


@pytest.mark.parametrize(
    "bad",
    [
        {"phone_number": "123"},
        {"postal_code": "ABCDE"},
        {"customer_name": ""},
        {"plan_name": "Home 900"},
        {"email": "not-an-email"},
        {"preferred_installation_date": "2020-01-01"},
    ],
)
async def test_bad_details_mean_no_save(workflow, context, saves, bad):
    with pytest.raises(ToolError):
        await workflow.submit_enrollment(context, **{**GOOD, **bad})
    assert saves == []


async def test_city_we_do_not_serve_means_no_save(workflow, context, saves):
    with pytest.raises(ToolError, match="does not serve"):
        await workflow.submit_enrollment(context, **{**GOOD, "city": "Boise", "state": "ID"})
    assert saves == []


async def test_failed_save_says_nothing_was_submitted(workflow, context, monkeypatch):
    async def broken_save(**fields):
        raise ConnectionError("database is down")

    monkeypatch.setattr(enrollment_service, "save_enrollment", broken_save)
    with pytest.raises(ToolError, match="Nothing was submitted"):
        await workflow.submit_enrollment(context, **GOOD)
    assert "You're enrolled" not in said(context)
    assert not context.userdata.enrollment_completed
    assert not workflow.done()


async def test_failed_save_is_logged_with_an_event_name(workflow, context, monkeypatch, caplog):
    async def broken_save(**fields):
        raise ConnectionError("database is down")

    monkeypatch.setattr(enrollment_service, "save_enrollment", broken_save)
    with pytest.raises(ToolError):
        await workflow.submit_enrollment(context, **GOOD)
    assert any(getattr(r, "event", None) == "db_save_failed" for r in caplog.records)


async def test_same_customer_twice_in_one_call_uses_one_idempotency_key(context, saves):
    for _ in range(2):
        await EnrollmentWorkflow(chat_ctx=ChatContext()).submit_enrollment(context, **GOOD)
    assert len(saves) == 2 and saves[0] == saves[1]
