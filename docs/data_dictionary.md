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