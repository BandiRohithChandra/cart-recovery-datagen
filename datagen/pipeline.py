"""Runs every generator in order and returns all tables."""
import random

import config
from datagen.attribution import attribute_orders
from datagen.campaigns import generate_campaigns, generate_messages
from datagen.anomalies import inject_anomalies
from datagen.carts import generate_carts
from datagen.ids import IdGenerator
from datagen.lifecycle import apply_abandonment
from datagen.master import generate_consents, generate_customers, generate_sessions
from datagen.orders import generate_orders
from datagen.sends import plan_organic_purchases, simulate_sends


def build(scale_name="starter", seed=config.SEED):
    scale = config.SCALES[scale_name]
    rng = random.Random(seed)
    ids = IdGenerator()

    customers = generate_customers(rng, ids, scale)
    consents = generate_consents(rng, ids, customers)
    sessions = generate_sessions(rng, ids, customers, scale)
    carts, lines, cart_events = generate_carts(rng, ids, customers, sessions, scale)
    apply_abandonment(rng, ids, carts, cart_events, scale)
    campaigns = generate_campaigns(ids, scale)
    messages = generate_messages(rng, ids, campaigns, carts, lines, customers, scale)
    plan = plan_organic_purchases(rng, carts)
    sends, send_events, purchase_at = simulate_sends(rng, ids, messages, carts, consents, plan)
    orders = generate_orders(rng, ids, carts, cart_events, sessions, purchase_at)
    attributions = attribute_orders(ids, orders, sends, send_events, messages, carts)

    tables = {
        "customers": customers, "consents": consents, "sessions": sessions,
        "carts": carts, "cart_lines": lines, "cart_events": cart_events,
        "campaigns": campaigns, "messages": messages,
        "send_attempts": sends, "send_events": send_events,
        "orders": orders, "attributions": attributions,
    }
    tables["ground_truth"] = inject_anomalies(rng, ids, scale, tables)
    return tables