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
