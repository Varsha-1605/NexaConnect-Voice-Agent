"""Speech-to-text, LLM and text-to-speech, each with a backup.

If a primary provider fails (connection error, timeout, 4xx/5xx), the backup takes over, so one
provider outage doesn't end calls. Test each backup on its own with the critical simulations
before relying on it.
"""

import logging

from livekit.agents import inference, llm
from livekit.agents.inference.llm import llm_from_model_string
from livekit.plugins import openai

from config import (
    BACKUP_LLM,
    PRIMARY_LLM,
    STT_BACKUP_MODEL,
    STT_LANGUAGE,
    STT_MODEL,
    TTS_BACKUP_MODEL,
    TTS_BACKUP_VOICE,
    TTS_LANGUAGE,
    TTS_MODEL,
    TTS_VOICE,
)

logger = logging.getLogger("voice-agent")


def build_stt() -> inference.STT:
    return inference.STT(
        model=STT_MODEL,
        language=STT_LANGUAGE,
        fallback=[{"model": STT_BACKUP_MODEL}],
    )


def build_tts() -> inference.TTS:
    return inference.TTS(
        model=TTS_MODEL,
        voice=TTS_VOICE,
        language=TTS_LANGUAGE,
        fallback=[{"model": TTS_BACKUP_MODEL, "voice": TTS_BACKUP_VOICE}],
    )


def build_llm() -> llm.FallbackAdapter:
    """Built once per process in prewarm, so the HTTP/SSL setup isn't on the call path."""
    adapter = llm.FallbackAdapter(
        [llm_from_model_string(PRIMARY_LLM), openai.LLM(model=BACKUP_LLM)],
    )

    @adapter.on("llm_availability_changed")
    def log_availability(event) -> None:
        logger.warning(
            "LLM %s is now %s",
            event.llm.model,
            "available" if event.available else "unavailable",
            extra={"event": "model_fallback"},
        )

    return adapter
