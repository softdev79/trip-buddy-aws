"""Exact trip arithmetic. The LLM never does maths itself; it calls this through an MCP tool."""

from __future__ import annotations

import math


def compute_trip_cost(
    travel_cost_per_person: float,
    room_price_per_night: float,
    daily_spend_per_person: float,
    people: int,
    nights: int,
    budget_per_person: float | None = None,
) -> dict:
    if people < 1 or nights < 1:
        raise ValueError("people and nights must be at least 1")
    rooms_needed = math.ceil(people / 2)  # one room fits 2 people
    stay_share = round(rooms_needed * room_price_per_night * nights / people, 2)
    food_and_fun = round(daily_spend_per_person * nights, 2)
    total = round(travel_cost_per_person + stay_share + food_and_fun, 2)
    result = {
        "rooms_needed": rooms_needed,
        "stay_share_per_person": stay_share,
        "food_and_fun_per_person": food_and_fun,
        "total_per_person": total,
    }
    if budget_per_person is not None:
        result["within_budget"] = total <= budget_per_person
        result["money_left_per_person"] = round(budget_per_person - total, 2)
    return result
