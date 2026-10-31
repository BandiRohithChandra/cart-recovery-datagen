"""Campaign and MessageTemplate generation (see docs/data_dictionary.md)."""
import math
from datetime import timedelta

import config

PERIOD_DAYS = (config.PERIOD_END.date() - config.PERIOD_START.date()).days + 1
LABELS = {1: "1H", 2: "26H", 3: "72H"}

SUBJECTS = {
    "A": "{first_name}, you left something in your cart",
    "B": "Still thinking about {product_name}?",
}
BODIES = {
    (1, "A"): "Hi {first_name}, your {product_name} is still waiting in your cart. Complete your order when you are ready.",
    (1, "B"): "Hi {first_name}, you were looking at {product_name}. It is saved in your cart whenever you want to come back.",
    (2, "A"): "Hi {first_name}, {product_name} is still in your cart and selling fast. Finish checkout today.",
    (2, "B"): "Hi {first_name}, a quick reminder: {product_name} is still saved in your cart.",
    (3, "A"): "Hi {first_name}, {product_name} is still in your cart. Finish checkout today.",
    (3, "B"): "Hi {first_name}, your cart is waiting with {product_name}. Come back and finish your order.",
}


def generate_campaigns(ids, scale):
    """Contiguous date windows covering the whole data period."""
    first_day = config.PERIOD_START.date()
    campaigns = []
    for i in range(scale.n_campaigns):
        start = first_day + timedelta(days=i * PERIOD_DAYS // scale.n_campaigns)
        end = first_day + timedelta(days=(i + 1) * PERIOD_DAYS // scale.n_campaigns - 1)
        campaigns.append({
            "campaign_id": ids.next("campaign"),
            "name": f"Cart Recovery {i + 1:02d}",
            "status": "completed",
            "start_date": start,
            "end_date": end,
            "abandonment_window_minutes": config.ABANDONMENT_WINDOW_MINUTES,
            "attribution_window_days": config.ATTRIBUTION_WINDOW_DAYS,
            "max_sends_per_channel_per_24h": config.MAX_SENDS_PER_CHANNEL_PER_24H,
            "max_sends_per_7d": config.MAX_SENDS_PER_7D,
        })
    return campaigns


def _campaign_for(campaigns, day):
    for camp in campaigns:
        if camp["start_date"] <= day <= camp["end_date"]:
            return camp
    return campaigns[-1]


def generate_messages(rng, ids, campaigns, carts, lines, customers, scale):
    """Plans messages for a sample of abandoned carts; exactly scale.n_sends rows."""
    abandoned = [c for c in carts if c["status"] == "abandoned"]
    n_target = math.ceil(scale.n_sends / len(config.MESSAGE_SEQUENCE))
    if n_target > len(abandoned):
        raise ValueError("Not enough abandoned carts for the requested number of sends")
    targeted = sorted(rng.sample(abandoned, n_target), key=lambda c: c["cart_id"])

    first_name = {c["customer_id"]: c["first_name"] for c in customers}
    first_product = {}
    for line in lines:
        first_product.setdefault(line["cart_id"], line["product_name"])

    messages = []
    for cart in targeted:
        camp = _campaign_for(campaigns, cart["abandoned_at"].date())
        variant = rng.choice(("A", "B"))
        fields = {
            "first_name": first_name[cart["customer_id"]],
            "product_name": first_product[cart["cart_id"]],
        }
        for sequence, channel, delay in config.MESSAGE_SEQUENCE:
            messages.append({
                "message_id": ids.message_id(cart["cart_id"], sequence),
                "campaign_id": camp["campaign_id"],
                "cart_id": cart["cart_id"],
                "sequence": sequence,
                "channel": channel,
                "variant": variant,
                "template_code": f"{channel.upper()}_{LABELS[sequence]}_{variant}",
                "delay_minutes": delay,
                "subject": SUBJECTS[variant].format(**fields) if channel == "email" else None,
                "body": BODIES[(sequence, variant)].format(**fields),
                "created_at": cart["abandoned_at"],
            })
    return messages[:scale.n_sends]