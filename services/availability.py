import os
import re
from functools import lru_cache

FAQ_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "F&Q Internet Plan.md"
)

US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA",
    "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[.,]", "", text)).strip().lower()


def normalize_state(state: str) -> str:
    """Accept 'TX', 'tx', or 'Texas' and return 'TX'."""
    s = _norm(state)
    return US_STATES.get(s, s.upper())


@lru_cache(maxsize=1)
def service_areas() -> dict[tuple[str, str], dict]:
    """Parse the FAQ Service Areas table into {(city, state): {...}}."""
    with open(FAQ_PATH, encoding="utf-8") as f:
        text = f.read()

    section = text.split("## Service Areas", 1)[1].split("\n## ", 1)[0]
    areas: dict[tuple[str, str], dict] = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 3 or cells[0] == "City" or set(cells[0]) <= {"-", " "}:
            continue
        city, state, plans = cells
        areas[(_norm(city), normalize_state(state))] = {
            "city": city,
            "state": normalize_state(state),
            "plans": [p.strip() for p in plans.split(",")],
        }
    return areas


@lru_cache(maxsize=1)
def plan_prices() -> dict[str, float]:
    """Parse the FAQ's Available Plans list into {plan name: monthly price}."""
    with open(FAQ_PATH, encoding="utf-8") as f:
        section = f.read().split("## Available Plans", 1)[1].split("\n## ", 1)[0]
    return {
        name: float(price)
        for name, price in re.findall(
            r"\*\*(.+?) \(NC-\d+\):\*\*.*?\$(\d+(?:\.\d+)?) per month", section
        )
    }


def all_plan_names() -> set[str]:
    return {plan for area in service_areas().values() for plan in area["plans"]}


def check_availability(city: str, state: str) -> dict:
    area = service_areas().get((_norm(city), normalize_state(state)))
    if area:
        return {"available": True, **area}
    return {
        "available": False,
        "served_cities": [f"{a['city']}, {a['state']}" for a in service_areas().values()],
    }
