"""Destination data: DynamoDB on AWS, an in-memory copy for local development and tests.

Set DESTINATIONS_TABLE to use DynamoDB. The table is seeded on startup if it is empty,
so a fresh deployment works without a separate data-loading step.
"""

from __future__ import annotations

import os
from decimal import Decimal

# Prices are from Bengaluru. One room fits 2 people. Travel = return trip per person.
SEED = [
    # place_id, name, trip_type, state, best_months, stay_name, room/night, travel_mode, travel/person, daily/person
    ("GOA", "Goa", "Beach", "Goa", "Nov-Feb", "Sea Breeze Guesthouse", 3000, "Overnight train", 2800, 1500),
    ("GOKARNA", "Gokarna", "Beach", "Karnataka", "Oct-Mar", "Om Beach Huts", 1800, "Overnight bus", 1200, 900),
    ("PONDY", "Pondicherry", "Beach", "Puducherry", "Oct-Mar", "French Quarter Homestay", 2500, "Bus", 1400, 1200),
    ("COORG", "Coorg", "Hills", "Karnataka", "Oct-Jun", "Coffee Estate Cottage", 2800, "Bus", 1000, 1100),
    ("OOTY", "Ooty", "Hills", "Tamil Nadu", "Mar-Jun", "Nilgiri View Lodge", 2200, "Bus", 1000, 1000),
    ("MANALI", "Manali", "Hills", "Himachal Pradesh", "Mar-Jun", "Old Manali Cafe Stay", 2500, "Flight + bus", 9000, 1300),
    ("HAMPI", "Hampi", "Heritage", "Karnataka", "Oct-Feb", "Boulder View Guesthouse", 1500, "Overnight train", 900, 800),
    ("JAIPUR", "Jaipur", "Heritage", "Rajasthan", "Oct-Mar", "Pink City Haveli", 2400, "Flight", 7500, 1200),
    ("RISHIKESH", "Rishikesh", "Adventure", "Uttarakhand", "Oct-Jun", "Ganga Riverside Camp", 1600, "Flight + cab", 8500, 1400),
    ("DANDELI", "Dandeli", "Adventure", "Karnataka", "Oct-May", "Jungle River Camp", 2000, "Bus", 1100, 1600),
]
FIELDS = ["place_id", "name", "trip_type", "state", "best_months", "stay_name",
          "room_price_per_night", "travel_mode", "travel_cost_per_person", "daily_spend_per_person"]
SUMMARY_FIELDS = ["place_id", "name", "trip_type", "best_months"]


def _seed_records() -> list[dict]:
    return [dict(zip(FIELDS, row, strict=True)) for row in SEED]


def _from_dynamo(item: dict) -> dict:
    return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in item.items() if k in FIELDS}


class DestinationStore:
    """Read-only access to destinations, backed by DynamoDB or memory."""

    def __init__(self, table_name: str | None = None):
        self.table_name = table_name if table_name is not None else os.getenv("DESTINATIONS_TABLE", "")
        self._table = None
        self._memory: dict[str, dict] = {}
        if self.table_name:
            import boto3

            self._table = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "us-east-1")).Table(
                self.table_name
            )
            self._seed_dynamo_if_empty()
        else:
            self._memory = {r["place_id"]: r for r in _seed_records()}

    @property
    def backend(self) -> str:
        return "dynamodb" if self._table is not None else "memory"

    def _seed_dynamo_if_empty(self) -> None:
        if self._table.scan(Limit=1, Select="COUNT")["Count"] > 0:
            return
        with self._table.batch_writer() as batch:
            for record in _seed_records():
                batch.put_item(Item={k: (Decimal(str(v)) if isinstance(v, (int, float)) else v)
                                     for k, v in record.items()})

    def _all(self) -> list[dict]:
        if self._table is None:
            return list(self._memory.values())
        items, kwargs = [], {}
        while True:
            page = self._table.scan(**kwargs)
            items.extend(_from_dynamo(i) for i in page["Items"])
            if "LastEvaluatedKey" not in page:
                return items
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def get(self, place: str) -> dict | None:
        """Look a place up by id ('PONDY') or by name ('Pondicherry'), case-insensitively."""
        key = place.strip().upper()
        if self._table is not None:
            item = self._table.get_item(Key={"place_id": key}).get("Item")
            if item:
                return _from_dynamo(item)
        elif key in self._memory:
            return dict(self._memory[key])
        return next((r for r in self._all() if r["name"].upper() == key), None)

    def list_summary(self) -> list[dict]:
        rows = sorted(self._all(), key=lambda r: (r["trip_type"], r["name"]))
        return [{k: r[k] for k in SUMMARY_FIELDS} for r in rows]
