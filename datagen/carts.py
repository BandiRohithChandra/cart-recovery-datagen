"""Product catalog, Cart, CartLine and CartEvent generation (see docs/data_dictionary.md)."""
from datetime import timedelta
from decimal import Decimal

import config

ADJECTIVES = (
    "Classic", "Modern", "Premium", "Everyday", "Compact",
    "Deluxe", "Eco", "Urban", "Essential", "Signature",
)
NOUNS = (
    "T-Shirt", "Hoodie", "Jeans", "Sneakers", "Backpack", "Wallet", "Watch",
    "Sunglasses", "Water Bottle", "Headphones", "Phone Case", "Power Bank",
    "Desk Lamp", "Notebook", "Mug", "Cushion Cover", "Bath Towel", "Bedsheet",
    "Candle", "Plant Pot", "Yoga Mat", "Dumbbell Set", "Face Wash",
    "Moisturizer", "Perfume", "Lipstick", "Hair Dryer", "Coffee Maker",
    "Blender", "Lunch Box",
)
N_SKUS = len(ADJECTIVES) * len(NOUNS)  # 300

# fixed illustrative rates, so prices are reproducible
FX_FROM_INR = {
    "INR": Decimal("1"), "SAR": Decimal("0.045"),
    "AED": Decimal("0.044"), "USD": Decimal("0.012"),
}
CENT = Decimal("0.01")

LINES_PER_CART = ((1, 0.45), (2, 0.28), (3, 0.15), (4, 0.08), (5, 0.04))
QUANTITY_WEIGHTS = ((1, 0.70), (2, 0.18), (3, 0.07), (4, 0.03), (5, 0.02))
QTY_UPDATE_RATE = 0.20  # share of carts with one quantity update


def generate_catalog(rng):
    catalog = []
    for i in range(N_SKUS):
        base = int(min(max(rng.lognormvariate(6.5, 0.7), 150), 15000))
        catalog.append({
            "product_sku": f"SKU-{i + 1:04d}",
            "product_name": f"{ADJECTIVES[i // len(NOUNS)]} {NOUNS[i % len(NOUNS)]}",
            "base_price_inr": base // 10 * 10 + 9,
        })
    return catalog


def _price(item, currency):
    return (Decimal(item["base_price_inr"]) * FX_FROM_INR[currency]).quantize(CENT)


def _event(ids, cart_id, session_id, event_type, at,
           line_id=None, old_q=None, new_q=None):
    return {
        "event_id": ids.next("cart_event"),
        "cart_id": cart_id,
        "session_id": session_id,
        "event_type": event_type,
        "cart_line_id": line_id,
        "old_quantity": old_q,
        "new_quantity": new_q,
        "occurred_at": at,
    }


def generate_carts(rng, ids, customers, sessions, scale):
    if len(sessions) < scale.n_carts:
        raise ValueError("Not enough sessions for the requested number of carts")

    catalog = generate_catalog(rng)
    country = {c["customer_id"]: c["country_code"] for c in customers}
    counts = [n for n, _ in LINES_PER_CART]
    count_w = [w for _, w in LINES_PER_CART]
    qtys = [q for q, _ in QUANTITY_WEIGHTS]
    qty_w = [w for _, w in QUANTITY_WEIGHTS]

    # each cart gets its own session; carts are numbered in time order
    chosen = sorted(rng.sample(sessions, scale.n_carts),
                    key=lambda s: (s["started_at"], s["session_id"]))

    carts, lines, events = [], [], []
    for session in chosen:
        customer_id = session["customer_id"]
        session_id = session["session_id"]
        currency = config.CURRENCY_BY_COUNTRY[country[customer_id]]
        cart_id = ids.next("cart")

        duration = int((session["last_activity_at"] - session["started_at"]).total_seconds())
        created = session["started_at"] + timedelta(seconds=rng.randint(0, duration // 2))
        events.append(_event(ids, cart_id, session_id, "cart_created", created))

        t = created
        cart_lines = []
        for item in rng.sample(catalog, rng.choices(counts, count_w)[0]):
            quantity = rng.choices(qtys, qty_w)[0]
            unit_price = _price(item, currency)
            line = {
                "cart_line_id": ids.next("cart_line"),
                "cart_id": cart_id,
                "product_sku": item["product_sku"],
                "product_name": item["product_name"],
                "unit_price": unit_price,
                "quantity": quantity,
                "line_total": unit_price * quantity,
            }
            cart_lines.append(line)
            t += timedelta(seconds=rng.randint(5, 120))
            events.append(_event(ids, cart_id, session_id, "line_added", t,
                                 line_id=line["cart_line_id"]))

        if rng.random() < QTY_UPDATE_RATE:
            line = rng.choice(cart_lines)
            old_q = line["quantity"]
            new_q = rng.choice([q for q in range(1, 6) if q != old_q])
            t += timedelta(seconds=rng.randint(30, 600))
            events.append(_event(ids, cart_id, session_id, "quantity_updated", t,
                                 line_id=line["cart_line_id"], old_q=old_q, new_q=new_q))
            line["quantity"] = new_q
            line["line_total"] = line["unit_price"] * new_q  # recomputed, never stale

        lines.extend(cart_lines)
        carts.append({
            "cart_id": cart_id,
            "customer_id": customer_id,
            "session_id": session_id,
            "currency": currency,
            "status": "active",  # derived from events in the next step
            "created_at": created,
            "last_activity_at": t,
            "abandoned_at": None,
            "cart_total": sum((l["line_total"] for l in cart_lines), Decimal("0.00")),
        })
    return carts, lines, events