"""
inventory-service
Owns seat/ticket availability. The one hard rule this service exists to enforce:
seats must never go negative, even under thousands of concurrent decrement requests.

Two backends:
- DynamoDB (default, cloud-native): atomic decrement via a conditional update
  (`seats_available > 0`), so the race-condition-proofing happens server-side
  in DynamoDB itself, not in application code.
- In-memory (LOCAL_MODE=true): a threading.Lock-guarded dict, for running the
  whole stack on `kind` without needing real AWS credentials during development.
"""
import os
import time
import threading
import logging

import boto3
from botocore.exceptions import ClientError
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, make_asgi_app

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("inventory-service")

LOCAL_MODE = os.getenv("LOCAL_MODE", "false").lower() == "true"
TABLE_NAME = os.getenv("SEATS_TABLE", "ticketguard-seats")
DEFAULT_EVENT_SEATS = int(os.getenv("DEFAULT_EVENT_SEATS", "500"))

app = FastAPI(title="inventory-service")
app.mount("/metrics", make_asgi_app())

RESERVE_REQUESTS = Counter("inventory_reserve_requests_total", "Reserve attempts", ["result"])
RESERVE_LATENCY = Histogram("inventory_reserve_latency_seconds", "Reserve request latency")


class LocalStore:
    """In-memory stand-in for DynamoDB's conditional-update behavior."""

    def __init__(self, seed_seats: int):
        self._lock = threading.Lock()
        self._seats = {f"seat-{i}": True for i in range(seed_seats)}  # True = available

    def reserve_one(self) -> str:
        with self._lock:
            for seat_id, available in self._seats.items():
                if available:
                    self._seats[seat_id] = False
                    return seat_id
        raise SoldOutError()

    def available_count(self) -> int:
        with self._lock:
            return sum(1 for v in self._seats.values() if v)


class SoldOutError(Exception):
    pass


local_store = LocalStore(DEFAULT_EVENT_SEATS) if LOCAL_MODE else None
dynamodb = None if LOCAL_MODE else boto3.resource("dynamodb")
table = None if LOCAL_MODE else dynamodb.Table(TABLE_NAME)


class ReserveRequest(BaseModel):
    booking_id: str


class ReserveResponse(BaseModel):
    seat_id: str
    reserved_at: float


@app.get("/health")
def health():
    return {"status": "ok", "mode": "local" if LOCAL_MODE else "dynamodb"}


@app.get("/inventory/available")
def available():
    if LOCAL_MODE:
        return {"available": local_store.available_count()}
    # DynamoDB path: maintain a single aggregate counter item (seat_id="__count__")
    # for O(1) reads; the authoritative per-seat truth still lives in the conditional
    # decrement below.
    resp = table.get_item(Key={"seat_id": "__count__"})
    return {"available": int(resp.get("Item", {}).get("count", 0))}


@app.post("/inventory/reserve", response_model=ReserveResponse)
def reserve(req: ReserveRequest):
    with RESERVE_LATENCY.time():
        try:
            if LOCAL_MODE:
                seat_id = local_store.reserve_one()
            else:
                seat_id = _reserve_dynamodb(req.booking_id)
        except SoldOutError:
            RESERVE_REQUESTS.labels(result="sold_out").inc()
            raise HTTPException(status_code=409, detail="sold_out")
        except Exception:
            RESERVE_REQUESTS.labels(result="error").inc()
            logger.exception("reserve failed")
            raise HTTPException(status_code=500, detail="internal_error")

    RESERVE_REQUESTS.labels(result="success").inc()
    return ReserveResponse(seat_id=seat_id, reserved_at=time.time())


def _reserve_dynamodb(booking_id: str) -> str:
    """
    Atomic decrement guarded by a condition expression: DynamoDB rejects the
    write if `count <= 0`, so two concurrent requests can never both succeed
    against the last remaining seat. This is what makes overselling structurally
    impossible instead of "unlikely."
    """
    try:
        resp = table.update_item(
            Key={"seat_id": "__count__"},
            UpdateExpression="SET #c = #c - :one",
            ConditionExpression="#c > :zero",
            ExpressionAttributeNames={"#c": "count"},
            ExpressionAttributeValues={":one": 1, ":zero": 0},
            ReturnValues="UPDATED_NEW",
        )
        remaining = resp["Attributes"]["count"]
        return f"seat-{remaining}"
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise SoldOutError()
        raise