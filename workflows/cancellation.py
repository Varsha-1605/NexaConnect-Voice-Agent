import logging
from datetime import date

from livekit.agents import ChatContext, RunContext, ToolError, function_tool

from services import account_service, cancellation_service, knowledge_base
from utils import publish_reference, spell_reference, spoken_date

from .workflow_task import CallState, WorkflowOutcome, WorkflowResult, WorkflowTask
from .shared_tools import (
    get_account_details,
    search_knowledge_base,
    verified_reference,
    verify_customer,
)

logger = logging.getLogger("voice-agent")


def _confirmation(reference: str, end_date: date, already_requested: bool) -> str:
    spelled = spell_reference(reference)
    ends = f"Your service will end on {spoken_date(end_date)}."
    if already_requested:
        return (
            "That account already has a cancellation request on file. "
            f"The reference is {spelled}. {ends}"
        )
    return f"Your cancellation request has been submitted. Your reference is {spelled}. {ends}"


class CancellationWorkflow(WorkflowTask):
    """Service cancellation. Spec: docs/cancellation_workflow.md."""

    prompt_file = "cancellation_prompt.md"
    opening = (
        "I can help with that. To find your account, I'll need your full name, the street "
        "address of your service, and either your email address or your phone number. "
        "Could we start with your full name?"
    )
    shared_tools = [verify_customer, get_account_details, search_knowledge_base]

    def __init__(self, chat_ctx: ChatContext, customer_verified: bool = False, request: str = ""):
        super().__init__(chat_ctx, customer_verified, request)
        # `submit_cancellation` refuses until the terms have been fetched and explained.
        self._terms_explained = False
        if customer_verified:
            self.opening = ""  # the reason may already be known, so let the model start

    @function_tool()
    async def get_contract_terms(self, context: RunContext[CallState]) -> dict:
        """Retrieve the customer's plan, the listed contract terms, and `service_ends_on`,
        the date service would end if they cancel today (the end of the billing month).
        Quote only what is listed; never invent fees or notice periods."""
        account = await account_service.get_account(verified_reference(context))
        context.session.say("Let me check the plan terms for you.")
        self._terms_explained = True
        return {
            "plan_name": account["plan_name"],
            "service_ends_on": spoken_date(cancellation_service.effective_date()),
            "terms": await knowledge_base.search("contract length"),
        }

    @function_tool()
    async def submit_cancellation(
        self,
        context: RunContext[CallState],
        cancellation_reason: str,
        consent_confirmed: bool,
    ) -> None:
        """Submit the cancellation request and tell the customer the reference. It speaks
        the confirmation and ends the workflow itself. Call only after verification and
        after the customer explicitly confirms the summary.

        Args:
            cancellation_reason: Why the customer is cancelling.
            consent_confirmed: True only if the customer explicitly confirmed the cancellation.
        """
        context.disallow_interruptions()
        reference = verified_reference(context)
        if not self._terms_explained:
            raise ToolError(
                "The terms have not been explained yet. Call `get_contract_terms`, explain the "
                "terms and end date, then summarize and ask the customer to confirm."
            )
        if not consent_confirmed:
            raise ToolError("The customer has not explicitly confirmed. Ask for confirmation first.")

        context.session.say("One moment while I submit that for you.")
        try:
            cancellation_reference, end_date, already_requested = (
                await cancellation_service.submit_cancellation(reference, cancellation_reason.strip())
            )
        except Exception as e:
            logger.error("Cancellation for %s could not be saved: %s", reference, type(e).__name__)
            raise ToolError(
                "The cancellation could not be saved. Nothing was submitted. "
                "Tell the customer and offer a team member."
            ) from e

        context.userdata.cancellation_completed = True
        logger.info("Cancellation %s saved", cancellation_reference)

        summary = (
            f"Cancellation {'was already on file' if already_requested else 'submitted'}. "
            f"Reference {cancellation_reference}. Service ends {end_date.isoformat()}. "
            "The customer was already given the reference."
        )

        def complete_workflow(_) -> None:
            if not self.done():  # a repeated tool call must not complete the task twice
                self.complete(WorkflowResult(WorkflowOutcome.COMPLETED, summary))

        # Not awaited (it would deadlock inside this speech). Returning None skips the model's reply.
        speech = context.session.say(
            _confirmation(cancellation_reference, end_date, already_requested),
            allow_interruptions=False,
        )
        speech.add_done_callback(complete_workflow)
        await publish_reference("Cancellation", cancellation_reference)

    @function_tool()
    async def get_cancellation_status(self, context: RunContext[CallState]) -> dict | str:
        """Check the cancellation status when the submit result is unclear."""
        status = await cancellation_service.get_status(verified_reference(context))
        return status or "No cancellation request is on file for this account."
