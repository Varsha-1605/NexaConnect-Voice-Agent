import logging
from datetime import date

from livekit.agents import RunContext, ToolError, function_tool

from services import availability, enrollment_service, validation
from utils import business_now, call_id, initials, publish_reference, spell_reference

from .workflow_task import CallState, WorkflowOutcome, WorkflowResult, WorkflowTask
from .shared_tools import search_knowledge_base, validate_customer_details

logger = logging.getLogger("voice-agent")


def _confirmation(reference: str, installation_date: str | None) -> str:
    text = f"You're enrolled! Your enrollment reference is {spell_reference(reference)}."
    if installation_date:
        chosen = date.fromisoformat(installation_date)
        text += f" Your preferred installation date is {chosen:%A, %B} {chosen.day}."
    return text


class EnrollmentWorkflow(WorkflowTask):
    """New service enrollment. Spec: docs/enrollment_workflow.md."""

    prompt_file = "enrollment_prompt.md"
    opening = "Happy to help! Would you like to check if we serve your area, or enroll in a plan today?"
    shared_tools = [validate_customer_details, search_knowledge_base]

    @function_tool()
    async def get_current_date(self, context: RunContext[CallState]) -> str:
        """Get the current date, weekday and local time. Always call it before
        offering installation dates or turning relative dates like "next Monday"
        or "tomorrow" into YYYY-MM-DD. Never assume the year."""
        return business_now().strftime("%A, %B %d, %Y at %I:%M %p")

    @function_tool()
    async def check_service_availability(
        self, context: RunContext[CallState], city: str, state: str
    ) -> dict:
        """Check whether NexaConnect serves a city. Returns `available` and `plans`.
        If not available, returns `served_cities` so you can check whether the
        customer meant one of them (e.g. "NYC" means New York).

        Args:
            city: City name, e.g. "Austin".
            state: State name or 2-letter code, e.g. "Texas" or "TX".
        """
        return availability.check_availability(city, state)

    @function_tool()
    async def submit_enrollment(
        self,
        context: RunContext[CallState],
        customer_name: str,
        phone_number: str,
        service_address: str,
        city: str,
        state: str,
        postal_code: str,
        plan_name: str,
        monthly_plan_price: float,
        router_rental_selected: bool,
        consent_confirmed: bool,
        email: str | None = None,
        preferred_installation_date: str | None = None,
    ) -> None:
        """Save the enrollment and tell the customer the reference. It speaks the
        confirmation and ends the workflow itself. Call only after reading the full
        summary to the customer and receiving their explicit consent. "One moment while I
        submit your enrollment" is spoken automatically: say nothing before calling this.

        Args:
            customer_name: Customer's full name.
            phone_number: US phone number.
            service_address: Street address.
            city: City of the service address.
            state: State of the service address.
            postal_code: 5-digit ZIP code.
            plan_name: Selected plan, e.g. "Home 500".
            monthly_plan_price: Monthly plan price in USD as quoted to the customer, excluding router.
            router_rental_selected: Whether the customer wants to rent a router.
            consent_confirmed: True only if the customer explicitly agreed to the summary.
            email: Email address, if given.
            preferred_installation_date: Preferred installation date as YYYY-MM-DD, if given.
        """
        context.disallow_interruptions()

        if not consent_confirmed:
            raise ToolError("The customer has not given explicit consent. Ask for consent first.")

        check = validation.validate(
            customer_name=customer_name,
            phone_number=phone_number,
            email=email,
            service_address=service_address,
            postal_code=postal_code,
            plan_name=plan_name,
            preferred_installation_date=preferred_installation_date,
        )
        if not check["valid"]:
            raise ToolError(f"Fix these details with the customer first: {check['errors']}")

        area = availability.check_availability(city, state)
        if not area["available"]:
            raise ToolError("NexaConnect does not serve this city. Do not enroll.")

        details = check["normalized"]
        if details["plan_name"] not in area["plans"]:
            raise ToolError(f"{details['plan_name']} is not offered in {area['city']}.")

        context.session.say("One moment while I submit your enrollment.")
        try:
            reference = await enrollment_service.save_enrollment(
                idempotency_key=f"{call_id()}:{details['phone_number']}",
                customer_name=details["customer_name"],
                phone_number=details["phone_number"],
                email=details.get("email"),
                service_address=details["service_address"],
                city=area["city"],
                state=area["state"],
                postal_code=details["postal_code"],
                plan_name=details["plan_name"],
                monthly_plan_price=monthly_plan_price,
                router_rental_selected=router_rental_selected,
                preferred_installation_date=details.get("preferred_installation_date"),
            )
        except Exception as e:
            logger.error(
                "Enrollment could not be saved: %s",
                type(e).__name__,
                extra={"event": "db_save_failed", "workflow": "enrollment"},
            )
            raise ToolError(
                "The enrollment could not be saved. Nothing was submitted. Tell the customer "
                "the enrollment was not submitted and offer a team member."
            ) from e

        # Set only after a real save, so an availability check alone doesn't block a sign-up.
        context.userdata.enrollment_completed = True
        logger.info("Enrollment %s saved", reference, extra={"event": "enrollment_saved"})

        # Not awaited (it would deadlock inside this speech); returning None skips the model's reply.
        speech = context.session.say(
            _confirmation(reference, details.get("preferred_installation_date")),
            allow_interruptions=False,
        )
        await publish_reference("Enrollment", reference)
        summary = (
            f"Enrolled {initials(details['customer_name'])} in {details['plan_name']} in {area['city']}, "
            f"{area['state']}. Reference {reference}. "
            "The customer was already given the reference and preferred date."
        )
        def complete_workflow(_) -> None:
            if not self.done():  # a repeated tool call must not complete the task twice
                self.complete(WorkflowResult(WorkflowOutcome.COMPLETED, summary))

        speech.add_done_callback(complete_workflow)
