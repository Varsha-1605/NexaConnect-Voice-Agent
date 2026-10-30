import logging
import os

import yaml
from livekit.agents import get_job_context

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
