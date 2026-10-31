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