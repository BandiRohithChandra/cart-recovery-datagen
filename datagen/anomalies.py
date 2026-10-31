"""Labelled anomaly injection (see docs/decisions.md section 11)."""
from datetime import timedelta

from datagen.carts import _event as make_event

COUNTS = {"starter": 3, "full": 50}  # per anomaly type


def _label(rows, issue_type, table, record_id, related_id, expected, detail):
    rows.append({
        "ground_truth_id": f"GT-{len(rows) + 1:06d}",
        "issue_type": issue_type,
        "table_name": table,
        "record_id": record_id,
        "related_id": related_id,
        "expected_decision": expected,
        "detail": detail,
    })


def inject_anomalies(rng, ids, scale, tables):
    """Changes tables in place and returns the ground-truth rows."""
    n = COUNTS[scale.name]
    truth = []

    # 1. message sent after opt-out
    suppressed = [a for a in tables["send_attempts"]
                  if a["suppression_reason"] == "opted_out"]
    for a in sorted(rng.sample(suppressed, min(n, len(suppressed))),
                    key=lambda a: a["send_id"]):
        a["decision"] = "sent"
        a["suppression_reason"] = None
        tables["send_events"].append({
            "send_event_id": ids.next("send_event"),
            "send_id": a["send_id"],
            "event_type": "delivered",
            "occurred_at": a["attempted_at"] + timedelta(seconds=rng.randint(1, 60)),
        })
        _label(truth, "message_after_opt_out", "send_attempts", a["send_id"],
               a["consent_id_checked"], "suppressed (opted_out)",
               "Message sent although the opt-out in force was the consent row checked")

    # 2. cart considered abandoned after purchase
    purchased_at = {e["cart_id"]: e["occurred_at"] for e in tables["cart_events"]
                    if e["event_type"] == "purchased"}
    direct = [c for c in tables["carts"] if c["status"] == "purchased"]
    for cart in sorted(rng.sample(direct, min(n, len(direct))),
                       key=lambda c: c["cart_id"]):
        at = purchased_at[cart["cart_id"]] + timedelta(minutes=rng.randint(5, 120))
        event = make_event(ids, cart["cart_id"], cart["session_id"], "abandoned", at)
        tables["cart_events"].append(event)
        _label(truth, "abandoned_after_purchase", "cart_events", event["event_id"],
               cart["cart_id"], "no abandoned event after a purchased event",
               "Abandoned event recorded after the cart was purchased")

    # 3. attribution double-counted across campaigns
    msg_campaign = {m["message_id"]: m["campaign_id"] for m in tables["messages"]}
    send_campaign = {s["send_id"]: msg_campaign[s["message_id"]]
                     for s in tables["send_attempts"]}
    touches = [e for e in tables["send_events"]
               if e["event_type"] in ("clicked", "opened")]
    order_by_id = {o["order_id"]: o for o in tables["orders"]}
    one_minute = timedelta(minutes=1)
    for attr in sorted(rng.sample(tables["attributions"],
                                  min(n, len(tables["attributions"]))),
                       key=lambda a: a["attribution_id"]):
        order = order_by_id[attr["order_id"]]
        first = send_campaign[attr["send_id"]]
        options = [e for e in touches
                   if send_campaign[e["send_id"]] != first
                   and order["placed_at"] - e["occurred_at"] >= one_minute]
        if not options:
            continue
        e = rng.choice(options)
        gap = order["placed_at"] - e["occurred_at"]
        extra = {
            "attribution_id": ids.next("attribution"),
            "order_id": order["order_id"],
            "send_id": e["send_id"],
            "send_event_id": e["send_event_id"],
            "touch_type": "click" if e["event_type"] == "clicked" else "open",
            "lag_minutes": int(gap.total_seconds() // 60),
            "attributed_revenue": order["order_total"],
        }
        tables["attributions"].append(extra)
        _label(truth, "attribution_double_count", "attributions",
               extra["attribution_id"], order["order_id"],
               "one attribution row per order",
               "Order credited to a second campaign; revenue counted twice")

    # 4. cart total stale after quantity update
    line_by_id = {l["cart_line_id"]: l for l in tables["cart_lines"]}
    cart_by_id = {c["cart_id"]: c for c in tables["carts"]}
    updates = [e for e in tables["cart_events"] if e["event_type"] == "quantity_updated"]
    for e in sorted(rng.sample(updates, min(n, len(updates))),
                    key=lambda e: e["event_id"]):
        cart = cart_by_id[e["cart_id"]]
        line = line_by_id[e["cart_line_id"]]
        correct = cart["cart_total"]
        cart["cart_total"] = correct - line["unit_price"] * (e["new_quantity"] - e["old_quantity"])
        _label(truth, "stale_cart_total", "carts", cart["cart_id"],
               e["event_id"], f"cart_total = {correct}",
               "cart_total still reflects the quantity before the update")

    return truth