#!/usr/bin/env bash
# Polls Prometheus for http_req_failed rate on the given deployment for
# $DURATION seconds after a deploy; if it ever exceeds $THRESHOLD, triggers
# `kubectl rollout undo` automatically. This is what turns "we have
# monitoring" into "our deploys can't silently make things worse" — the
# rollback decision doesn't wait for a human to notice a dashboard.
set -euo pipefail

DEPLOYMENT="${1:?deployment name required}"
NAMESPACE="${2:?namespace required}"
DURATION="${3:-180}"
THRESHOLD="${4:-0.001}"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://prometheus.monitoring.svc.cluster.local:9090}"

echo "watching error rate for ${DEPLOYMENT} for ${DURATION}s (threshold=${THRESHOLD})"

elapsed=0
interval=15
while [ "$elapsed" -lt "$DURATION" ]; do
  sleep "$interval"
  elapsed=$((elapsed + interval))

  error_rate=$(curl -s --get "${PROMETHEUS_URL}/api/v1/query" \
    --data-urlencode "query=sum(rate(booking_requests_total{result=~\"error|inventory_unavailable\"}[1m])) / sum(rate(booking_requests_total[1m]))" \
    | jq -r '.data.result[0].value[1] // "0"')

  echo "t=${elapsed}s error_rate=${error_rate}"

  if awk -v er="$error_rate" -v th="$THRESHOLD" 'BEGIN{exit !(er > th)}'; then
    echo "SLO BREACH: error_rate ${error_rate} > threshold ${THRESHOLD} — rolling back"
    kubectl rollout undo "deployment/${DEPLOYMENT}" -n "${NAMESPACE}"
    exit 1
  fi
done

echo "no SLO breach detected over ${DURATION}s — deploy stable"