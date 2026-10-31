"""Send simulation: SendAttempt, SendEvent and purchase timing
(see docs/decisions.md sections 5 to 10).

Messages are processed in attempt-time order. Each one is checked against
purchases, consent and frequency caps; if sent, delivery, open and click
outcomes are drawn. A click can lead to a purchase, which suppresses the
cart's later messages.
"""
from collections import defaultdict
from datetime import timedelta

import config

ORGANIC_RATE = 0.05   # abandoned carts bought within 72 hours without any click
LATE_RATE = 0.03      # abandoned carts bought 15 to 28 days later (outside every window)
DELIVERY_RATE = {"email": 0.97, "sms": 0.98}
OPEN_RATE = {"A": 0.30, "B": 0.38}
OPEN_FACTOR_BY_SEQUENCE = {1: 1.0, 2: 0.7}
CLICK_AFTER_OPEN = {"A": 0.25, "B": 0.32}
SMS_CLICK_RATE = {"A": 0.12, "B": 0.15}
CONVERT_AFTER_CLICK = {"A": 0.18, "B": 0.22}


def plan_organic_purchases(rng, carts):
    """Some abandoned carts are bought again without a message driving it."""
    plan = {}
    for cart in carts:
        if cart["status"] != "abandoned":
            continue
        r = rng.random()
        if r < ORGANIC_RATE:
            plan[cart["cart_id"]] = cart["abandoned_at"] + timedelta(
                minutes=rng.randint(10, 72 * 60))
        elif r < ORGANIC_RATE + LATE_RATE:
            plan[cart["cart_id"]] = cart["abandoned_at"] + timedelta(
                days=rng.randint(15, 28), minutes=rng.randint(0, 1439))
    return plan


def _outcome(rng, ids, send_id, msg, attempted):
    """Delivery, open and click events for one sent message.

    Returns (events, purchase_time or None).
    """
    variant = msg["variant"]
    rows = []

    def add(kind, at):
        rows.append({
            "send_event_id": ids.next("send_event"),
            "send_id": send_id,
            "event_type": kind,
            "occurred_at": at,
        })

    if rng.random() >= DELIVERY_RATE[msg["channel"]]:
        add("bounced", attempted + timedelta(seconds=rng.randint(5, 600)))
        return rows, None

    delivered = attempted + timedelta(seconds=rng.randint(1, 60))
    add("delivered", delivered)

    click_at = None
    if msg["channel"] == "email":
        p_open = OPEN_RATE[variant] * OPEN_FACTOR_BY_SEQUENCE.get(msg["sequence"], 1.0)
        if rng.random() < p_open:
            minutes = min(int(rng.lognormvariate(3.4, 1.2)), 2880)
            opened = delivered + timedelta(minutes=minutes, seconds=rng.randint(0, 59))
            add("opened", opened)
            if rng.random() < 0.15:
                add("opened", opened + timedelta(minutes=rng.randint(5, 720)))
            if rng.random() < CLICK_AFTER_OPEN[variant]:
                click_at = opened + timedelta(seconds=rng.randint(5, 600))
    elif rng.random() < SMS_CLICK_RATE[variant]:
        minutes = min(int(rng.lognormvariate(2.5, 1.0)), 1440)
        click_at = delivered + timedelta(minutes=minutes, seconds=rng.randint(0, 59))

    if click_at is None:
        return rows, None
    add("clicked", click_at)

    if rng.random() >= CONVERT_AFTER_CLICK[variant]:
        return rows, None
    if rng.random() < 0.85:
        delay = timedelta(minutes=rng.randint(5, 360))
    else:
        delay = timedelta(days=rng.randint(1, 6), minutes=rng.randint(0, 1439))
    return rows, click_at + delay


def simulate_sends(rng, ids, messages, carts, consents, purchase_plan):
    """Returns (send_attempts, send_events, purchase_at) where purchase_at maps
    cart_id to the time the cart is bought (organic, late or click-driven)."""
    cart_by_id = {c["cart_id"]: c for c in carts}

    history = defaultdict(list)  # (customer_id, channel) -> consent rows by time
    for row in sorted(consents, key=lambda c: (c["effective_from"], c["consent_id"])):
        history[(row["customer_id"], row["channel"])].append(row)

    purchase_at = dict(purchase_plan)

    queue = []
    for msg in messages:
        cart = cart_by_id[msg["cart_id"]]
        scheduled = cart["abandoned_at"] + timedelta(minutes=msg["delay_minutes"])
        attempted = scheduled + timedelta(seconds=rng.randint(0, 300))
        queue.append((attempted, msg["message_id"], scheduled, msg, cart))
    queue.sort(key=lambda q: (q[0], q[1]))

    day, week = timedelta(hours=24), timedelta(days=7)
    sent = defaultdict(list)  # customer_id -> [(attempted_at, channel)]
    attempts, events = [], []

    for attempted, _, scheduled, msg, cart in queue:
        customer, channel = cart["customer_id"], msg["channel"]

        in_force = None  # the consent row in force at attempted_at
        for row in history.get((customer, channel), []):
            if row["effective_from"] > attempted:
                break
            in_force = row

        bought = purchase_at.get(cart["cart_id"])
        recent = sent[customer]
        reason = None
        if bought is not None and bought <= attempted:
            reason = "purchased_before_send"
        elif in_force is None:
            reason = "no_consent_record"
        elif in_force["status"] == "opt_out":
            reason = "opted_out"
        elif sum(1 for t, ch in recent
                 if ch == channel and t > attempted - day
                 ) >= config.MAX_SENDS_PER_CHANNEL_PER_24H:
            reason = "frequency_cap_24h"
        elif sum(1 for t, _ in recent if t > attempted - week) >= config.MAX_SENDS_PER_7D:
            reason = "frequency_cap_7d"

        send_id = ids.next("send")
        attempts.append({
            "send_id": send_id,
            "message_id": msg["message_id"],
            "scheduled_at": scheduled,
            "attempted_at": attempted,
            "decision": "suppressed" if reason else "sent",
            "suppression_reason": reason,
            "consent_id_checked": in_force["consent_id"] if in_force else None,
        })

        if reason is None:
            recent.append((attempted, channel))
            rows, candidate = _outcome(rng, ids, send_id, msg, attempted)
            events.extend(rows)
            cart_id = cart["cart_id"]
            if candidate is not None and (cart_id not in purchase_at
                                          or candidate < purchase_at[cart_id]):
                purchase_at[cart_id] = candidate

    return attempts, events, purchase_at