"""
notification-service
Consumes booking.created events from SQS and "sends" a confirmation
(stubbed — logs + a metric, since an actual email/SMS provider is out of
scope for this project). Exists mainly to demonstrate the event-driven
decoupling: if this service is down, bookings still succeed, they just
queue up until it recovers — a deliberate design choice, not an oversight.
"""
import os
import json
import time
import logging

import boto3
from prometheus_client import Counter, start_http_server

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("notification-service")

QUEUE_URL = os.getenv("BOOKING_EVENTS_QUEUE_URL", "")
POLL_WAIT_S = int(os.getenv("POLL_WAIT_S", "10"))

NOTIFICATIONS_SENT = Counter("notifications_sent_total", "Notifications processed")

sqs = boto3.client("sqs") if QUEUE_URL else None


def process_message(body: str):
    event = json.loads(body)
    logger.info("sending confirmation for booking %s (customer %s)", event["booking_id"], event["customer_id"])
    NOTIFICATIONS_SENT.inc()


def main():
    start_http_server(8000)  # /metrics on :8000
    if not QUEUE_URL:
        logger.warning("BOOKING_EVENTS_QUEUE_URL not set — idling (local mode has nothing to consume)")
        while True:
            time.sleep(3600)

    logger.info("polling %s", QUEUE_URL)
    while True:
        resp = sqs.receive_message(QueueUrl=QUEUE_URL, MaxNumberOfMessages=10, WaitTimeSeconds=POLL_WAIT_S)
        for msg in resp.get("Messages", []):
            try:
                process_message(msg["Body"])
                sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])
            except Exception:
                logger.exception("failed to process message, leaving for redrive")


if __name__ == "__main__":
    main()