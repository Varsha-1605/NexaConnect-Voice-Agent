from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import Literal

from livekit.agents import AgentTask, ChatContext, function_tool

from config import UPCOMING_DAYS
from utils import business_now, load_prompt, spoken_date


def _today_line() -> str:
    now = business_now()
    return f"{spoken_date(now)}, {now.year}"


def _upcoming_days() -> str:
    today = business_now()
    return "; ".join(spoken_date(today + timedelta(days=i)) for i in range(1, UPCOMING_DAYS + 1))


@dataclass
class CallState:
    customer_verified: bool = False
    verification_attempts: int = 0
    enrollment_reference: str | None = None  # the verified customer's account
    enrollment_completed: bool = False
    cancellation_completed: bool = False
    last_filler_at: float = 0.0  # when a waiting line was last spoken


class WorkflowOutcome(str, Enum):
    COMPLETED = "completed"
    CANCELLED = "cancelled by customer"
    ESCALATE = "escalate"


@dataclass
class WorkflowResult:
    outcome: WorkflowOutcome
    summary: str


class WorkflowTask(AgentTask[WorkflowResult]):
    prompt_file: str = ""
    shared_tools: list = []
    opening: str = ""  # spoken on entry, no model wait

    def __init__(self, chat_ctx: ChatContext, customer_verified: bool = False, request: str = ""):
        verification_note = (
            "The customer is already verified. Do not call `verify_customer` again."
            if customer_verified
            else "The customer is not verified yet."
        )
        request_note = (
            f"\n\n# Customer Request\n\nThe customer already asked for this: {request}. "
            "Do not ask what they want; start from it."
            if request
            else ""
        )
        super().__init__(
            instructions=load_prompt(self.prompt_file)
            + f"\n\n# Verification State\n\n{verification_note}"
            + request_note
            + f"\n\n# Current Date\n\nToday is {_today_line()}.\n\n"
            f"Upcoming days, with the correct weekday for each: {_upcoming_days()}.\n"
            "Take every weekday only from this list; never work one out yourself.",
            chat_ctx=chat_ctx,
            tools=list(self.shared_tools),
        )
        self.request = request

    async def on_enter(self) -> None:
        # not awaited: would block this tool
        if self.opening and not self.request:
            self.session.say(self.opening)
        else:
            self.session.generate_reply(
                instructions="Start this workflow now. Do not greet the customer or say it is "
                "nice to meet them; they were already acknowledged. Go straight to the first step."
            )

    @function_tool()
    async def finish_workflow(
        self,
        outcome: Literal["completed", "cancelled by customer", "escalate"],
        summary: str,
    ) -> None:
        """End this workflow and return control to the primary agent.

        Call this only after you have told the customer the outcome.

        Args:
            outcome: "completed" if the task finished, "cancelled by customer" if the
                customer stopped or changed their request, "escalate" if they need a human.
            summary: One or two sentences on what happened, including any new request
                the customer made.
        """
        self.complete(WorkflowResult(outcome=WorkflowOutcome(outcome), summary=summary))
