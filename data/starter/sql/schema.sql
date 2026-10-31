-- Cart recovery schema (SQLite). Run before seed.sql.
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
