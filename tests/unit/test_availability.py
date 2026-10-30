import pytest

from services import availability


@pytest.mark.parametrize(
    "city, state",
    [("Austin", "TX"), ("austin", "Texas"), ("AUSTIN", "tx"), ("New York", "NY"), ("new york", "New York"), ("Austin,", "TX.")],
)
def test_served_city(city, state):
    assert availability.check_availability(city, state)["available"]


@pytest.mark.parametrize("city, state", [("Boise", "ID"), ("Austin", "CA"), ("Dallas", "TX"), ("", "")])
def test_city_not_served(city, state):
    result = availability.check_availability(city, state)
    assert not result["available"]
    assert "Austin, TX" in result["served_cities"]


def test_five_cities_are_served():
    assert len(availability.service_areas()) == 5


def test_every_city_has_all_three_plans():
    for area in availability.service_areas().values():
        assert set(area["plans"]) == {"Home 300", "Home 500", "Home Gigabit"}


def test_plan_prices_come_from_the_faq():
    assert availability.plan_prices() == {"Home 300": 40.0, "Home 500": 55.0, "Home Gigabit": 75.0}


@pytest.mark.parametrize("text, expected", [("TX", "TX"), ("tx", "TX"), ("Texas", "TX"), ("new york", "NY"), ("District of Columbia", "DC")])
def test_normalize_state(text, expected):
    assert availability.normalize_state(text) == expected
