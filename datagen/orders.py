"""Order generation and final cart statuses (see docs/decisions.md section 8)."""
from datetime import timedelta

from datagen.carts import _event as make_event

CANCEL_RATE = 0.02
DIFFERENT_DEVICE_RATE = 0.60


def generate_orders(rng, ids, carts, events, sessions, purchase_at):
    """One order per bought cart.

    Direct purchases reuse the existing 'purchased' event. Abandoned carts in
    purchase_at become 'recovered': a new session and a 'recovered' event are
    added. carts, events and sessions are changed in place.
    """
    session_by_id = {s["session_id"]: s for s in sessions}
    devices = {}  # customer_id -> {device_id: device_type}
    for s in sessions:
        devices.setdefault(s["customer_id"], {})[s["device_id"]] = s["device_type"]

    direct = {e["cart_id"]: e["occurred_at"]
              for e in events if e["event_type"] == "purchased"}

    items = []
    for cart in carts:
        if cart["status"] == "purchased":
            items.append((direct[cart["cart_id"]], cart["cart_id"]))
        elif cart["cart_id"] in purchase_at:
            items.append((purchase_at[cart["cart_id"]], cart["cart_id"]))
    items.sort()

    cart_by_id = {c["cart_id"]: c for c in carts}
    orders, new_sessions, new_events = [], [], []

    for placed_at, cart_id in items:
        cart = cart_by_id[cart_id]
        if cart["status"] == "abandoned":
            old_device = session_by_id[cart["session_id"]]["device_id"]
            known = devices[cart["customer_id"]]
            others = [d for d in known if d != old_device]
            if others and rng.random() < DIFFERENT_DEVICE_RATE:
                device_id = rng.choice(others)
            else:
                device_id = old_device
            session_id = ids.next("session")
            new_sessions.append({
                "session_id": session_id,
                "customer_id": cart["customer_id"],
                "device_id": device_id,
                "device_type": known[device_id],
                "started_at": placed_at - timedelta(minutes=rng.randint(2, 30)),
                "last_activity_at": placed_at + timedelta(minutes=rng.randint(1, 10)),
            })
            new_events.append(make_event(ids, cart_id, session_id, "recovered", placed_at))
            cart["status"] = "recovered"
        else:
            session_id = cart["session_id"]

        orders.append({
            "order_id": ids.next("order"),
            "customer_id": cart["customer_id"],
            "cart_id": cart_id,
            "session_id": session_id,
            "currency": cart["currency"],
            "order_total": cart["cart_total"],
            "status": "cancelled" if rng.random() < CANCEL_RATE else "placed",
            "placed_at": placed_at,
        })

    events.extend(new_events)
    sessions.extend(new_sessions)
    return orders