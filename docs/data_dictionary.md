# Data Dictionary

All data is synthetic. IDs are immutable and zero-padded. Timestamps are UTC, ISO 8601.

## Customer
Master table. One row per customer. Consent history lives in the Consent table.

| Field | Type | Required | Allowed / format | Unique | Validation |
|---|---|---|---|---|---|
| customer_id | string | yes | CUS-000001 | PK | matches ^CUS-\d{6}$, immutable |
| first_name | string | yes | synthetic name list | no | non-empty |
| email | string | yes | synthetic, @example.com | yes | valid format, lowercase |
| phone | string | optional | E.164, fictional number range | yes | required if the customer ever has SMS consent |
| country_code | enum | yes | IN, SA, AE, US | no | one of the allowed values |
| created_at | timestamp | yes | UTC | no | earlier than any session, consent or cart of this customer |



## Consent
Append-only history of consent changes. A withdrawal is a new row, and rows are never edited.

| Field | Type | Required | Allowed / format | Unique | Validation |
|---|---|---|---|---|---|
| consent_id | string | yes | CON-000001 | PK | matches ^CON-\d{6}$, immutable |
| customer_id | string | yes | existing CUS- id | no | FK to Customer |
| channel | enum | yes | email, sms | no | one of the allowed values |
| status | enum | yes | opt_in, opt_out | no | same status can't repeat back to back |
| effective_from | timestamp | yes | UTC | no | at or after customer.created_at; unique per (customer_id, channel) |
| recorded_at | timestamp | yes | UTC | no | at or after effective_from |
| source | enum | yes | signup, checkout, preference_center, unsubscribe_link, sms_stop | no | sms_stop only for the sms channel |

Lifecycle: for each customer and channel, opt_in and opt_out alternate in order of effective_from. There is no effective_to column, because it is derived from the next event's effective_from.


## Session
One row per visit. A customer can have many sessions across several devices (1:N from Customer).

| Field | Type | Required | Allowed / format | Unique | Validation |
|---|---|---|---|---|---|
| session_id | string | yes | SES-2026-000001 | PK | matches ^SES-\d{4}-\d{6}$, immutable |
| customer_id | string | yes | existing CUS- id | no | FK to Customer |
| device_id | string | yes | DEV-000001 | no | 1 to 3 devices per customer |
| device_type | enum | yes | mobile, desktop, tablet | no | one of the allowed values |
| started_at | timestamp | yes | UTC | no | at or after customer.created_at |
| last_activity_at | timestamp | yes | UTC | no | at or after started_at |

Assumption: every session belongs to an identified customer (no anonymous sessions), because consent checks need a known contact.



## Cart
One row per cart, holding its current state. The full history lives in CartEvent.

| Field | Type | Required | Allowed / format | Unique | Validation |
|---|---|---|---|---|---|
| cart_id | string | yes | CART-2026-000001 | PK | matches ^CART-\d{4}-\d{6}$, immutable |
| customer_id | string | yes | existing CUS- id | no | FK to Customer |
| session_id | string | yes | the session that created the cart | no | FK to Session; the session's customer must match |
| currency | enum | yes | INR, SAR, AED, USD | no | matches the customer's country |
| status | enum | yes | active, abandoned, recovered, purchased | no | derived from CartEvent history |
| created_at | timestamp | yes | UTC | no | at or after session.started_at |
| last_activity_at | timestamp | yes | UTC | no | equals the latest cart-editing CartEvent time (cart_created, line_added, quantity_updated, line_removed); purchased, abandoned and recovered events do not change it |
| abandoned_at | timestamp | optional | last_activity_at + 60 minutes | no | null unless abandoned; never after a purchase |
| cart_total | decimal(12,2) | yes | currency units | no | equals the sum of its CartLine line_total values |

Lifecycle: active -> abandoned -> recovered, or active -> purchased. A cart that is abandoned and later bought, whether or not any message gets credit, is "recovered"; attribution decides credit separately. A cart bought without ever being abandoned is "purchased".


## CartLine
One row per product in a cart (1:N from Cart).

| Field | Type | Required | Allowed / format | Unique | Validation |
|---|---|---|---|---|---|
| cart_line_id | string | yes | CLN-000001 | PK | matches ^CLN-\d{6}$, immutable |
| cart_id | string | yes | existing CART- id | no | FK to Cart |
| product_sku | string | yes | SKU-0001 to SKU-0300 from a synthetic catalog | no | unique within a cart |
| product_name | string | yes | synthetic catalog name | no | non-empty, used for message personalization |
| unit_price | decimal(10,2) | yes | currency units | no | greater than 0 |
| quantity | integer | yes | 1 to 10 | no | current quantity after any updates |
| line_total | decimal(12,2) | yes | currency units | no | equals unit_price x quantity |


## CartEvent
Supporting table (not in the statement's core entity list). Append-only history of everything that happens to a cart, so nothing is overwritten.

| Field | Type | Required | Allowed / format | Unique | Validation |
|---|---|---|---|---|---|
| event_id | string | yes | CEV-000001 | PK | matches ^CEV-\d{6}$, immutable |
| cart_id | string | yes | existing CART- id | no | FK to Cart |
| session_id | string | yes | the session where the event happened | no | FK to Session; may differ from the cart's creating session (multiple devices) |
| event_type | enum | yes | cart_created, line_added, quantity_updated, line_removed, abandoned, recovered, purchased | no | one of the allowed values |
| cart_line_id | string | optional | existing CLN- id | no | required for line events, null otherwise |
| old_quantity | integer | optional | 1 to 10 | no | only for quantity_updated |
| new_quantity | integer | optional | 1 to 10 | no | only for quantity_updated; must differ from old_quantity |
| occurred_at | timestamp | yes | UTC | no | non-decreasing per cart |

Lifecycle rule: after a purchased event, no abandoned event is valid. The injected anomaly "cart considered abandoned after purchase" breaks this on purpose and is recorded in ground_truth.csv.



## Campaign
One row per recovery campaign. The rules in force for its sends are stored here for traceability.

| Field | Type | Required | Allowed / format | Unique | Validation |
|---|---|---|---|---|---|
| campaign_id | string | yes | CMP-2026-000001 | PK | matches ^CMP-\d{4}-\d{6}$, immutable |
| name | string | yes | free text | yes | non-empty |
| status | enum | yes | draft, active, completed, cancelled | no | one of the allowed values |
| start_date | date | yes | UTC date | no | before or equal to end_date |
| end_date | date | yes | UTC date | no | after or equal to start_date |
| abandonment_window_minutes | integer | yes | 60 | no | greater than 0; a cart is only eligible after this much inactivity |
| attribution_window_days | integer | yes | 7 | no | greater than 0; orders count only within this window after a click or open |
| max_sends_per_channel_per_24h | integer | yes | 1 | no | greater than 0 |
| max_sends_per_7d | integer | yes | 3 | no | greater than or equal to max_sends_per_channel_per_24h |

Lifecycle: draft -> active -> completed, or draft/active -> cancelled. A campaign covers carts abandoned between start_date and end_date. Its messages may be scheduled up to 72 hours after end_date (the length of the sequence); SendAttempts are not created before start_date or for a draft or cancelled campaign.



## MessageTemplate
One row per planned message for a cart (ID follows MSG-<cart-id>-NN). The template is rendered with the customer's and cart's details, so each row is the personalized message for one cart. Campaign and Cart are both 1:N parents, so no bridge table is needed.

| Field | Type | Required | Allowed / format | Unique | Validation |
|---|---|---|---|---|---|
| message_id | string | yes | MSG-CART-2026-000001-01 | PK | matches ^MSG-CART-\d{4}-\d{6}-\d{2}$, immutable |
| campaign_id | string | yes | existing CMP- id | no | FK to Campaign |
| cart_id | string | yes | existing CART- id | no | FK to Cart; the cart must be abandoned |
| sequence | integer | yes | 1 to 3 | no | matches the NN suffix; unique per cart |
| channel | enum | yes | email, sms | no | one of the allowed values |
| variant | enum | yes | A, B | no | one of the allowed values (A/B test) |
| template_code | string | yes | e.g. EMAIL_1H_A, EMAIL_26H_B, SMS_72H_A | no | channel in the code matches channel |
| delay_minutes | integer | yes | 60, 1560, 4320 | no | send is due this long after abandoned_at |
| subject | string | optional | text | no | required for email, null for sms |
| body | string | yes | text rendered with first_name and product_name | no | non-empty; SMS at most 160 characters |
| created_at | timestamp | yes | UTC | no | at or after the cart's abandoned_at |


## SendAttempt
One row per attempt to send a planned message, including attempts that were suppressed. Never edited; what happens after a send is recorded in SendEvent.

| Field | Type | Required | Allowed / format | Unique | Validation |
|---|---|---|---|---|---|
| send_id | string | yes | SEND-2026-000001 | PK | matches ^SEND-\d{4}-\d{6}$, immutable |
| message_id | string | yes | existing MSG- id | yes | FK to MessageTemplate; one attempt per message |
| scheduled_at | timestamp | yes | UTC | no | equals the cart's abandoned_at + the message's delay_minutes |
| attempted_at | timestamp | yes | UTC | no | at or after scheduled_at |
| decision | enum | yes | sent, suppressed | no | one of the allowed values |
| suppression_reason | enum | optional | opted_out, no_consent_record, frequency_cap_24h, frequency_cap_7d, purchased_before_send | no | required when decision is suppressed, null when sent |
| consent_id_checked | string | optional | existing CON- id | no | FK to Consent; the consent row in force at attempted_at, null if none exists |

Rules:
- A send is valid only if the consent row in force for that channel at attempted_at is opt_in, and no frequency cap is breached.
- The injected anomaly "message sent after opt-out" produces a sent row that breaks this rule, and it is recorded in ground_truth.csv.



## SendEvent
Supporting table (not in the statement's core entity list). Append-only record of what happens after a send. Attribution reads clicks and opens from here.

| Field | Type | Required | Allowed / format | Unique | Validation |
|---|---|---|---|---|---|
| send_event_id | string | yes | SEV-000001 | PK | matches ^SEV-\d{6}$, immutable |
| send_id | string | yes | existing SEND- id | no | FK to SendAttempt; the attempt's decision must be sent |
| event_type | enum | yes | delivered, bounced, opened, clicked | no | one of the allowed values |
| occurred_at | timestamp | yes | UTC | no | at or after the send's attempted_at |

Rules:
- Suppressed attempts have no SendEvent rows.
- Each sent attempt has exactly one delivered or bounced event.
- opened and clicked events are only valid after a delivered event, and never after a bounced one.
- A send can have several opened or clicked events, and attribution uses the earliest qualifying one.



## Order
One row per purchase. Each order comes from exactly one cart, and each cart has at most one order (1:1, optional from Cart).

| Field | Type | Required | Allowed / format | Unique | Validation |
|---|---|---|---|---|---|
| order_id | string | yes | ORD-2026-000001 | PK | matches ^ORD-\d{4}-\d{6}$, immutable |
| customer_id | string | yes | existing CUS- id | no | FK to Customer; must match the cart's customer |
| cart_id | string | yes | existing CART- id | yes | FK to Cart; one order per cart |
| session_id | string | yes | existing SES- id | no | FK to Session; the session where the purchase happened, which may be on a different device from the cart's session |
| currency | enum | yes | INR, SAR, AED, USD | no | equals the cart's currency |
| order_total | decimal(12,2) | yes | currency units | no | equals the cart's total at purchase time (sum of its line totals) |
| status | enum | yes | placed, cancelled | no | one of the allowed values |
| placed_at | timestamp | yes | UTC | no | after the cart's created_at; equals the cart's purchased event time |

Rules:
- A cart with an order must have a purchased or recovered CartEvent at placed_at.
- An order is a late purchase when it is placed after the attribution window has ended for every send to that cart. These are valid orders that get no attribution.
- Order lines are not stored separately. They are the cart's lines at purchase time.


## Attribution
One row per attributed order. It links an order to the single send credited for it, using one documented deterministic rule.

| Field | Type | Required | Allowed / format | Unique | Validation |
|---|---|---|---|---|---|
| attribution_id | string | yes | ATR-2026-000001 | PK | matches ^ATR-\d{4}-\d{6}$, immutable |
| order_id | string | yes | existing ORD- id | yes | FK to Order; one attribution per order, so revenue is never double-counted |
| send_id | string | yes | existing SEND- id | no | FK to SendAttempt; the attempt's decision must be sent |
| send_event_id | string | yes | existing SEV- id | no | FK to SendEvent; the click or open that earned the credit |
| touch_type | enum | yes | click, open | no | must match the event_type of send_event_id |
| lag_minutes | integer | yes | minutes | no | order.placed_at minus the touch's occurred_at; greater than 0 and at most attribution_window_days x 1440 |
| attributed_revenue | decimal(12,2) | yes | currency units | no | equals order.order_total |

Attribution rule (deterministic, last-touch):
1. Consider only placed orders that have at least one qualifying touch, meaning a click or open on a sent message to the same customer, occurring before the order and within the attribution window (7 days).
2. Prefer the latest click. If there are no clicks, use the latest open.
3. If several touches tie on time, pick the lowest send_id.
4. Orders with no qualifying touch, including late purchases, get no attribution row.

Reconciliation: the sum of attributed_revenue by campaign must be at most total order revenue, and the number of attribution rows must equal the number of distinct orders attributed.

The injected anomaly "attribution double-counted across campaigns" adds a second row for the same order, which deliberately breaks the order_id uniqueness. It is recorded in ground_truth.csv.