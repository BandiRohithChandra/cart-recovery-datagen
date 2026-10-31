"""Validation (problem statement Step 8).

Usage: python validate.py --scale starter|full [--data data]

Reads the exported CSV files and runs every check WITHOUT looking at the
ground truth. Only afterwards are the findings compared with ground_truth.csv.
Exit code 1 if any violation is not explained by a labelled anomaly, or if an
injected anomaly was not detected.
"""
import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import config
from datagen.export import TABLES
from datagen.ids import is_valid, is_valid_message_id

EPOCH = datetime(1970, 1, 1)
WINDOW = timedelta(days=config.ATTRIBUTION_WINDOW_DAYS)
MIN_LAG = timedelta(minutes=1)
EDITING = {"cart_created", "line_added", "quantity_updated", "line_removed"}
LINE_EVENTS = {"line_added", "quantity_updated", "line_removed"}

PK = {name: pk for name, _, pk, _ in TABLES}
KIND = {
    "customers": "customer", "consents": "consent", "sessions": "session",
    "campaigns": "campaign", "carts": "cart", "cart_lines": "cart_line",
    "cart_events": "cart_event", "send_attempts": "send",
    "send_events": "send_event", "orders": "order", "attributions": "attribution",
}

# (child table, column, parent table)
FKS = (
    ("consents", "customer_id", "customers"),
    ("sessions", "customer_id", "customers"),
    ("carts", "customer_id", "customers"),
    ("carts", "session_id", "sessions"),
    ("cart_lines", "cart_id", "carts"),
    ("cart_events", "cart_id", "carts"),
    ("cart_events", "session_id", "sessions"),
    ("cart_events", "cart_line_id", "cart_lines"),
    ("message_templates", "campaign_id", "campaigns"),
    ("message_templates", "cart_id", "carts"),
    ("send_attempts", "message_id", "message_templates"),
    ("send_attempts", "consent_id_checked", "consents"),
    ("send_events", "send_id", "send_attempts"),
    ("orders", "customer_id", "customers"),
    ("orders", "cart_id", "carts"),
    ("orders", "session_id", "sessions"),
    ("attributions", "order_id", "orders"),
    ("attributions", "send_id", "send_attempts"),
    ("attributions", "send_event_id", "send_events"),
)

ENUMS = {
    ("customers", "country_code"): {"IN", "SA", "AE", "US"},
    ("consents", "channel"): {"email", "sms"},
    ("consents", "status"): {"opt_in", "opt_out"},
    ("consents", "source"): {"signup", "checkout", "preference_center",
                             "unsubscribe_link", "sms_stop"},
    ("sessions", "device_type"): {"mobile", "desktop", "tablet"},
    ("campaigns", "status"): {"draft", "active", "completed", "cancelled"},
    ("carts", "currency"): {"INR", "SAR", "AED", "USD"},
    ("carts", "status"): {"active", "abandoned", "recovered", "purchased"},
    ("cart_events", "event_type"): {"cart_created", "line_added", "quantity_updated",
                                    "line_removed", "abandoned", "recovered", "purchased"},
    ("message_templates", "channel"): {"email", "sms"},
    ("message_templates", "variant"): {"A", "B"},
    ("send_attempts", "decision"): {"sent", "suppressed"},
    ("send_attempts", "suppression_reason"): {"opted_out", "no_consent_record",
                                              "frequency_cap_24h", "frequency_cap_7d",
                                              "purchased_before_send"},
    ("send_events", "event_type"): {"delivered", "bounced", "opened", "clicked"},
    ("orders", "currency"): {"INR", "SAR", "AED", "USD"},
    ("orders", "status"): {"placed", "cancelled"},
    ("attributions", "touch_type"): {"click", "open"},
}

OPTIONAL = {
    "customers": {"phone"},
    "carts": {"abandoned_at"},
    "cart_events": {"cart_line_id", "old_quantity", "new_quantity"},
    "message_templates": {"subject"},
    "send_attempts": {"suppression_reason", "consent_id_checked"},
}

UNIQUE = (
    ("customers", ("email",)),
    ("customers", ("phone",)),
    ("consents", ("customer_id", "channel", "effective_from")),
    ("campaigns", ("name",)),
    ("cart_lines", ("cart_id", "product_sku")),
    ("cart_events", ("cart_id", "event_type", "cart_line_id", "occurred_at")),
    ("message_templates", ("cart_id", "sequence")),
    ("send_attempts", ("message_id",)),
    ("orders", ("cart_id",)),
)

STATUS_RULES = {  # status -> (event types required, event types forbidden)
    "purchased": ({"purchased"}, {"abandoned", "recovered"}),
    "abandoned": ({"abandoned"}, {"purchased", "recovered"}),
    "recovered": ({"abandoned", "recovered"}, {"purchased"}),
    "active": (set(), {"abandoned", "purchased", "recovered"}),
}

# Which checks may legitimately fire because of each injected anomaly type
ALLOWED = {
    "message_after_opt_out": {"send_consent_in_force", "frequency_caps"},
    "abandoned_after_purchase": {"cart_status_vs_events"},
    "attribution_double_count": {"attribution_unique_per_order",
                                 "attribution_touch_rules",
                                 "attribution_counts_reconcile"},
    "stale_cart_total": {"cart_total_reconciles"},
}
# The check that must detect each injected anomaly type
DETECTED_BY = {
    "message_after_opt_out": "send_consent_in_force",
    "abandoned_after_purchase": "cart_status_vs_events",
    "attribution_double_count": "attribution_unique_per_order",
    "stale_cart_total": "cart_total_reconciles",
}


def ts(value):
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ") if value else None


def secs(dt):
    return (dt - EPOCH).total_seconds()


class Ctx:
    def __init__(self, data):
        self.t = data
        self.by = {name: {r[pk]: r for r in data[name]} for name, _, pk, _ in TABLES}
        self.violations = []
        self.lines = defaultdict(list)
        for r in data["cart_lines"]:
            self.lines[r["cart_id"]].append(r)
        self.events = defaultdict(list)
        for r in sorted(data["cart_events"], key=lambda r: r["event_id"]):
            self.events[r["cart_id"]].append(r)

    def flag(self, check, keys, message):
        self.violations.append(
            {"check": check, "keys": [k for k in keys if k], "message": message})


def _send_ctx(c, s):
    m = c.by["message_templates"].get(s["message_id"])
    cart = c.by["carts"].get(m["cart_id"]) if m else None
    return (m, cart) if cart else (None, None)


# ---------------------------------------------------------------- structure

def primary_keys(c, flag):
    for name, _, pk, _ in TABLES:
        seen = set()
        for r in c.t[name]:
            v = r[pk]
            if v in seen:
                flag([v], f"{name}: duplicate primary key {v}")
            seen.add(v)
            ok = (is_valid_message_id(v) if name == "message_templates"
                  else is_valid(KIND[name], v))
            if not ok:
                flag([v], f"{name}: malformed id {v}")
    for r in c.t["sessions"]:
        if not is_valid("device", r["device_id"]):
            flag([r["session_id"]], f"sessions: malformed device_id {r['device_id']}")


def foreign_keys(c, flag):
    for table, col, parent in FKS:
        for r in c.t[table]:
            v = r[col]
            if v and v not in c.by[parent]:
                flag([r[PK[table]], v], f"{table}.{col}={v} has no parent in {parent}")


def join_consistency(c, flag):
    for cart in c.t["carts"]:
        s = c.by["sessions"].get(cart["session_id"])
        cust = c.by["customers"].get(cart["customer_id"])
        if s and s["customer_id"] != cart["customer_id"]:
            flag([cart["cart_id"]], "cart and its session belong to different customers")
        if cust and cart["currency"] != config.CURRENCY_BY_COUNTRY.get(cust["country_code"]):
            flag([cart["cart_id"]], "cart currency does not match the customer's country")
    for o in c.t["orders"]:
        cart = c.by["carts"].get(o["cart_id"])
        if cart and cart["customer_id"] != o["customer_id"]:
            flag([o["order_id"]], "order and its cart belong to different customers")
        if cart and cart["currency"] != o["currency"]:
            flag([o["order_id"]], "order currency differs from its cart")
    for e in c.t["cart_events"]:
        cart = c.by["carts"].get(e["cart_id"])
        s = c.by["sessions"].get(e["session_id"])
        if cart and s and s["customer_id"] != cart["customer_id"]:
            flag([e["event_id"]], "cart event happened in another customer's session")
        line = c.by["cart_lines"].get(e["cart_line_id"]) if e["cart_line_id"] else None
        if line and line["cart_id"] != e["cart_id"]:
            flag([e["event_id"]], "cart event refers to a line of another cart")
    for m in c.t["message_templates"]:
        expected = f"MSG-{m['cart_id']}-{int(m['sequence']):02d}"
        if m["message_id"] != expected:
            flag([m["message_id"]], f"message_id should be {expected}")
    for a in c.t["attributions"]:
        ev = c.by["send_events"].get(a["send_event_id"])
        if ev and ev["send_id"] != a["send_id"]:
            flag([a["attribution_id"]], "touch event belongs to a different send")


def allowed_values(c, flag):
    for (table, col), allowed in ENUMS.items():
        for r in c.t[table]:
            if r[col] and r[col] not in allowed:
                flag([r[PK[table]]], f"{table}.{col}={r[col]!r} not allowed")


def required_fields(c, flag):
    for name, _, pk, columns in TABLES:
        optional = OPTIONAL.get(name, set())
        for r in c.t[name]:
            for col in columns:
                if col not in optional and r[col] == "":
                    flag([r[pk]], f"{name}.{col} is required")


def natural_keys_unique(c, flag):
    for table, cols in UNIQUE:
        seen = {}
        for r in c.t[table]:
            key = tuple(r[col] for col in cols)
            if len(cols) == 1 and key[0] == "":
                continue
            if key in seen:
                flag([r[PK[table]], seen[key]], f"{table}: duplicate {'/'.join(cols)}")
            else:
                seen[key] = r[PK[table]]


# ------------------------------------------------------------- date ordering

def date_ordering(c, flag):
    cust, carts = c.by["customers"], c.by["carts"]
    for r in c.t["consents"]:
        p = cust.get(r["customer_id"])
        if p and ts(r["effective_from"]) < ts(p["created_at"]):
            flag([r["consent_id"]], "consent effective before the customer existed")
        if ts(r["recorded_at"]) < ts(r["effective_from"]):
            flag([r["consent_id"]], "consent recorded before it took effect")
    for r in c.t["sessions"]:
        p = cust.get(r["customer_id"])
        if p and ts(r["started_at"]) < ts(p["created_at"]):
            flag([r["session_id"]], "session started before the customer existed")
        if ts(r["last_activity_at"]) < ts(r["started_at"]):
            flag([r["session_id"]], "session ends before it starts")
    for cart in c.t["carts"]:
        s = c.by["sessions"].get(cart["session_id"])
        if s and ts(cart["created_at"]) < ts(s["started_at"]):
            flag([cart["cart_id"]], "cart created before its session started")
        if ts(cart["last_activity_at"]) < ts(cart["created_at"]):
            flag([cart["cart_id"]], "cart last activity before creation")
    for cart_id, evs in c.events.items():
        cart = carts.get(cart_id)
        for e in evs:
            if cart and ts(e["occurred_at"]) < ts(cart["created_at"]):
                flag([e["event_id"], cart_id], "cart event before cart creation")
        for prev, cur in zip(evs, evs[1:]):
            if ts(cur["occurred_at"]) < ts(prev["occurred_at"]):
                flag([cur["event_id"], cart_id], "cart events go backwards in time")
    for r in c.t["campaigns"]:
        if r["start_date"] > r["end_date"]:
            flag([r["campaign_id"]], "campaign starts after it ends")
    for m in c.t["message_templates"]:
        cart = carts.get(m["cart_id"])
        if cart and cart["abandoned_at"] and ts(m["created_at"]) < ts(cart["abandoned_at"]):
            flag([m["message_id"]], "message planned before the cart was abandoned")
    for s in c.t["send_attempts"]:
        if ts(s["attempted_at"]) < ts(s["scheduled_at"]):
            flag([s["send_id"]], "send attempted before it was scheduled")
        m, cart = _send_ctx(c, s)
        if cart and cart["abandoned_at"]:
            due = ts(cart["abandoned_at"]) + timedelta(minutes=int(m["delay_minutes"]))
            if ts(s["scheduled_at"]) != due:
                flag([s["send_id"]], "scheduled_at is not abandoned_at + delay")
    for e in c.t["send_events"]:
        s = c.by["send_attempts"].get(e["send_id"])
        if s and ts(e["occurred_at"]) < ts(s["attempted_at"]):
            flag([e["send_event_id"]], "send event before the send attempt")
    for o in c.t["orders"]:
        cart = carts.get(o["cart_id"])
        if cart and ts(o["placed_at"]) <= ts(cart["created_at"]):
            flag([o["order_id"]], "order placed before its cart was created")


# ----------------------------------------------------------- reconciliation

def line_total_reconciles(c, flag):
    for l in c.t["cart_lines"]:
        unit, qty = Decimal(l["unit_price"]), int(l["quantity"])
        if unit <= 0:
            flag([l["cart_line_id"]], "unit_price must be positive")
        if not 1 <= qty <= 10:
            flag([l["cart_line_id"]], "quantity must be 1 to 10")
        if Decimal(l["line_total"]) != unit * qty:
            flag([l["cart_line_id"]], "line_total != unit_price x quantity")


def cart_total_reconciles(c, flag):
    for cart in c.t["carts"]:
        total = sum((Decimal(l["line_total"]) for l in c.lines.get(cart["cart_id"], [])),
                    Decimal("0"))
        if total != Decimal(cart["cart_total"]):
            flag([cart["cart_id"]],
                 f"cart_total {cart['cart_total']} != sum of lines {total}")


def order_total_reconciles(c, flag):
    for o in c.t["orders"]:
        total = sum((Decimal(l["line_total"]) for l in c.lines.get(o["cart_id"], [])),
                    Decimal("0"))
        if total != Decimal(o["order_total"]):
            flag([o["order_id"]], f"order_total {o['order_total']} != sum of lines {total}")


def cart_event_fields(c, flag):
    for e in c.t["cart_events"]:
        eid, t = e["event_id"], e["event_type"]
        if t in LINE_EVENTS and not e["cart_line_id"]:
            flag([eid], f"{t} needs a cart_line_id")
        if t not in LINE_EVENTS and e["cart_line_id"]:
            flag([eid], f"{t} must not have a cart_line_id")
        if t == "quantity_updated":
            if not (e["old_quantity"] and e["new_quantity"]) or e["old_quantity"] == e["new_quantity"]:
                flag([eid], "quantity_updated needs different old and new quantities")
            else:
                line = c.by["cart_lines"].get(e["cart_line_id"])
                if line and line["quantity"] != e["new_quantity"]:
                    flag([eid], "line quantity does not match the update")
        elif e["old_quantity"] or e["new_quantity"]:
            flag([eid], f"{t} must not carry quantities")


# ---------------------------------------------------------------- lifecycle

def consent_lifecycle(c, flag):
    groups = defaultdict(list)
    for r in c.t["consents"]:
        groups[(r["customer_id"], r["channel"])].append(r)
    for (cust_id, channel), rows in groups.items():
        rows.sort(key=lambda r: (r["effective_from"], r["consent_id"]))
        if rows[0]["status"] != "opt_in":
            flag([rows[0]["consent_id"]], "first consent event must be opt_in")
        for prev, cur in zip(rows, rows[1:]):
            if prev["status"] == cur["status"]:
                flag([cur["consent_id"]], f"{cur['status']} repeated back to back")
        cust = c.by["customers"].get(cust_id)
        if channel == "sms" and cust and not cust["phone"]:
            flag([rows[0]["consent_id"]], "SMS consent for a customer without a phone")
    for r in c.t["consents"]:
        if r["source"] == "sms_stop" and r["channel"] != "sms":
            flag([r["consent_id"]], "sms_stop used on a non-SMS channel")


def cart_status_vs_events(c, flag):
    for cart in c.t["carts"]:
        cid, status = cart["cart_id"], cart["status"]
        evs = c.events.get(cid, [])
        types = [e["event_type"] for e in evs]
        need, forbid = STATUS_RULES.get(status, (set(), set()))
        if "cart_created" not in types:
            flag([cid], "cart has no cart_created event")
        for t in sorted(need - set(types)):
            flag([cid], f"{status} cart has no {t} event")
        for e in evs:
            if e["event_type"] in forbid:
                flag([cid, e["event_id"]], f"{status} cart has a {e['event_type']} event")
        if (status == "recovered" and "abandoned" in types and "recovered" in types
                and types.index("abandoned") > types.index("recovered")):
            flag([cid], "recovered before abandoned")


def order_cart_lifecycle(c, flag):
    by_cart = defaultdict(list)
    for o in c.t["orders"]:
        by_cart[o["cart_id"]].append(o)
    for cart in c.t["carts"]:
        cid, status = cart["cart_id"], cart["status"]
        orders = by_cart.get(cid, [])
        bought = status in ("purchased", "recovered")
        if bought and len(orders) != 1:
            flag([cid], f"{status} cart has {len(orders)} orders")
        if not bought and orders:
            flag([cid, orders[0]["order_id"]], f"{status} cart has an order")
        if bought and len(orders) == 1:
            times = [ts(e["occurred_at"]) for e in c.events.get(cid, [])
                     if e["event_type"] == status]
            if times and ts(orders[0]["placed_at"]) != times[0]:
                flag([cid, orders[0]["order_id"]], "order time differs from the cart event")


def abandonment_rule(c, flag):
    window = timedelta(minutes=config.ABANDONMENT_WINDOW_MINUTES)
    for cart in c.t["carts"]:
        cid, status = cart["cart_id"], cart["status"]
        evs = c.events.get(cid, [])
        edits = [ts(e["occurred_at"]) for e in evs if e["event_type"] in EDITING]
        last = ts(cart["last_activity_at"])
        if edits and max(edits) != last:
            flag([cid], "last_activity_at is not the latest cart-editing event")
        if status in ("abandoned", "recovered"):
            if not cart["abandoned_at"]:
                flag([cid], f"{status} cart has no abandoned_at")
                continue
            if ts(cart["abandoned_at"]) != last + window:
                flag([cid], "abandoned_at is not last_activity_at + window")
            ab = [ts(e["occurred_at"]) for e in evs if e["event_type"] == "abandoned"]
            if ab and ab[0] != ts(cart["abandoned_at"]):
                flag([cid], "abandoned event time differs from abandoned_at")
        else:
            if cart["abandoned_at"]:
                flag([cid], f"{status} cart has abandoned_at")
            if status == "purchased":
                bought = [ts(e["occurred_at"]) for e in evs if e["event_type"] == "purchased"]
                if bought and bought[0] - last >= window:
                    flag([cid], "bought after the window but never marked abandoned")
    for m in c.t["message_templates"]:
        cart = c.by["carts"].get(m["cart_id"])
        camp = c.by["campaigns"].get(m["campaign_id"])
        if cart is None:
            continue
        if not cart["abandoned_at"]:
            flag([m["message_id"]], "message targets a cart that was never abandoned")
        elif camp and not camp["start_date"] <= cart["abandoned_at"][:10] <= camp["end_date"]:
            flag([m["message_id"]], "cart abandoned outside the campaign dates")


# --------------------------------------------------------- sends and consent

def send_decision_consistency(c, flag):
    evs = defaultdict(list)
    for e in c.t["send_events"]:
        evs[e["send_id"]].append(e)
    for s in c.t["send_attempts"]:
        sid, es = s["send_id"], evs.get(s["send_id"], [])
        kinds = Counter(e["event_type"] for e in es)
        if s["decision"] == "sent":
            if s["suppression_reason"]:
                flag([sid], "sent attempt has a suppression_reason")
            if kinds["delivered"] + kinds["bounced"] != 1:
                flag([sid], "sent attempt needs exactly one delivered or bounced event")
            if kinds["bounced"] and (kinds["opened"] or kinds["clicked"]):
                flag([sid], "opened or clicked after a bounce")
            delivered = [ts(e["occurred_at"]) for e in es if e["event_type"] == "delivered"]
            for e in es:
                if (e["event_type"] in ("opened", "clicked") and delivered
                        and ts(e["occurred_at"]) < delivered[0]):
                    flag([sid], f"{e['event_type']} before delivery")
            m, _ = _send_ctx(c, s)
            if m and m["channel"] == "sms" and kinds["opened"]:
                flag([sid], "SMS cannot have opened events")
        else:
            if not s["suppression_reason"]:
                flag([sid], "suppressed attempt has no reason")
            if es:
                flag([sid], "suppressed attempt has send events")


def send_consent_in_force(c, flag):
    hist = defaultdict(list)
    for r in sorted(c.t["consents"], key=lambda r: (r["effective_from"], r["consent_id"])):
        hist[(r["customer_id"], r["channel"])].append(r)
    for s in c.t["send_attempts"]:
        m, cart = _send_ctx(c, s)
        if cart is None:
            continue
        in_force = None
        for row in hist.get((cart["customer_id"], m["channel"]), []):
            if row["effective_from"] > s["attempted_at"]:
                break
            in_force = row
        in_id = in_force["consent_id"] if in_force else ""
        sid, reason = s["send_id"], s["suppression_reason"]
        if s["consent_id_checked"] != in_id:
            flag([sid], "consent_id_checked is not the consent row in force")
        if s["decision"] == "sent":
            if in_force is None or in_force["status"] != "opt_in":
                flag([sid], "message sent without opt-in in force")
        elif reason == "opted_out" and not (in_force and in_force["status"] == "opt_out"):
            flag([sid], "suppressed as opted_out but no opt-out in force")
        elif reason == "no_consent_record" and in_force is not None:
            flag([sid], "suppressed as no_consent_record but consent exists")


def frequency_caps(c, flag):
    sent = defaultdict(list)
    for s in sorted(c.t["send_attempts"], key=lambda s: (s["attempted_at"], s["send_id"])):
        if s["decision"] != "sent":
            continue
        m, cart = _send_ctx(c, s)
        if cart:
            sent[cart["customer_id"]].append((ts(s["attempted_at"]), m["channel"], s["send_id"]))
    day, week = timedelta(hours=24), timedelta(days=7)
    for rows in sent.values():
        for i, (at, channel, sid) in enumerate(rows):
            prior = rows[:i]
            same = [p for p in prior if p[1] == channel and p[0] > at - day]
            if len(same) >= config.MAX_SENDS_PER_CHANNEL_PER_24H:
                flag([sid] + [p[2] for p in same], "24-hour channel cap exceeded")
            recent = [p for p in prior if p[0] > at - week]
            if len(recent) >= config.MAX_SENDS_PER_7D:
                flag([sid] + [p[2] for p in recent], "7-day cap exceeded")


def no_send_after_purchase(c, flag):
    placed = {o["cart_id"]: ts(o["placed_at"]) for o in c.t["orders"]}
    for s in c.t["send_attempts"]:
        _, cart = _send_ctx(c, s)
        if cart is None:
            continue
        bought = placed.get(cart["cart_id"])
        attempted = ts(s["attempted_at"])
        if s["decision"] == "sent" and bought and bought <= attempted:
            flag([s["send_id"]], "message sent after the cart was bought")
        if (s["suppression_reason"] == "purchased_before_send"
                and not (bought and bought <= attempted)):
            flag([s["send_id"]], "suppressed as purchased_before_send but not yet bought")


# --------------------------------------------------------------- attribution

def attribution_unique_per_order(c, flag):
    by_order = defaultdict(list)
    for a in c.t["attributions"]:
        by_order[a["order_id"]].append(a["attribution_id"])
    for oid, ids in by_order.items():
        if len(ids) > 1:
            flag([oid] + ids, f"order has {len(ids)} attribution rows")


def attribution_touch_rules(c, flag):
    for a in c.t["attributions"]:
        aid = a["attribution_id"]
        o = c.by["orders"].get(a["order_id"])
        ev = c.by["send_events"].get(a["send_event_id"])
        s = c.by["send_attempts"].get(a["send_id"])
        if not (o and ev and s):
            continue
        if (a["touch_type"], ev["event_type"]) not in (("click", "clicked"), ("open", "opened")):
            flag([aid], "touch_type does not match the event type")
        if s["decision"] != "sent":
            flag([aid], "credited send was not sent")
        if o["status"] != "placed":
            flag([aid], "attribution on an order that is not placed")
        _, cart = _send_ctx(c, s)
        if cart and cart["customer_id"] != o["customer_id"]:
            flag([aid], "credited send went to a different customer")
        gap = ts(o["placed_at"]) - ts(ev["occurred_at"])
        if gap < MIN_LAG or gap > WINDOW:
            flag([aid], "touch is outside the attribution window")
        if int(a["lag_minutes"]) != int(gap.total_seconds() // 60) or int(a["lag_minutes"]) <= 0:
            flag([aid], "lag_minutes does not match the touch and order times")


def attribution_matches_last_touch(c, flag):
    customer_of_send = {}
    for s in c.t["send_attempts"]:
        if s["decision"] == "sent":
            _, cart = _send_ctx(c, s)
            if cart:
                customer_of_send[s["send_id"]] = cart["customer_id"]
    touches = defaultdict(list)
    for e in c.t["send_events"]:
        if e["event_type"] in ("clicked", "opened") and e["send_id"] in customer_of_send:
            touches[customer_of_send[e["send_id"]]].append(e)
    rows = defaultdict(list)
    for a in c.t["attributions"]:
        rows[a["order_id"]].append(a)

    for o in c.t["orders"]:
        mine = rows.get(o["order_id"], [])
        if len(mine) > 1:
            continue  # reported by attribution_unique_per_order
        best = {"clicked": None, "opened": None}
        if o["status"] == "placed":
            placed = ts(o["placed_at"])
            for e in touches.get(o["customer_id"], []):
                at = ts(e["occurred_at"])
                if placed - at < MIN_LAG or placed - at > WINDOW:
                    continue
                key = (-secs(at), e["send_id"], e["send_event_id"])
                cur = best[e["event_type"]]
                if cur is None or key < cur[0]:
                    best[e["event_type"]] = (key, e)
        chosen = best["clicked"] or best["opened"]
        if not mine and chosen:
            flag([o["order_id"]], "order has a qualifying touch but no attribution")
        elif mine and o["status"] == "placed" and not chosen:
            flag([o["order_id"], mine[0]["attribution_id"]],
                 "attributed without a qualifying touch")
        elif mine and chosen and mine[0]["send_event_id"] != chosen[1]["send_event_id"]:
            flag([o["order_id"], mine[0]["attribution_id"]],
                 "credited touch differs from the last-touch rule")


def attribution_revenue_reconciles(c, flag):
    placed, credited = defaultdict(Decimal), defaultdict(Decimal)
    for o in c.t["orders"]:
        if o["status"] == "placed":
            placed[o["currency"]] += Decimal(o["order_total"])
    for a in c.t["attributions"]:
        o = c.by["orders"].get(a["order_id"])
        if o is None:
            continue
        if Decimal(a["attributed_revenue"]) != Decimal(o["order_total"]):
            flag([a["attribution_id"]], "attributed_revenue differs from order_total")
        credited[o["currency"]] += Decimal(a["attributed_revenue"])
    for currency, total in credited.items():
        if total > placed[currency]:
            flag([], f"{currency}: attributed revenue {total} exceeds placed revenue {placed[currency]}")


def attribution_counts_reconcile(c, flag):
    by_order = defaultdict(list)
    for a in c.t["attributions"]:
        by_order[a["order_id"]].append(a["attribution_id"])
    rows = len(c.t["attributions"])
    if rows != len(by_order):
        keys = []
        for oid, ids in by_order.items():
            if len(ids) > 1:
                keys += [oid] + ids
        flag(keys, f"{rows} attribution rows for {len(by_order)} distinct orders")


CHECKS = [
    ("primary_keys", primary_keys),
    ("foreign_keys", foreign_keys),
    ("join_consistency", join_consistency),
    ("allowed_values", allowed_values),
    ("required_fields", required_fields),
    ("natural_keys_unique", natural_keys_unique),
    ("date_ordering", date_ordering),
    ("line_total_reconciles", line_total_reconciles),
    ("cart_total_reconciles", cart_total_reconciles),
    ("order_total_reconciles", order_total_reconciles),
    ("cart_event_fields", cart_event_fields),
    ("consent_lifecycle", consent_lifecycle),
    ("cart_status_vs_events", cart_status_vs_events),
    ("order_cart_lifecycle", order_cart_lifecycle),
    ("abandonment_rule", abandonment_rule),
    ("send_decision_consistency", send_decision_consistency),
    ("send_consent_in_force", send_consent_in_force),
    ("frequency_caps", frequency_caps),
    ("no_send_after_purchase", no_send_after_purchase),
    ("attribution_unique_per_order", attribution_unique_per_order),
    ("attribution_touch_rules", attribution_touch_rules),
    ("attribution_matches_last_touch", attribution_matches_last_touch),
    ("attribution_revenue_reconciles", attribution_revenue_reconciles),
    ("attribution_counts_reconcile", attribution_counts_reconcile),
]


# ------------------------------------------------------- comparison and output

def explained_ids(g):
    if g["issue_type"] == "message_after_opt_out":
        return {g["record_id"]}
    return {g["record_id"], g["related_id"]}


def classify(violations, truth):
    targets = [(ALLOWED[g["issue_type"]], explained_ids(g)) for g in truth]
    for v in violations:
        keys = set(v["keys"])
        v["labelled"] = any(v["check"] in allowed and ids & keys for allowed, ids in targets)


def detection(violations, truth):
    result = {}
    for issue, check in DETECTED_BY.items():
        rows = [g for g in truth if g["issue_type"] == issue]
        found = 0
        for g in rows:
            ids = explained_ids(g)
            if any(v["check"] == check and ids & set(v["keys"]) for v in violations):
                found += 1
        result[issue] = {"injected": len(rows), "detected": found}
    return result


def write_reports(summary, data_dir, scale):
    base = Path(data_dir)
    (base / f"validation_summary_{scale}.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    lines = [
        f"# Validation summary ({scale})", "",
        f"Seed: {summary['seed']}. Result: **{summary['result']}**", "",
        "| Check | Violations | Labelled anomalies | Unexpected |", "|---|---:|---:|---:|",
    ]
    for name, r in summary["checks"].items():
        lines.append(f"| {name} | {r['violations']} | {r['labelled']} | {r['unexpected']} |")
    lines += ["", "## Injected anomaly detection", "",
              "| Issue type | Injected | Detected |", "|---|---:|---:|"]
    for issue, r in summary["detection"].items():
        lines.append(f"| {issue} | {r['injected']} | {r['detected']} |")
    lines += ["", "## Row counts", "", "| Table | Rows |", "|---|---:|"]
    for table, n in summary["row_counts"].items():
        lines.append(f"| {table} | {n} |")
    (base / f"validation_summary_{scale}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Validate the generated dataset.")
    parser.add_argument("--scale", choices=sorted(config.SCALES), default="starter")
    parser.add_argument("--data", default="data")
    args = parser.parse_args()
    base = Path(args.data) / args.scale

    data = {}
    for name, _, _, _ in TABLES:
        with open(base / "tables" / f"{name}.csv", newline="", encoding="utf-8") as f:
            data[name] = list(csv.DictReader(f))
    c = Ctx(data)

    for name, fn in CHECKS:  # the ground truth is not read until all checks have run
        try:
            fn(c, lambda keys, msg, n=name: c.flag(n, keys, msg))
        except Exception as exc:  # a broken check must fail the run, not hide
            c.flag(name, [], f"check could not run: {exc!r}")

    with open(base / "ground_truth" / "ground_truth.csv", newline="", encoding="utf-8") as f:
        truth = list(csv.DictReader(f))
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))

    classify(c.violations, truth)
    det = detection(c.violations, truth)

    checks = {}
    for name, _ in CHECKS:
        mine = [v for v in c.violations if v["check"] == name]
        labelled = sum(1 for v in mine if v["labelled"])
        checks[name] = {"violations": len(mine), "labelled": labelled,
                        "unexpected": len(mine) - labelled}
    unexpected = sum(r["unexpected"] for r in checks.values())
    missed = sum(r["injected"] - r["detected"] for r in det.values())
    result = "PASS" if unexpected == 0 and missed == 0 else "FAIL"

    summary = {"scale": args.scale, "seed": manifest["seed"], "result": result,
               "checks": checks, "detection": det, "row_counts": manifest["row_counts"],
               "unexpected_examples": [v for v in c.violations if not v["labelled"]][:20]}
    write_reports(summary, args.data, args.scale)

    print(f"Validation: scale={args.scale} seed={manifest['seed']}")
    print(f"{'check':<34}{'violations':>11}{'labelled':>10}{'unexpected':>12}")
    for name, r in checks.items():
        print(f"{name:<34}{r['violations']:>11}{r['labelled']:>10}{r['unexpected']:>12}")
    print("\nInjected anomalies")
    for issue, r in det.items():
        print(f"  {issue:<28} injected={r['injected']:<4} detected={r['detected']}")
    for v in summary["unexpected_examples"][:10]:
        print(f"  UNEXPECTED [{v['check']}] {v['message']} {v['keys'][:3]}")
    print(f"\nRESULT: {result}")
    sys.exit(0 if result == "PASS" else 1)


if __name__ == "__main__":
    main()