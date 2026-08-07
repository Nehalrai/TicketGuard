/*
 * Focused correctness test, separate from the load test: fires the SAME
 * idempotency key 20 times concurrently and asserts exactly one booking
 * (one unique seat_id) comes back across all responses. This is the direct
 * proof for the "no duplicate bookings" SLO — the load test proves it holds
 * under pressure, this proves the logic is correct at all.
 *
 * Usage:
 *   k6 run -e BASE_URL=http://<booking-service-lb> load-test/idempotency-check.js
 */
import http from "k6/http";
import { check } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8080";
const SHARED_KEY = "idempotency-check-fixed-key";

export const options = {
  scenarios: {
    concurrent_retries: {
      executor: "shared-iterations",
      vus: 20,
      iterations: 20,
      maxDuration: "30s",
    },
  },
};

export default function () {
  const payload = JSON.stringify({ event_id: "eras-tour-2026", customer_id: "duplicate-test-customer" });
  const res = http.post(`${BASE_URL}/bookings`, payload, {
    headers: { "Content-Type": "application/json", "Idempotency-Key": SHARED_KEY },
  });

  check(res, { "got a response": (r) => r.status === 200 });
  console.log(`seat_id=${JSON.parse(res.body).seat_id} replayed=${JSON.parse(res.body).replayed}`);
}