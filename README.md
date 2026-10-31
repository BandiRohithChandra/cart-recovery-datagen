# Cart Recovery Synthetic Data Generator

Synthetic dataset for an abandoned-cart recovery workflow: carts and abandonment, contact consent, frequency caps, campaign sends, delivery/open/click events, orders and last-touch attribution. All data is synthetic. No external or real data is used.

## Quick start

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python generate.py --scale starter     # 1,000 carts
python validate.py --scale starter
python reproduce.py --scale starter
python metrics.py --scale starter
```

Replace `starter` with `full` for the full dataset (50,000 carts, about 70 seconds). The starter and full datasets use the same generator; only the scale parameters in `config.py` differ.

Fixed seed: **20261022**, through one `random.Random` instance. No wall-clock time is used, so the same seed gives byte-identical files.

## Commands

| Command | What it does |
|---|---|
| `python generate.py --scale starter\|full` | Generates all tables, injects labelled anomalies, writes `data/<scale>/` |
| `python validate.py --scale ...` | Runs 24 checks on the exported CSVs, then compares findings with `ground_truth` |
| `python reproduce.py --scale ...` | Generates twice, compares row counts and SHA-256 of every file |
| `python metrics.py --scale ...` | Funnel, send outcomes by channel and variant, attributed revenue, reconciliation |

## Output layout

```
data/<scale>/
  tables/        CSV, one file per entity (parents first)
  json/          same rows as JSON (decimals as strings)
  sql/           schema.sql + seed.sql (SQLite-compatible)
  ground_truth/  ground_truth.csv / .json (known anomalies, never read by the generator)
  manifest.json  seed, row counts, SHA-256 of every file
data/validation_summary_<scale>.json / .md
data/reproducibility_<scale>.json
data/metrics_<scale>.json
```

The starter dataset is committed in full. For the full dataset the CSV tables, ground truth and manifest are committed. `data/full/json/` and `data/full/sql/` are git-ignored (115 MB and 60 MB); regenerate them with `python generate.py --scale full`, which gives identical bytes.

## Documentation

- `docs/data_dictionary.md`: every field with type, required, allowed values, uniqueness, validation, plus cardinality and lifecycle states.
- `docs/decisions.md`: assumptions and rules (abandonment, consent, caps, campaign sequence, attribution window, anomalies).
- `docs/`: entity-relationship description.

## Entities

Customer, Consent, Session, Cart, CartLine, Campaign, MessageTemplate, SendAttempt, Order, Attribution, plus two supporting history tables, CartEvent and SendEvent, so nothing is overwritten. IDs follow the brief (`CUS-000001`, `CART-2026-000001`, `CMP-2026-000001`, `MSG-<cart-id>-01`, `SEND-2026-000001`, `ORD-2026-000001`).

## Business rules (summary)

- **Abandonment:** no cart activity for 60 minutes and no order. `abandoned_at = last_activity_at + 60 min`.
- **Consent:** per channel, append-only events with effective dates. A send is allowed only if the consent row in force at send time is `opt_in`. No consent row means not consented.
- **Frequency caps:** at most 1 message per channel per customer per 24 hours, and 3 per customer per 7 days.
- **Sequence:** email at +60 min, email at +26 h, SMS at +72 h (the second email is 25 h after the first, so it does not collide with the 24 h cap). Variants A/B are assigned from the seed. A pending message is suppressed if the cart is purchased first.
- **Attribution:** deterministic last-touch, 7-day window. The latest click wins, otherwise the latest open, ties go to the lowest `send_id`. One attribution per order. Late purchases are valid orders with no attribution.

## Full dataset at a glance

| | |
|---|---|
| Carts / abandoned | 50,000 / 20,000 |
| Send attempts (sent / suppressed) | 10,000 (7,073 / 2,927) |
| Suppression reasons | no consent record 2,143; opted out 378; purchased before send 377; 24 h cap 8; 7 d cap 21 |
| Orders | 31,700 (1,700 recovered carts) |
| Attributed orders | 310 (357 rows including 47 injected duplicates) |

The starter dataset has no cap conflicts; they only appear at full scale.

## Labelled edge cases

Injected after the valid baseline and listed in `ground_truth.csv`; each touches only its target rows:

| issue_type | starter | full |
|---|---|---|
| message_after_opt_out | 3 | 50 |
| abandoned_after_purchase | 3 | 50 |
| attribution_double_count | 1 | 47 |
| stale_cart_total | 3 | 50 |

`attribution_double_count` is limited by the number of orders eligible for a cross-campaign duplicate, so it can fall below the target of 3 / 50.

## Validation

`validate.py` reads only the exported CSVs and never `ground_truth`. It checks primary keys, foreign keys, joins, enums, required fields, natural-key uniqueness, date ordering, arithmetic reconciliation (line, cart, order totals), cart and consent lifecycles, abandonment rule, send decisions, frequency caps, and attribution rules. It then compares its findings with the labels: every violation must be explained by an injected anomaly, and every injected anomaly must be detected. The result is `PASS` only if there are zero unexplained violations and zero missed anomalies. Results are in `data/validation_summary_<scale>.json` and `.md`.

## Reproducibility

`reproduce.py` clears the output folder, generates twice with the same seed and compares row counts and SHA-256 checksums of all 28 files. Result for both scales: 0 mismatches (`data/reproducibility_<scale>.json`). Line endings are pinned to LF (`.gitattributes`) so checksums match on Windows and Linux.

## Provenance

No external data. Names, products, prices, emails (`@example.com`) and phone numbers are generated from lists and ranges in the code.