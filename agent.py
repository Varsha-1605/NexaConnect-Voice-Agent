import asyncio
import logging
import os
import threading

from dotenv import load_dotenv
from livekit import agents, api, rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    ConversationItemAddedEvent,
    RoomInputOptions,
    RunContext,
    ToolError,
    TurnHandlingOptions,
    UserStateChangedEvent,
    function_tool,
    get_job_context,
    inference,
)
from livekit.agents.beta.tools import EndCallTool
from livekit.agents.inference.llm import llm_from_model_string
from livekit.agents.llm import ChatMessage
from livekit.plugins import ai_coustics, silero
from db.pool import close_pool, init_pool
from services import knowledge_base
from utils import load_prompt
from workflows import (
    AccountUpdateWorkflow,
    BillingQueryWorkflow,
    CallState,
    CancellationWorkflow,
    EnrollmentWorkflow,
    WorkflowOutcome,
    WorkflowTask,
)
from workflows.shared_tools import search_knowledge_base

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voice-agent")

# After this many seconds of customer silence (the agent's own speech doesn't count) the agent asks
# "Are you still there?", then ends the call if the customer still hasn't spoken this long after it.
CUSTOMER_SILENCE_TIMEOUT = 10.0
STILL_THERE_WAIT = 3.0

class PrimaryAgent(Agent):
    """Supervisor: stays in control of the call, delegates each request to a
    workflow (AgentTask), and decides what happens next from its result."""

    def __init__(self):
        super().__init__(
            instructions=load_prompt("triage_prompt.md"),
            tools=[
                search_knowledge_base,
                *EndCallTool(
                    extra_description=(
                        "Call it only after the customer has said they need nothing else and "
                        "says goodbye. Never call it while a request is still open, or when "
                        "they ask for a team member."
                    ),
                ).tools,
            ],
        )

    async def _delegate(
        self, context: RunContext[CallState], workflow_cls: type[WorkflowTask], request: str = ""
    ) -> str:
        logger.info("Delegating to %s", workflow_cls.__name__)
        result = await workflow_cls(
            # Conversation so far, without the primary agent's system prompt.
            chat_ctx=self.chat_ctx.copy(exclude_instructions=True),
            customer_verified=context.userdata.customer_verified,
            request=request,
        )
        logger.info(
            "%s finished: %s | %s", workflow_cls.__name__, result.outcome.value, result.summary
        )

        if result.outcome == WorkflowOutcome.ESCALATE:
            next_step = "Call transfer_to_human now."
        else:
            next_step = (
                "If the summary mentions a new request, route it. "
                "Otherwise ask if there is anything else you can help with."
            )
        return (
            f"Workflow finished with outcome '{result.outcome.value}'. "
            f"Summary: {result.summary} "
            f"The customer was already told the outcome; do not repeat it. {next_step}"
        )

    @function_tool()
    async def start_cancellation(self, context: RunContext[CallState]) -> str:
        """Start the service cancellation workflow when the customer wants to cancel a service."""
        if context.userdata.cancellation_completed:
            return (
                "The cancellation was already submitted and the customer has its reference. "
                "Do not start another one. Ask if there is anything else you can help with."
            )
        return await self._delegate(context, CancellationWorkflow)

    @function_tool()
    async def start_account_update(self, context: RunContext[CallState], request: str = "") -> str:
        """Start the account update workflow when the customer wants to change account information.

        Args:
            request: The change the customer already asked for, if known, e.g.
                "change plan to Home Gigabit". Leave empty if they haven't said.
        """
        return await self._delegate(context, AccountUpdateWorkflow, request)

    @function_tool()
    async def start_billing_query(self, context: RunContext[CallState]) -> str:
        """Start the billing workflow for questions about bills, charges, or payments."""
        return await self._delegate(context, BillingQueryWorkflow)

    @function_tool()
    async def start_enrollment(self, context: RunContext[CallState]) -> str:
        """Start the enrollment workflow when the customer wants to check availability
        or sign up for a new service."""
        if context.userdata.enrollment_completed:
            return (
                "The enrollment was already submitted and the customer has its reference. "
                "Do not start another one. Ask if there is anything else you can help with."
            )
        result = await self._delegate(context, EnrollmentWorkflow)
        context.userdata.enrollment_completed = "outcome 'completed'" in result
        return result

    @function_tool()
    async def transfer_to_human(self, context: RunContext[CallState], reason: str) -> str:
        """Transfer the customer to human support.

        Args:
            reason: Why the transfer is needed, for the human agent.
        """
        logger.info("Transfer to human requested: %s", reason)
        job_ctx = get_job_context()
        sip_participant = next(
            (
                p
                for p in job_ctx.room.remote_participants.values()
                if p.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
            ),
            None,
        )
        transfer_to = os.getenv("HUMAN_TRANSFER_NUMBER")
        if sip_participant is None or not transfer_to:
            raise ToolError(
                "Nobody has been connected: this call can't be transferred right now. "
                "Apologize, tell the customer plainly that you can't transfer them, "
                "and ask if there is anything else you can help with."
            )

        await context.session.say(
            "Of course, I'll transfer you to a team member now. Please hold.",
            allow_interruptions=False,
        )
        await job_ctx.api.sip.transfer_sip_participant(
            api.TransferSIPParticipantRequest(
                room_name=job_ctx.room.name,
                participant_identity=sip_participant.identity,
                transfer_to=f"tel:{transfer_to}",
                play_dialtone=True,
            )
        )
        return "The customer was transferred. Do not say anything more."


async def check_in_then_end(session: AgentSession, ctx: agents.JobContext) -> None:
    """Ask "Are you still there?", then hang up if the customer is still silent STILL_THERE_WAIT later."""
    await session.say("Are you still there?")
    await asyncio.sleep(STILL_THERE_WAIT)
    if session.user_state != "away":
        return
    logger.info("Customer still silent, ending the call")
    session.say(
        "I haven't heard from you, so I'll end the call now. "
        "Thank you for calling NexaConnect. Goodbye!",
        allow_interruptions=False,
    )

    # The same hang-up EndCallTool does: close the session, delete the room, end the job.
    async def delete_room() -> None:
        await ctx.delete_room()

    ctx.add_shutdown_callback(delete_room)
    session.once("close", lambda event: ctx.shutdown(reason=event.reason.value))
    session.shutdown(drain=True)


def prewarm(proc: agents.JobProcess):
    """Load models and clients once per process so the first call isn't slow."""
    logger.info("Prewarming worker process...")

    # Default 0.55s silence delays every turn; the turn detector handles mid-sentence pauses.
    proc.userdata["vad"] = silero.VAD.load(min_silence_duration=0.3)

    # Otherwise imported lazily on the first LLM call, blocking the event loop.
    import anyio._backends._asyncio  # noqa: F401
    import unittest.mock  # noqa: F401  (console mode's mock room imports it on the first job)
    import openai.lib.streaming.chat as _openai_streaming  # noqa: F401

    # Reused by every session so its HTTP/SSL setup isn't on the call path.
    proc.userdata["llm"] = llm_from_model_string("google/gemma-4-31b-it")

    # Pinecone index lookup is a blocking HTTP call; do it here, not during a call.
    knowledge_base.share_ssl_context()
    knowledge_base.vector_store()
    # Background thread: prewarm has a 10 s limit and this is a network call.
    threading.Thread(target=knowledge_base.warm_up, daemon=True).start()


server = AgentServer()
server.setup_fnc = prewarm


@server.rtc_session(agent_name="my-agent")
async def entrypoint(ctx: agents.JobContext):
    logger.info(f"Connecting to room: {ctx.room.name}")

    # Open both together so their network waits overlap.
    # If either fails the call still starts; the tool that needs it reports the error.
    results = await asyncio.gather(init_pool(), knowledge_base.connect(), return_exceptions=True)
    for name, result in zip(("Database pool", "Pinecone connection"), results):
        if isinstance(result, Exception):
            logger.error("%s could not be opened: %s", name, type(result).__name__)
    ctx.add_shutdown_callback(close_pool)
    ctx.add_shutdown_callback(knowledge_base.disconnect)

    session = AgentSession[CallState](
        userdata=CallState(),
        stt="deepgram/nova-3:en",
        llm=ctx.proc.userdata["llm"],
        tts="cartesia/sonic-3:9626c31c-bec5-4cca-baa8-f8ba9e84c8bc",
        vad=ctx.proc.userdata["vad"],
        user_away_timeout=CUSTOMER_SILENCE_TIMEOUT,
        turn_handling=TurnHandlingOptions(
            turn_detection=inference.TurnDetector(),
            endpointing={
                "mode": "dynamic",
                "min_delay": 0.2,
                "max_delay": 0.5,
                "alpha": 0.5,
            },
            interruption={
                "mode": "adaptive",
                "min_duration": 0.5,
                "min_words": 0,
                "false_interruption_timeout": 1.0,
                "resume_false_interruption": True,
            },
            preemptive_generation={
                "enabled": True,
                "preemptive_tts": True,
            },
        ),
    )

    @session.on("conversation_item_added")
    def log_turn_latency(event: ConversationItemAddedEvent) -> None:
        item = event.item
        if not isinstance(item, ChatMessage) or item.role != "assistant":
            return
        latency = {
            key: round(item.metrics[key], 2)
            for key in ("e2e_latency", "llm_node_ttft", "tts_node_ttfb")
            if key in item.metrics
        }
        if latency:
            logger.info("Turn latency (s): %s", latency)

    async def log_usage() -> None:
        logger.info("Call usage: %s", session.usage.model_usage)

    ctx.add_shutdown_callback(log_usage)

    check_ins: set[asyncio.Task] = set()

    @session.on("user_state_changed")
    def on_customer_silence(event: UserStateChangedEvent) -> None:
        if event.new_state != "away":
            return
        logger.info("Customer silent for %ss, checking in", CUSTOMER_SILENCE_TIMEOUT)
        task = asyncio.create_task(check_in_then_end(session, ctx))
        check_ins.add(task)
        task.add_done_callback(check_ins.discard)

    await session.start(
        room=ctx.room,
        agent=PrimaryAgent(),
        room_input_options=RoomInputOptions(
            noise_cancellation=ai_coustics.audio_enhancement(
                model=ai_coustics.EnhancerModel.QUAIL_VF_L,
            ),
        ),
    )

    await session.generate_reply(
        instructions=(
            "Greet the user in one short sentence: say you are Ashley from NexaConnect "
            "and ask how you can help."
        )
    )


if __name__ == "__main__":
    agents.cli.run_app(server)
