# Decisions and Assumptions

Each item below fills a gap in the problem statement or fixes a rule. Code, validation and metrics must follow this file.

## 1. Scope
- Output is a synthetic dataset plus documentation, validation and metrics. There is no UI.
- All data is fully synthetic. No external or real data is used.

## 2. Reproducibility
- Fixed seed: 20261022, used through one random.Random instance. No wall-clock time is used in generation.
- Scale is parameterized (starter and full datasets use the same generator).
- Data period: 2026-01-01 to 2026-09-30 (UTC).

## 3. Volumes (full dataset)
- 50,000 carts, of which 20,000 are abandoned.
- 10,000 SendAttempt rows (sent and suppressed together), spread over a small number of Campaigns (about 20).
- The statement says "10,000 campaigns/sends". We read this as 10,000 sends, because 10,000 separate campaigns would make the Campaign table meaningless.

## 4. Abandonment
- A cart is abandoned when it has had no activity for 60 minutes and has no order.
- abandoned_at = last_activity_at + 60 minutes.
- Carts with activity inside the window stay active (this is the boundary case).
- Carts that are not abandoned are bought directly, 1 to 59 minutes after their last activity (most within 30 minutes, some near the 60-minute boundary). The number of abandoned carts is exactly round(n_carts x abandon_rate).

## 5. Consent and suppression
- Consent is per channel and stored as append-only events with effective dates.
- A send is allowed only if the consent row in force at attempted_at is opt_in.
- A customer with no consent row for the channel is treated as not consented.
- Suppressed attempts are recorded with a suppression_reason, never deleted.

## 6. Frequency caps
- At most 1 message per channel per customer per 24 hours.
- At most 3 messages per customer per 7 days, across channels.
- Attempts are processed in scheduled_at order; ties are broken by lowest send_id.
- An attempt that would breach a cap is suppressed with frequency_cap_24h or frequency_cap_7d.

## 7. Campaign sequence
- Up to 3 messages per abandoned cart: email at +60 minutes, email at +26 hours, SMS at +72 hours.
- The second email is sent 26 hours after abandonment (25 hours after the first), so it does not collide with the 1-email-per-24-hours cap.
- Subject and body variants A and B are assigned deterministically from the seed.
- A pending message is suppressed with purchased_before_send if the cart is purchased before its scheduled time.

## 8. Attribution (deterministic, last-touch)
- Window: 7 days after the touch, where a touch is a click or open on a sent message to the same customer.
- Choose the latest click; if there are no clicks, the latest open; ties go to the lowest send_id.
- One attribution row per order at most, so revenue is never double-counted.
- Late purchases (outside the window) are valid orders with no attribution.
- Recovery purchases happen in a new session, on a different device from the cart's session 60% of the time when the customer has another device.
- About 2% of orders are cancelled; attribution only considers placed orders.
- Follow-up events (sends, purchases) may fall after 2026-09-30. The data period applies to cart creation.
- A touch counts for any cart of the same customer, not only the cart that was messaged. It must be at least 1 minute and at most 7 days before the order.

## 9. Derived values
- line_total = unit_price x quantity.
- cart_total = sum of line_total.
- order_total = cart_total at purchase time.
- status and abandoned_at come from CartEvent history, never generated independently.

## 10. Outcomes
- Delivery, open, click and purchase outcomes are produced by documented rules and probabilities that depend on the cart, channel, variant and timing, not by independent random assignment.

## 11. Labelled anomalies (injected after the valid baseline)
1. message_after_opt_out: a send that happens after an opt-out was in force.
2. abandoned_after_purchase: an abandoned event after a purchased event.
3. attribution_double_count: a second attribution row for one order across campaigns.
4. stale_cart_total: a quantity updated without recomputing the cart total.
- Each anomaly touches only its target rows and is recorded in ground_truth.csv, which is never used as an input to generation or validation of features.
- Anomaly counts: 3 per type in the starter set and 50 per type in the full set. An injected attribution_double_count row may also break the 7-day window or same-customer rule, because it is a deliberately wrong row. ground_truth is a separate output and is never read by any generator or feature step.
 The attribution_double_count count is limited by the number of orders eligible for a cross-campaign duplicate, so it can be lower (1 on starter, 47 on full).


## 12. ID conventions
- Given: CUS-000001, CART-2026-000001, CMP-2026-000001, MSG-<cart-id>-01, SEND-2026-000001, ORD-2026-000001.
- Added by us: CON-, SES-2026-, DEV-, CLN-, CEV-, SEV-, ATR-2026-.
- Counters are zero-padded and IDs are immutable.

## 13. Deviations from the statement
- Added supporting tables CartEvent and SendEvent to keep history.
- No bridge table, because MessageTemplate already links Campaign and Cart (see erd.md).
- Exports are CSV, JSON and a SQLite-compatible SQL seed. JSON decimals are strings to keep exact values. Rows are sorted by primary key and files carry no generation time, so output is byte-identical for the same seed.
- schema.sql enforces primary keys, foreign keys, enums and positive-value checks, but deliberately not one attribution per order, so the injected attribution_double_count row can load. validate.py enforces that rule instead.
- validate.py reads the exported CSV files, runs all checks without reading ground_truth.csv, then compares the findings with the labels. A violation is "labelled" only when a check expected for that anomaly type flags the record the ground truth names. Unexplained violations, or an injected anomaly that no check detects, make validation fail. Its summary is written to data/validation_summary_<scale>.json and .md, outside the dataset folder so it does not change the manifest checksums.