"""
booking-service
Front door for booking requests. Enforces the other hard rule this project
exists to prove: a retried request (client timeout, double-click, network
blip, k6 retrying a slow response) must never create two bookings.

Idempotency: caller supplies an `Idempotency-Key`. We do a conditional
"put if not exists" into DynamoDB before doing any real work; if the key
already exists, we return the *original* result instead of re-processing.

Also demonstrates the resilience pattern this project is built to test:
a short timeout + limited retries + a simple circuit breaker when calling
inventory-service, so that when Chaos Mesh kills inventory-service pods,
booking-service degrades (fails fast, returns 503) instead of hanging and
taking the whole system down with it.
"""
import os
import time
import uuid
import logging
from datetime import datetime, timedelta

import boto3
import httpx
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, make_asgi_app

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("booking-service")

LOCAL_MODE = os.getenv("LOCAL_MODE", "false").lower() == "true"
INVENTORY_URL = os.getenv("INVENTORY_URL", "http://inventory-service:8000")
IDEMPOTENCY_TABLE = os.getenv("IDEMPOTENCY_TABLE", "ticketguard-idempotency-keys")
QUEUE_URL = os.getenv("BOOKING_EVENTS_QUEUE_URL", "")
INVENTORY_TIMEOUT_S = float(os.getenv("INVENTORY_TIMEOUT_S", "1.5"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))

app = FastAPI(title="booking-service")
app.mount("/metrics", make_asgi_app())

BOOKING_REQUESTS = Counter("booking_requests_total", "Booking attempts", ["result"])
BOOKING_LATENCY = Histogram("booking_latency_seconds", "End-to-end booking latency")

_local_idempotency_store: dict[str, dict] = {}
_circuit_open_until: float = 0.0  # simple circuit breaker: 0 means closed
CIRCUIT_FAILURE_THRESHOLD = 5
CIRCUIT_COOLDOWN_S = 5.0
_recent_failures = 0

dynamodb = None if LOCAL_MODE else boto3.resource("dynamodb")
idem_table = None if LOCAL_MODE else dynamodb.Table(IDEMPOTENCY_TABLE)
sqs = None if LOCAL_MODE else boto3.client("sqs")


class BookingRequest(BaseModel):
    event_id: str
    customer_id: str


class BookingResponse(BaseModel):
    booking_id: str
    seat_id: str
    status: str
    replayed: bool = False


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/bookings", response_model=BookingResponse)
def create_booking(req: BookingRequest, idempotency_key: str = Header(..., alias="Idempotency-Key")):
    with BOOKING_LATENCY.time():
        existing = _get_existing(idempotency_key)
        if existing:
            BOOKING_REQUESTS.labels(result="replayed").inc()
            return BookingResponse(**existing, replayed=True)

        if _circuit_open():
            BOOKING_REQUESTS.labels(result="circuit_open").inc()
            raise HTTPException(status_code=503, detail="inventory temporarily unavailable, try again shortly")

        try:
            seat_id = _reserve_with_retry(req)
        except SoldOut:
            BOOKING_REQUESTS.labels(result="sold_out").inc()
            raise HTTPException(status_code=409, detail="sold_out")
        except InventoryUnavailable:
            BOOKING_REQUESTS.labels(result="inventory_unavailable").inc()
            raise HTTPException(status_code=503, detail="inventory temporarily unavailable, try again shortly")

        booking_id = str(uuid.uuid4())
        result = {"booking_id": booking_id, "seat_id": seat_id, "status": "confirmed"}
        _store_idempotency_result(idempotency_key, result)
        _publish_event(booking_id, req)

        BOOKING_REQUESTS.labels(result="success").inc()
        return BookingResponse(**result)


class SoldOut(Exception):
    pass


class InventoryUnavailable(Exception):
    pass


def _reserve_with_retry(req: BookingRequest) -> str:
    global _recent_failures, _circuit_open_until
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            with httpx.Client(timeout=INVENTORY_TIMEOUT_S) as client:
                resp = client.post(f"{INVENTORY_URL}/inventory/reserve", json={"booking_id": req.customer_id})
            if resp.status_code == 409:
                raise SoldOut()
            resp.raise_for_status()
            _recent_failures = 0  # reset on success
            return resp.json()["seat_id"]
        except SoldOut:
            raise
        except (httpx.TimeoutException, httpx.HTTPError) as e:
            last_error = e
            _recent_failures += 1
            if _recent_failures >= CIRCUIT_FAILURE_THRESHOLD:
                _circuit_open_until = time.time() + CIRCUIT_COOLDOWN_S
                logger.warning("circuit breaker opened for %.1fs after repeated inventory failures", CIRCUIT_COOLDOWN_S)
            backoff = 0.05 * (2 ** attempt)
            time.sleep(backoff)
    logger.error("inventory unreachable after %d attempts: %s", MAX_RETRIES + 1, last_error)
    raise InventoryUnavailable()


def _circuit_open() -> bool:
    return time.time() < _circuit_open_until


def _get_existing(key: str) -> dict | None:
    if LOCAL_MODE:
        return _local_idempotency_store.get(key)
    resp = idem_table.get_item(Key={"idempotency_key": key})
    item = resp.get("Item")
    if not item:
        return None
    return {"booking_id": item["booking_id"], "seat_id": item["seat_id"], "status": item["status"]}


def _store_idempotency_result(key: str, result: dict):
    if LOCAL_MODE:
        _local_idempotency_store[key] = result
        return
    idem_table.put_item(
        Item={
            "idempotency_key": key,
            **result,
            "expires_at": int((datetime.utcnow() + timedelta(hours=24)).timestamp()),
        }
    )


def _publish_event(booking_id: str, req: BookingRequest):
    if LOCAL_MODE or not QUEUE_URL:
        logger.info("booking.created event (local, not published): %s", booking_id)
        return
    sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=f'{{"booking_id": "{booking_id}", "event_id": "{req.event_id}", "customer_id": "{req.customer_id}"}}',
    )