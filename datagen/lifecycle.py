"""Abandonment logic (see docs/decisions.md section 4)."""
from datetime import timedelta

import config
from datagen.carts import _event as make_event

FAST_PURCHASE_SHARE = 0.90   # direct purchases made within 1 to 30 minutes
FAST_MAX_SECONDS = 30 * 60
BOUNDARY_MIN_SECONDS = 50 * 60  # slow purchases land 50 to 59:59 after last activity


def apply_abandonment(rng, ids, carts, events, scale):
    """Marks carts abandoned, or bought directly inside the 60-minute window.

    Changes carts and events in place. The exact abandoned count is
    round(n_carts x abandon_rate). Abandoned carts get an 'abandoned' event at
    last_activity_at + 60 minutes. All others get a 'purchased' event
    1 second to 59:59 after last activity.
    """
    window = timedelta(minutes=config.ABANDONMENT_WINDOW_MINUTES)
    window_seconds = config.ABANDONMENT_WINDOW_MINUTES * 60
    n_abandoned = round(len(carts) * scale.abandon_rate)
    abandoned_ids = {c["cart_id"] for c in rng.sample(carts, n_abandoned)}

    for cart in carts:
        last = cart["last_activity_at"]
        if cart["cart_id"] in abandoned_ids:
            at = last + window
            events.append(make_event(ids, cart["cart_id"], cart["session_id"],
                                     "abandoned", at))
            cart["status"] = "abandoned"
            cart["abandoned_at"] = at
        else:
            if rng.random() < FAST_PURCHASE_SHARE:
                delay = rng.randint(60, FAST_MAX_SECONDS)
            else:
                delay = rng.randint(BOUNDARY_MIN_SECONDS, window_seconds - 1)
            events.append(make_event(ids, cart["cart_id"], cart["session_id"],
                                     "purchased", last + timedelta(seconds=delay)))
            cart["status"] = "purchased"