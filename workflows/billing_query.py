import logging

from livekit.agents import ChatContext, RunContext, ToolError, function_tool

from services import billing_service
from utils import call_id, publish_reference, spell_reference

from .workflow_task import CallState, WorkflowTask
from .shared_tools import run_with_filler, verified_reference, verify_customer

logger = logging.getLogger("voice-agent")

NO_BILL = "No bill is on file for this account yet."


class BillingQueryWorkflow(WorkflowTask):
    prompt_file = "billing_query_prompt.md"
    opening = "I can help with that. Is it a high bill, an unexpected charge, or a payment issue?"
    shared_tools = [verify_customer]

    def __init__(self, chat_ctx: ChatContext, customer_verified: bool = False, request: str = ""):
        super().__init__(chat_ctx, customer_verified, request)
        if customer_verified:
            self.opening = ""  # the issue may already be known, so let the model start

    async def _lookup_bill(self, context: RunContext[CallState], reference: str) -> dict | None:
        return await run_with_filler(
            context,
            "Let me pull up your bill and check on that.",
            billing_service.get_bill(reference),
        )

    @function_tool()
    async def get_bill_details(self, context: RunContext[CallState]) -> dict | str:
        """Retrieve the current bill: billing period, due date, total, itemized `charges`
        and the payment status. Quote only what is returned."""
        reference = verified_reference(context)
        return await self._lookup_bill(context, reference) or NO_BILL

    @function_tool()
    async def get_payment_status(self, context: RunContext[CallState]) -> dict | str:
        """Check whether the current bill's payment was `received`, is `pending`, or is
        `outstanding`, with the amount paid and the amount still owed."""
        reference = verified_reference(context)
        bill = await self._lookup_bill(context, reference)
        if not bill:
            return NO_BILL
        return {
            key: bill[key]
            for key in ("payment_status", "total_amount", "amount_paid", "amount_outstanding", "paid_on", "due_date")
        }

    @function_tool()
    async def create_support_ticket(
        self,
        context: RunContext[CallState],
        billing_issue: str,
        billing_issue_details: str,
    ) -> dict:
        """Create a support ticket when the billing issue cannot be resolved on the call.
        Call only after the customer agrees to a ticket.

        Args:
            billing_issue: Short category, e.g. "high bill" or "unrecognized charge".
            billing_issue_details: What the customer reported and what was checked.
        """
        context.disallow_interruptions()
        reference = verified_reference(context)
        try:
            ticket = await run_with_filler(
                context,
                "One moment while I create that ticket for you.",
                billing_service.create_ticket(
                    reference,
                    billing_issue,
                    billing_issue_details,
                    idempotency_key=f"{call_id()}:{reference}",
                ),
            )
        except Exception as e:
            logger.error(
                "Support ticket for %s could not be saved: %s",
                reference,
                type(e).__name__,
                extra={"event": "db_save_failed", "workflow": "billing_query"},
            )
            raise ToolError(
                "The ticket could not be saved. Nothing was submitted. "
                "Tell the customer and offer a team member."
            ) from e

        logger.info("Support ticket %s saved", ticket, extra={"event": "ticket_saved"})
        await publish_reference("Support ticket", ticket)
        return {"ticket_reference": ticket, "spoken_reference": spell_reference(ticket)}
