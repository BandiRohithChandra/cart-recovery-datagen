# Validation summary (starter)

Seed: 20261022. Result: **PASS**

| Check | Violations | Labelled anomalies | Unexpected |
|---|---:|---:|---:|
| primary_keys | 0 | 0 | 0 |
| foreign_keys | 0 | 0 | 0 |
| join_consistency | 0 | 0 | 0 |
| allowed_values | 0 | 0 | 0 |
| required_fields | 0 | 0 | 0 |
| natural_keys_unique | 0 | 0 | 0 |
| date_ordering | 0 | 0 | 0 |
| line_total_reconciles | 0 | 0 | 0 |
| cart_total_reconciles | 3 | 3 | 0 |
| order_total_reconciles | 0 | 0 | 0 |
| cart_event_fields | 0 | 0 | 0 |
| consent_lifecycle | 0 | 0 | 0 |
| cart_status_vs_events | 3 | 3 | 0 |
| order_cart_lifecycle | 0 | 0 | 0 |
| abandonment_rule | 0 | 0 | 0 |
| send_decision_consistency | 0 | 0 | 0 |
| send_consent_in_force | 3 | 3 | 0 |
| frequency_caps | 1 | 1 | 0 |
| no_send_after_purchase | 0 | 0 | 0 |
| attribution_unique_per_order | 2 | 2 | 0 |
| attribution_touch_rules | 4 | 4 | 0 |
| attribution_matches_last_touch | 0 | 0 | 0 |
| attribution_revenue_reconciles | 0 | 0 | 0 |
| attribution_counts_reconcile | 1 | 1 | 0 |

## Injected anomaly detection

| Issue type | Injected | Detected |
|---|---:|---:|
| message_after_opt_out | 3 | 3 |
| abandoned_after_purchase | 3 | 3 |
| attribution_double_count | 2 | 2 |
| stale_cart_total | 3 | 3 |

## Row counts

| Table | Rows |
|---|---:|
| customers | 400 |
| consents | 626 |
| sessions | 1620 |
| campaigns | 4 |
| carts | 1000 |
| cart_lines | 2020 |
| cart_events | 4285 |
| message_templates | 200 |
| send_attempts | 200 |
| send_events | 121 |
| orders | 638 |
| attributions | 4 |
| ground_truth | 11 |
