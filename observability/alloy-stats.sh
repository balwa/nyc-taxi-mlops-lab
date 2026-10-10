#!/usr/bin/env bash
# Alloy's own view of what it sends, as JSON (S5, given): samples sent and failed since it started, and
# the active series in its write-ahead log. That last one is an upper bound for what Grafana Cloud
# counts against the budget: series you've stopped sending stay in the log until Alloy is redeployed
# (or for up to two hours).
# Runs on a lab host; the status and observability workflows use it.
set -euo pipefail
m=$(curl -fsS -m 5 http://127.0.0.1:12345/metrics) || { echo '{"error": "Alloy is not answering on 127.0.0.1:12345"}'; exit 0; }
total() { awk -v n="$1" '$1 == n || index($1, n "{") == 1 { s += $NF } END { printf "%d", s }' <<<"$m"; }
jq -cn --argjson sent "$(total prometheus_remote_storage_samples_total)" \
  --argjson failed "$(total prometheus_remote_storage_samples_failed_total)" \
  --argjson series "$(total prometheus_remote_write_wal_storage_active_series)" \
  '{samples_sent: $sent, samples_failed: $failed, active_series: $series}'
