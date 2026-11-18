"""Trip Buddy MCP server over streamable HTTP.

Runs as its own ECS service. Other services reach it at http://mcp.<namespace>.local:8001/mcp
(AWS Cloud Map private DNS). Any MCP client (Claude Desktop, Cursor, the Trip Buddy API) can use it.

    Tools      db_lookup, list_destinations, compute_trip_cost
    Resources  trips://destinations, trips://place/{place_id}
    Prompts    plan_trip
"""

from __future__ import annotations

import json
import os
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from destinations import DestinationStore
from tripbuddy_shared import trip_math
from tripbuddy_shared.logs import get_logger, log_event

log = get_logger("mcp_server")
store = DestinationStore()

mcp = FastMCP(
    "Trip Buddy Server",
    host=os.getenv("HOST", "0.0.0.0"),
    port=int(os.getenv("PORT", "8001")),
    stateless_http=True,   # no sticky sessions needed: any task can answer any request
    json_response=True,
    log_level="WARNING",
)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "store": store.backend})


# ---------------------------------------------------------------- tools
@mcp.tool()
def db_lookup(place: Annotated[str, Field(description="Place name like 'Goa' or id like 'PONDY'")]) -> dict:
    """Fetch a destination's trip type, best months, stay, room price, travel cost and daily spend."""
    record = store.get(place)
    log_event(log, "tool_call", tool="db_lookup", place=place, found=bool(record))
    return record or {"error": f"{place} not found. Use list_destinations to see valid places."}


@mcp.tool()
def list_destinations() -> list[dict]:
    """Return all destinations with trip type and best months."""
    log_event(log, "tool_call", tool="list_destinations")
    return store.list_summary()


@mcp.tool()
def compute_trip_cost(
    travel_cost_per_person: Annotated[float, Field(ge=0, description="Return travel cost for one person, in rupees")],
    room_price_per_night: Annotated[float, Field(ge=0, description="Price of one room for one night (a room fits 2)")],
    daily_spend_per_person: Annotated[float, Field(ge=0, description="Food, local travel and fun per person per day")],
    people: Annotated[int, Field(ge=1, le=20, description="Number of friends travelling (1-20)")],
    nights: Annotated[int, Field(ge=1, le=30, description="Number of nights (1-30)")],
    budget_per_person: Annotated[float | None, Field(description="Optional budget per person, in rupees")] = None,
) -> dict:
    """Compute the trip cost per person with exact arithmetic. One room fits 2 people.
    Returns rooms_needed, stay_share_per_person, food_and_fun_per_person, total_per_person and,
    if a budget is given, within_budget and money_left_per_person (negative = over budget)."""
    result = trip_math.compute_trip_cost(travel_cost_per_person, room_price_per_night,
                                         daily_spend_per_person, people, nights, budget_per_person)
    log_event(log, "tool_call", tool="compute_trip_cost", people=people, nights=nights,
              total=result["total_per_person"])
    return result


# ---------------------------------------------------------------- resources
@mcp.resource("trips://destinations", mime_type="application/json")
def destinations_resource() -> str:
    """All destinations with their trip type and best months."""
    return json.dumps(store.list_summary(), ensure_ascii=False)


@mcp.resource("trips://place/{place_id}", mime_type="application/json")
def place_resource(place_id: str) -> str:
    """One destination's full record, e.g. trips://place/HAMPI."""
    return json.dumps(store.get(place_id) or {"error": f"{place_id} not found"}, ensure_ascii=False)


# ---------------------------------------------------------------- prompts
@mcp.prompt()
def plan_trip(place: str, people: str, nights: str, budget_per_person: str) -> str:
    """Plan a trip: fills the group's details into a well-phrased question."""
    return (f"We are {people} friends with Rs {budget_per_person} each. Can we do {place} for {nights} nights? "
            "Give the cost per person, say whether it fits our budget, and add 2 useful tips.")


if __name__ == "__main__":
    log_event(log, "starting", store=store.backend, port=mcp.settings.port)
    mcp.run(transport="streamable-http")
