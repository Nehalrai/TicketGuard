/*
 * Simulates a ticket on-sale: quiet baseline traffic, then a sudden 10x
 * spike (the exact pattern that has taken down Ticketmaster, exam-board
 * portals, and Tatkal booking in real life), held for a few minutes, then
 * a taper. Run this while chaos/pod-kill-inventory.yaml fires partway
 * through the spike plateau to prove SLOs hold under simultaneous load +
 * failure.
 *
 * Usage:
 *   k6 run -e BASE_URL=http://<booking-service-lb> load-test/on-sale-spike.js
 */
import http from "k6/http";
import { check, sleep } from "k6";
import { Counter, Trend } from "k6/metrics";
import { uuidv4 } from "https://jslib.k6.io/k6-utils/1.4.0/index.js";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8080";

const soldOutCount = new Counter("sold_out_responses");
const errorCount = new Counter("error_responses");
const bookingLatency = new Trend("booking_latency_ms");

export const options = {
  scenarios: {
    on_sale_spike: {
      executor: "ramping-vus",
      startVUs: 5,
      stages: [
        { duration: "1m", target: 20 },   // baseline browsing traffic
        { duration: "30s", target: 400 },  // tickets just went on sale
        { duration: "3m", target: 400 },   // sustained spike — chaos gets injected here
        { duration: "1m", target: 50 },    // taper as inventory sells out
        { duration: "30s", target: 0 },
      ],
    },
  },
  thresholds: {
    // These map directly to the SLOs defined in README.md.
    http_req_duration: ["p(95)<300"],
    http_req_failed: ["rate<0.001"], // < 0.1% hard failures (excludes expected 409 sold_out)
  },
};

export default function () {
  const idempotencyKey = uuidv4();
  const payload = JSON.stringify({
    event_id: "eras-tour-2026",
    customer_id: `customer-${__VU}-${__ITER}`,
  });

  const res = http.post(`${BASE_URL}/bookings`, payload, {
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    timeout: "5s",
  });

  bookingLatency.add(res.timings.duration);

  if (res.status === 409) {
    soldOutCount.add(1); // expected once inventory runs out — not a failure
  } else if (res.status >= 500) {
    errorCount.add(1);
  }

  check(res, {
    "status is 200 or expected 409/503": (r) => [200, 409, 503].includes(r.status),
  });

  sleep(Math.random() * 0.5);
}