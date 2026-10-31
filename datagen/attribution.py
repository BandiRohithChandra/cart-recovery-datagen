"""Deterministic last-touch attribution (see docs/decisions.md section 8)."""
from collections import defaultdict
from datetime import timedelta

import config


def attribute_orders(ids, orders, sends, send_events, messages, carts):
    window = timedelta(days=config.ATTRIBUTION_WINDOW_DAYS)
    min_lag = timedelta(minutes=1)

    cart_customer = {c["cart_id"]: c["customer_id"] for c in carts}
    msg_customer = {m["message_id"]: cart_customer[m["cart_id"]] for m in messages}
    send_customer = {s["send_id"]: msg_customer[s["message_id"]] for s in sends}

    # touches per customer, sorted by send_id so ties go to the lowest send_id
    touches = defaultdict(list)
    for e in sorted(send_events, key=lambda e: (e["send_id"], e["send_event_id"])):
        if e["event_type"] in ("clicked", "opened"):
            touches[send_customer[e["send_id"]]].append(e)

    rows = []
    for order in sorted(orders, key=lambda o: o["order_id"]):
        if order["status"] != "placed":
            continue
        best = {"clicked": None, "opened": None}
        for e in touches.get(order["customer_id"], []):
            gap = order["placed_at"] - e["occurred_at"]
            if gap < min_lag or gap > window:
                continue
            current = best[e["event_type"]]
            if current is None or e["occurred_at"] > current["occurred_at"]:
                best[e["event_type"]] = e  # strict ">" keeps the earlier send_id on ties

        chosen = best["clicked"] or best["opened"]
        if chosen is None:
            continue  # no qualifying touch, e.g. a late or organic purchase
        gap = order["placed_at"] - chosen["occurred_at"]
        rows.append({
            "attribution_id": ids.next("attribution"),
            "order_id": order["order_id"],
            "send_id": chosen["send_id"],
            "send_event_id": chosen["send_event_id"],
            "touch_type": "click" if chosen["event_type"] == "clicked" else "open",
            "lag_minutes": int(gap.total_seconds() // 60),
            "attributed_revenue": order["order_total"],
        })
    return rows