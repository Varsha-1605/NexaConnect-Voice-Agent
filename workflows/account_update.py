import logging
from typing import Literal

from livekit.agents import ChatContext, RunContext, ToolError, function_tool

from services import account_service

from .workflow_task import CallState, WorkflowTask
from .shared_tools import (
    get_account_details,
    search_knowledge_base,
    verified_reference,
    verify_customer,
)

logger = logging.getLogger("voice-agent")


class AccountUpdateWorkflow(WorkflowTask):
    """Account update. Spec: docs/account_update.md."""

    prompt_file = "account_update_prompt.md"
    opening = "I can help with that. Which account information would you like to update?"
    shared_tools = [verify_customer, get_account_details, search_knowledge_base]

    def __init__(self, chat_ctx: ChatContext, customer_verified: bool = False, request: str = ""):
        super().__init__(chat_ctx, customer_verified, request)
        # The last change that passed validation. `update_customer_details` saves exactly this.
        self._pending: tuple[str, dict] | None = None

    @function_tool()
    async def validate_account_change(
        self,
        context: RunContext[CallState],
        field: Literal["customer_name", "phone_number", "email", "service_address", "plan_name"],
        new_value: str,
        city: str | None = None,
        state: str | None = None,
        postal_code: str | None = None,
    ) -> dict:
        """Check one requested change against the customer's account. Nothing is saved.
        Returns `valid`, `errors` to resolve with the customer, and `changes`, the values
        that would be saved (a plan change includes `monthly_plan_price`).

        Args:
            field: The account field to change.
            new_value: The new value; for `plan_name`, the plan name; for `service_address`, the street address.
            city: New city. Only for `service_address`.
            state: New state. Only for `service_address`.
            postal_code: New 5-digit ZIP code. Only for `service_address`.
        """
        account = await account_service.get_account(verified_reference(context))
        result = account_service.validate_change(account, field, new_value, city, state, postal_code)
        self._pending = (field, result["changes"]) if result["valid"] else None
        return result

    @function_tool()
    async def update_customer_details(
        self, context: RunContext[CallState], consent_confirmed: bool
    ) -> dict:
        """Save the change last checked by `validate_account_change`. Call only after the
        customer explicitly confirms the change you read back.

        Args:
            consent_confirmed: True only if the customer explicitly confirmed the change.
        """
        context.disallow_interruptions()
        reference = verified_reference(context)
        if not self._pending:
            raise ToolError("No change has been validated. Call `validate_account_change` first.")
        if not consent_confirmed:
            raise ToolError("The customer has not explicitly confirmed. Ask for confirmation first.")

        field, changes = self._pending
        try:
            await account_service.update_account(reference, field, changes)
        except Exception as e:
            logger.error(
                "Account update for %s could not be saved: %s",
                reference,
                type(e).__name__,
                extra={"event": "db_save_failed", "workflow": "account_update"},
            )
            raise ToolError(
                "The change could not be saved. Nothing was changed. "
                "Tell the customer and offer a team member."
            ) from e

        self._pending = None
        logger.info("Account %s: %s updated", reference, field, extra={"event": "account_updated"})
        return {"updated": field, **changes}
