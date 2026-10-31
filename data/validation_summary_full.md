# Validation summary (full)

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
| cart_total_reconciles | 50 | 50 | 0 |
| order_total_reconciles | 0 | 0 | 0 |
| cart_event_fields | 0 | 0 | 0 |
| consent_lifecycle | 0 | 0 | 0 |
| cart_status_vs_events | 50 | 50 | 0 |
| order_cart_lifecycle | 0 | 0 | 0 |
| abandonment_rule | 0 | 0 | 0 |
| send_decision_consistency | 0 | 0 | 0 |
| send_consent_in_force | 50 | 50 | 0 |
| frequency_caps | 0 | 0 | 0 |
| no_send_after_purchase | 0 | 0 | 0 |
| attribution_unique_per_order | 47 | 47 | 0 |
| attribution_touch_rules | 93 | 93 | 0 |
| attribution_matches_last_touch | 0 | 0 | 0 |
| attribution_revenue_reconciles | 0 | 0 | 0 |
| attribution_counts_reconcile | 1 | 1 | 0 |

## Injected anomaly detection

| Issue type | Injected | Detected |
|---|---:|---:|
| message_after_opt_out | 50 | 50 |
| abandoned_after_purchase | 50 | 50 |
| attribution_double_count | 47 | 47 |
| stale_cart_total | 50 | 50 |

## Row counts

| Table | Rows |
|---|---:|
| customers | 20000 |
| consents | 31779 |
| sessions | 81744 |
| campaigns | 20 |
| carts | 50000 |
| cart_lines | 98896 |
| cart_events | 210556 |
| message_templates | 10000 |
| send_attempts | 10000 |
| send_events | 9491 |
| orders | 31700 |
| attributions | 357 |
| ground_truth | 197 |
