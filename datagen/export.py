"""Exporters: CSV, JSON, SQL schema and seed, ground truth and manifest."""
import csv
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

# (table name, key in the pipeline output, primary key, columns), parents first
TABLES = (
    ("customers", "customers", "customer_id",
     ("customer_id", "first_name", "email", "phone", "country_code", "created_at")),
    ("consents", "consents", "consent_id",
     ("consent_id", "customer_id", "channel", "status", "effective_from",
      "recorded_at", "source")),
    ("sessions", "sessions", "session_id",
     ("session_id", "customer_id", "device_id", "device_type", "started_at",
      "last_activity_at")),
    ("campaigns", "campaigns", "campaign_id",
     ("campaign_id", "name", "status", "start_date", "end_date",
      "abandonment_window_minutes", "attribution_window_days",
      "max_sends_per_channel_per_24h", "max_sends_per_7d")),
    ("carts", "carts", "cart_id",
     ("cart_id", "customer_id", "session_id", "currency", "status", "created_at",
      "last_activity_at", "abandoned_at", "cart_total")),
    ("cart_lines", "cart_lines", "cart_line_id",
     ("cart_line_id", "cart_id", "product_sku", "product_name", "unit_price",
      "quantity", "line_total")),
    ("cart_events", "cart_events", "event_id",
     ("event_id", "cart_id", "session_id", "event_type", "cart_line_id",
      "old_quantity", "new_quantity", "occurred_at")),
    ("message_templates", "messages", "message_id",
     ("message_id", "campaign_id", "cart_id", "sequence", "channel", "variant",
      "template_code", "delay_minutes", "subject", "body", "created_at")),
    ("send_attempts", "send_attempts", "send_id",
     ("send_id", "message_id", "scheduled_at", "attempted_at", "decision",
      "suppression_reason", "consent_id_checked")),
    ("send_events", "send_events", "send_event_id",
     ("send_event_id", "send_id", "event_type", "occurred_at")),
    ("orders", "orders", "order_id",
     ("order_id", "customer_id", "cart_id", "session_id", "currency",
      "order_total", "status", "placed_at")),
    ("attributions", "attributions", "attribution_id",
     ("attribution_id", "order_id", "send_id", "send_event_id", "touch_type",
      "lag_minutes", "attributed_revenue")),
)

GROUND_TRUTH_COLUMNS = (
    "ground_truth_id", "issue_type", "table_name", "record_id", "related_id",
    "expected_decision", "detail",
)

SCHEMA_SQL = """-- Cart recovery schema (SQLite). Run before seed.sql.
-- attributions.order_id is deliberately NOT unique so the injected
-- attribution_double_count anomaly can load; validate.py enforces the rule.
PRAGMA foreign_keys = ON;

CREATE TABLE customers (
  customer_id TEXT PRIMARY KEY,
  first_name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  phone TEXT UNIQUE,
  country_code TEXT NOT NULL CHECK (country_code IN ('IN','SA','AE','US')),
  created_at TEXT NOT NULL
);

CREATE TABLE consents (
  consent_id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL REFERENCES customers(customer_id),
  channel TEXT NOT NULL CHECK (channel IN ('email','sms')),
  status TEXT NOT NULL CHECK (status IN ('opt_in','opt_out')),
  effective_from TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('signup','checkout','preference_center','unsubscribe_link','sms_stop')),
  UNIQUE (customer_id, channel, effective_from)
);

CREATE TABLE sessions (
  session_id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL REFERENCES customers(customer_id),
  device_id TEXT NOT NULL,
  device_type TEXT NOT NULL CHECK (device_type IN ('mobile','desktop','tablet')),
  started_at TEXT NOT NULL,
  last_activity_at TEXT NOT NULL
);

CREATE TABLE campaigns (
  campaign_id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL CHECK (status IN ('draft','active','completed','cancelled')),
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  abandonment_window_minutes INTEGER NOT NULL CHECK (abandonment_window_minutes > 0),
  attribution_window_days INTEGER NOT NULL CHECK (attribution_window_days > 0),
  max_sends_per_channel_per_24h INTEGER NOT NULL CHECK (max_sends_per_channel_per_24h > 0),
  max_sends_per_7d INTEGER NOT NULL CHECK (max_sends_per_7d > 0)
);

CREATE TABLE carts (
  cart_id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL REFERENCES customers(customer_id),
  session_id TEXT NOT NULL REFERENCES sessions(session_id),
  currency TEXT NOT NULL CHECK (currency IN ('INR','SAR','AED','USD')),
  status TEXT NOT NULL CHECK (status IN ('active','abandoned','recovered','purchased')),
  created_at TEXT NOT NULL,
  last_activity_at TEXT NOT NULL,
  abandoned_at TEXT,
  cart_total NUMERIC NOT NULL CHECK (cart_total >= 0)
);

CREATE TABLE cart_lines (
  cart_line_id TEXT PRIMARY KEY,
  cart_id TEXT NOT NULL REFERENCES carts(cart_id),
  product_sku TEXT NOT NULL,
  product_name TEXT NOT NULL,
  unit_price NUMERIC NOT NULL CHECK (unit_price > 0),
  quantity INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 10),
  line_total NUMERIC NOT NULL,
  UNIQUE (cart_id, product_sku)
);

CREATE TABLE cart_events (
  event_id TEXT PRIMARY KEY,
  cart_id TEXT NOT NULL REFERENCES carts(cart_id),
  session_id TEXT NOT NULL REFERENCES sessions(session_id),
  event_type TEXT NOT NULL CHECK (event_type IN ('cart_created','line_added','quantity_updated','line_removed','abandoned','recovered','purchased')),
  cart_line_id TEXT REFERENCES cart_lines(cart_line_id),
  old_quantity INTEGER,
  new_quantity INTEGER,
  occurred_at TEXT NOT NULL
);

CREATE TABLE message_templates (
  message_id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id),
  cart_id TEXT NOT NULL REFERENCES carts(cart_id),
  sequence INTEGER NOT NULL CHECK (sequence BETWEEN 1 AND 3),
  channel TEXT NOT NULL CHECK (channel IN ('email','sms')),
  variant TEXT NOT NULL CHECK (variant IN ('A','B')),
  template_code TEXT NOT NULL,
  delay_minutes INTEGER NOT NULL CHECK (delay_minutes > 0),
  subject TEXT,
  body TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (cart_id, sequence)
);

CREATE TABLE send_attempts (
  send_id TEXT PRIMARY KEY,
  message_id TEXT NOT NULL UNIQUE REFERENCES message_templates(message_id),
  scheduled_at TEXT NOT NULL,
  attempted_at TEXT NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('sent','suppressed')),
  suppression_reason TEXT CHECK (suppression_reason IS NULL OR suppression_reason IN ('opted_out','no_consent_record','frequency_cap_24h','frequency_cap_7d','purchased_before_send')),
  consent_id_checked TEXT REFERENCES consents(consent_id)
);

CREATE TABLE send_events (
  send_event_id TEXT PRIMARY KEY,
  send_id TEXT NOT NULL REFERENCES send_attempts(send_id),
  event_type TEXT NOT NULL CHECK (event_type IN ('delivered','bounced','opened','clicked')),
  occurred_at TEXT NOT NULL
);

CREATE TABLE orders (
  order_id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL REFERENCES customers(customer_id),
  cart_id TEXT NOT NULL UNIQUE REFERENCES carts(cart_id),
  session_id TEXT NOT NULL REFERENCES sessions(session_id),
  currency TEXT NOT NULL CHECK (currency IN ('INR','SAR','AED','USD')),
  order_total NUMERIC NOT NULL CHECK (order_total >= 0),
  status TEXT NOT NULL CHECK (status IN ('placed','cancelled')),
  placed_at TEXT NOT NULL
);

CREATE TABLE attributions (
  attribution_id TEXT PRIMARY KEY,
  order_id TEXT NOT NULL REFERENCES orders(order_id),
  send_id TEXT NOT NULL REFERENCES send_attempts(send_id),
  send_event_id TEXT NOT NULL REFERENCES send_events(send_event_id),
  touch_type TEXT NOT NULL CHECK (touch_type IN ('click','open')),
  lag_minutes INTEGER NOT NULL CHECK (lag_minutes > 0),
  attributed_revenue NUMERIC NOT NULL
);
CREATE INDEX idx_attributions_order ON attributions(order_id);
"""


def _fmt(value):
    if value is None:
        return None
    if isinstance(value, datetime):  # check before date: datetime is a date subclass
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _rows(records, pk, columns):
    ordered = sorted(records, key=lambda r: r[pk])
    return [[_fmt(r[c]) for c in columns] for r in ordered]


def _write_csv(path, columns, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow(["" if v is None else v for v in row])


def _write_json(path, columns, rows):
    lines = [json.dumps(dict(zip(columns, row)), ensure_ascii=False) for row in rows]
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write("[\n" + ",\n".join(lines) + "\n]\n")


def _sql_literal(raw):
    if raw is None:
        return "NULL"
    if isinstance(raw, (int, Decimal)):
        return str(raw)
    return "'" + str(_fmt(raw)).replace("'", "''") + "'"


def _write_seed(path, data):
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write("-- Seed data. Run schema.sql first.\nPRAGMA foreign_keys = ON;\nBEGIN;\n")
        for name, key, pk, columns in TABLES:
            records = sorted(data[key], key=lambda r: r[pk])
            for i in range(0, len(records), 500):
                values = ",\n".join(
                    "(" + ", ".join(_sql_literal(r[c]) for c in columns) + ")"
                    for r in records[i:i + 500]
                )
                f.write(f"INSERT INTO {name} ({', '.join(columns)}) VALUES\n{values};\n")
        f.write("COMMIT;\n")


def export_all(data, scale_name, seed, out_dir):
    """Writes every output file and returns the manifest dict."""
    out_dir = Path(out_dir)
    for sub in ("tables", "json", "sql", "ground_truth"):
        (out_dir / sub).mkdir(parents=True, exist_ok=True)

    counts = {}
    for name, key, pk, columns in TABLES:
        rows = _rows(data[key], pk, columns)
        counts[name] = len(rows)
        _write_csv(out_dir / "tables" / f"{name}.csv", columns, rows)
        _write_json(out_dir / "json" / f"{name}.json", columns, rows)

    truth = _rows(data["ground_truth"], "ground_truth_id", GROUND_TRUTH_COLUMNS)
    counts["ground_truth"] = len(truth)
    _write_csv(out_dir / "ground_truth" / "ground_truth.csv", GROUND_TRUTH_COLUMNS, truth)
    _write_json(out_dir / "ground_truth" / "ground_truth.json", GROUND_TRUTH_COLUMNS, truth)

    with open(out_dir / "sql" / "schema.sql", "w", newline="", encoding="utf-8") as f:
        f.write(SCHEMA_SQL)
    _write_seed(out_dir / "sql" / "seed.sql", data)

    files = {}
    for path in sorted(out_dir.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            files[path.relative_to(out_dir).as_posix()] = hashlib.sha256(
                path.read_bytes()).hexdigest()
    manifest = {"scale": scale_name, "seed": seed, "row_counts": counts, "files": files}
    with open(out_dir / "manifest.json", "w", newline="", encoding="utf-8") as f:
        f.write(json.dumps(manifest, indent=2) + "\n")
    return manifest