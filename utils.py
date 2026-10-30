import logging
import os
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

import yaml
from livekit.agents import get_job_context

from config import BUSINESS_TIMEZONE

logger = logging.getLogger("voice-agent")

_DIGITS = dict(zip("0123456789", "zero one two three four five six seven eight nine".split()))


def spell_reference(reference: str) -> str:
    """Spell a reference such as ENR-20261029-TAK9F2 for speech.

    The prefix and code are spelled letter by letter; the date runs on without pauses.
    """
    prefix, date_part, code = reference.split("-")
    date_words = " ".join(_DIGITS[d] for d in date_part)
    code_words = ", ".join(_DIGITS.get(c, c) for c in code)
    return f"{', '.join(prefix)}, {date_words}, {code_words}"


async def publish_reference(kind: str, reference: str) -> None:
    """Send a new reference to the web page, which shows it in a card.

    Only a convenience: the customer already hears the reference, so a failure must not
    break the workflow.
    """
    try:
        await get_job_context().room.local_participant.send_text(
            reference, topic="reference", attributes={"kind": kind}
        )
    except Exception as e:
        logger.warning("Could not publish the %s reference: %s", kind, type(e).__name__)


def call_id() -> str:
    """The current job's ID, used in idempotency keys so a repeated tool call saves once."""
    try:
        return get_job_context().job.id
    except RuntimeError:  # not running inside a job (tests, scripts)
        return "no-job"


def business_now() -> datetime:
    """Current time in the business time zone (BUSINESS_TIMEZONE, default America/New_York).

    LiveKit Cloud runs on UTC, so plain datetime.now() would give the wrong day in US evenings.
    """
    return datetime.now(ZoneInfo(BUSINESS_TIMEZONE))


def business_today() -> date:
    return business_now().date()


_EMAIL = re.compile(r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
_PHONE = re.compile(r"(?<![\w-])\+?\d[\d\s().-]{6,}\d(?![\w-])")


def _mask_phone(match: re.Match) -> str:
    digits = re.sub(r"\D", "", match.group())
    if len(digits) < 10:  # dates, ZIP codes and amounts are not phone numbers
        return match.group()
    return "*" * (len(digits) - 4) + digits[-4:]


def mask_personal_details(text: str) -> str:
    """Hide emails and phone numbers before logging, e.g. m***@example.com, *******4567.

    Names inside free text can't be found reliably, so code that knows a name should log
    `initials(name)` instead of the name itself.
    """
    return _PHONE.sub(_mask_phone, _EMAIL.sub(r"\1***@\2", text))


def initials(name: str) -> str:
    """'Maria Lopez' -> 'M. L.'"""
    return " ".join(f"{part[0].upper()}." for part in name.split())


def spoken_date(day) -> str:
    """e.g. 'Saturday, October 31'."""
    return f"{day:%A, %B} {day.day}"


def load_prompt(filename):
    """Load a prompt from the prompts folder.

    .md / .txt files are read as plain text.
    .yaml / .yml files must have an `instructions` key.
    Raises an error if the file is missing, invalid, or empty,
    so the agent never starts without instructions.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_path = os.path.join(script_dir, "prompts", filename)

    with open(prompt_path, "r", encoding="utf-8") as file:
        content = file.read()

    if filename.lower().endswith((".yaml", ".yml")):
        data = yaml.safe_load(content) or {}
        instructions = data.get("instructions", "")
    else:
        instructions = content

    instructions = instructions.strip()
    if not instructions:
        raise ValueError(f"Prompt file {filename} is empty.")

    return instructions
