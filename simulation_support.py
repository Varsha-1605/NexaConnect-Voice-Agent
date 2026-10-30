"""Support for simulations (`lk agent simulate`): a fake, in-memory backend.

During a simulation the agent code runs unchanged. Only the functions that read or write the
database are replaced by in-memory ones that start from the scenario's `userdata`, so a
simulation never touches a real database. Real database behaviour is covered by tests/integration.

Scenario `userdata`:

    accounts:                      # customers that already exist
      - reference: ENR-20261001-AAAA11
        customer_name: Maria Lopez
        phone_number: "+17974517506"
        email: maria@example.com
        service_address: 21 Jane Street
        city: Austin
        state: TX
        postal_code: "78701"
        plan_name: Home 500
        router_rental_selected: true
        bill: high                 # none (default), normal, high, unpaid or pending
    fail_saves: true               # every save raises, like a database outage
    expected_state:                # checked when the call ends
      enrollments: 1               # new enrollments saved
      cancellations: 0
      tickets: 0
      account_changes: 0
      account_status: {ENR-20261001-AAAA11: cancellation_requested}   # optional
"""

import logging
import weakref
from datetime import timedelta

from config import MAX_FAILED_VERIFICATIONS
from services import account_service, availability, billing_service, cancellation_service, enrollment_service
from utils import business_today

logger = logging.getLogger("voice-agent")

# One backend per running job, so the end-of-call check can find it.
_backends: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def backend_for(job_context):
    return _backends.get(job_context)


def install(job_context, userdata: dict) -> "FakeBackend":
    backend = FakeBackend(userdata)
    backend.replace_services()
    _backends[job_context] = backend
    return backend


def use_fake_backend(job_context) -> bool:
    """Call at the start of a job. In a simulation, swap in the fake backend and return True.
    In a real call do nothing and return False."""
    simulation = job_context.simulation_context()
    if not simulation:
        return False
    backend = install(job_context, simulation.userdata())
    job_context.add_shutdown_callback(backend.remove)
    return True


async def check_result(simulation) -> None:
    """At the end of a simulated call: fail it if what was saved isn't what the scenario expects.
    The judge grades the conversation; this grades the data."""
    expected = simulation.userdata().get("expected_state")
    backend = backend_for(simulation.job_context)
    if expected and backend and (problem := backend.difference_from(expected)):
        simulation.fail(reason=problem)


class FakeBackend:
    def __init__(self, userdata: dict):
        self.fail_saves = bool(userdata.get("fail_saves"))
        self.accounts: dict[str, dict] = {}
        self.bills: dict[str, dict] = {}
        for item in userdata.get("accounts", []):
            account = {"enrollment_status": "submitted", "monthly_plan_price": 0.0, **item}
            account["monthly_plan_price"] = availability.plan_prices().get(account["plan_name"], 0.0)
            self.accounts[account["reference"]] = account
            if account.get("bill", "none") != "none":
                self.bills[account["reference"]] = self._make_bill(account, account["bill"])
        self.enrollment_keys: dict[str, str] = {}
        self.ticket_keys: dict[str, str] = {}
        self.new_enrollments: list[str] = []
        self.cancellations: dict[str, tuple] = {}
        self.tickets: list[str] = []
        self.account_changes: list[tuple] = []
        self.failures: list[str] = []
        self._originals: list[tuple] = []

    # ------------------------------------------------------------ bills
    @staticmethod
    def _make_bill(account: dict, scenario: str) -> dict:
        price = availability.plan_prices()[account["plan_name"]]
        charges = [{"description": f"{account['plan_name']} plan", "amount": price}]
        if account.get("router_rental_selected"):
            charges.append({"description": "Router rental", "amount": 8.0})
        if scenario == "high":
            charges.append({"description": "Technician installation fee", "amount": 49.0})
        total = round(sum(c["amount"] for c in charges), 2)
        today = business_today()
        end = today.replace(day=1) - timedelta(days=1)
        paid = scenario in ("normal", "high")
        return {
            "billing_period": f"{end.replace(day=1).isoformat()} to {end.isoformat()}",
            "due_date": (today - timedelta(days=5) if scenario == "unpaid" else today + timedelta(days=10)).isoformat(),
            "total_amount": total,
            "charges": charges,
            "payment_status": "received" if paid else "outstanding" if scenario == "unpaid" else "pending",
            "amount_paid": total if paid else 0.0,
            "amount_outstanding": 0.0 if paid else total,
            "paid_on": today.isoformat() if paid else None,
        }

    # ------------------------------------------------------------ the fake service functions
    def _down(self) -> None:
        if self.fail_saves:
            raise ConnectionError("simulated database outage")

    async def save_enrollment(self, *, idempotency_key, **fields) -> str:
        self._down()
        if idempotency_key in self.enrollment_keys:
            return self.enrollment_keys[idempotency_key]
        reference = enrollment_service.new_reference("ENR")
        self.accounts[reference] = {"reference": reference, "enrollment_status": "submitted", **fields}
        self.enrollment_keys[idempotency_key] = reference
        self.new_enrollments.append(reference)
        return reference

    async def find_account(self, customer_name, service_address, email=None, phone_number=None):
        phone = None
        if phone_number:
            from services import validation

            phone = validation.validate(phone_number=phone_number)["normalized"].get("phone_number")
        spoken = account_service._normalize_address(service_address)
        matches = []
        for account in self.accounts.values():
            if " ".join(account["customer_name"].lower().split()) != " ".join(customer_name.lower().split()):
                continue
            if not ((email and account.get("email") and account["email"].lower() == email.strip().lower())
                    or (phone and account.get("phone_number") == phone)):
                continue
            stored = account_service._normalize_address(account["service_address"])
            if spoken == stored or spoken.startswith(stored + " "):
                matches.append(account)
        matches.sort(key=lambda a: a["enrollment_status"] == account_service.CANCELLED_STATUS)
        return matches[0]["reference"] if matches else None

    async def verification_locked(self, service_address) -> bool:
        key = account_service._normalize_address(service_address)
        return sum(1 for f in self.failures if f == key) >= MAX_FAILED_VERIFICATIONS

    async def record_failed_verification(self, service_address) -> None:
        self.failures.append(account_service._normalize_address(service_address))

    async def get_account(self, reference) -> dict:
        account = self.accounts[reference]
        return {
            "plan_name": account["plan_name"],
            "monthly_plan_price": float(account["monthly_plan_price"]),
            "router_rental_selected": bool(account.get("router_rental_selected")),
            "city": account["city"],
            "state": account["state"],
            "status": account["enrollment_status"],
            "enrolled_on": business_today().isoformat(),
        }

    async def update_account(self, reference, field, changes) -> None:
        self._down()
        account = self.accounts[reference]
        if account["enrollment_status"] == account_service.CANCELLED_STATUS:
            raise ValueError("account has a cancellation request")
        old = account.get(field)
        account.update(changes)
        self.account_changes.append((reference, field, old, changes))

    async def get_bill(self, reference):
        return self.bills.get(reference)

    async def create_ticket(self, enrollment_reference, billing_issue, details, idempotency_key) -> str:
        self._down()
        if idempotency_key not in self.ticket_keys:
            self.ticket_keys[idempotency_key] = enrollment_service.new_reference("TKT")
            self.tickets.append(self.ticket_keys[idempotency_key])
        return self.ticket_keys[idempotency_key]

    async def submit_cancellation(self, reference, reason):
        self._down()
        if reference in self.cancellations:
            number, end = self.cancellations[reference]
            return number, end, True
        number, end = enrollment_service.new_reference("CAN"), cancellation_service.effective_date()
        self.cancellations[reference] = (number, end)
        self.accounts[reference]["enrollment_status"] = account_service.CANCELLED_STATUS
        return number, end, False

    async def get_status(self, reference):
        if reference not in self.cancellations:
            return None
        number, end = self.cancellations[reference]
        return {
            "cancellation_reference": number,
            "cancellation_status": "submitted",
            "service_ends_on": end.isoformat(),
            "submitted_on": business_today().isoformat(),
        }

    # ------------------------------------------------------------ installing and removing
    def replace_services(self) -> None:
        replacements = [
            (enrollment_service, "save_enrollment", self.save_enrollment),
            (account_service, "find_account", self.find_account),
            (account_service, "verification_locked", self.verification_locked),
            (account_service, "record_failed_verification", self.record_failed_verification),
            (account_service, "get_account", self.get_account),
            (account_service, "update_account", self.update_account),
            (billing_service, "get_bill", self.get_bill),
            (billing_service, "create_ticket", self.create_ticket),
            (cancellation_service, "submit_cancellation", self.submit_cancellation),
            (cancellation_service, "get_status", self.get_status),
        ]
        for module, name, fake in replacements:
            self._originals.append((module, name, getattr(module, name)))
            setattr(module, name, fake)

    async def remove(self) -> None:
        """Put the real functions back (the worker process may run a real call next)."""
        for module, name, original in reversed(self._originals):
            setattr(module, name, original)
        self._originals.clear()

    # ------------------------------------------------------------ the end-of-call check
    def difference_from(self, expected: dict) -> str | None:
        """Describe the first way the final state differs from `expected`, or None if it matches."""
        actual = {
            "enrollments": len(self.new_enrollments),
            "cancellations": len(self.cancellations),
            "tickets": len(self.tickets),
            "account_changes": len(self.account_changes),
        }
        for key, value in actual.items():
            if key in expected and expected[key] != value:
                return f"expected {expected[key]} {key.replace('_', ' ')}, found {value}"
        for reference, status in (expected.get("account_status") or {}).items():
            found = self.accounts.get(reference, {}).get("enrollment_status")
            if found != status:
                return f"expected account {reference} to be '{status}', found '{found}'"
        return None
