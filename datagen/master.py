"""Customer and Consent generation (see docs/data_dictionary.md)."""
from datetime import timedelta

import config
from datagen.util import rand_between

FIRST_NAMES = (
    "Aarav", "Vihaan", "Ananya", "Diya", "Rohan", "Priya", "Karan", "Sneha",
    "Omar", "Layla", "Yusuf", "Noor", "Khalid", "Fatima", "Hassan", "Mariam",
    "James", "Emma", "Liam", "Olivia", "Noah", "Sophia", "Ethan", "Ava",
)
COUNTRY_WEIGHTS = (("IN", 0.50), ("SA", 0.20), ("AE", 0.15), ("US", 0.15))
DIAL_CODES = {"IN": "+91", "SA": "+966", "AE": "+971", "US": "+1"}

PHONE_RATE = 0.85         # share of customers with a phone number
EMAIL_OPTIN_RATE = 0.92   # share of customers who ever opt in to email
SMS_OPTIN_RATE = 0.60     # share of customers with a phone who opt in to SMS
WITHDRAW_RATE = 0.10      # share of opted-in customers who later opt out
REOPTIN_RATE = 0.15       # share of withdrawers who opt in again


def generate_customers(rng, ids, scale):
    countries = [c for c, _ in COUNTRY_WEIGHTS]
    weights = [w for _, w in COUNTRY_WEIGHTS]
    earliest = config.PERIOD_START - timedelta(days=365)
    latest = config.PERIOD_END - timedelta(days=14)
    customers = []
    for i in range(1, scale.n_customers + 1):
        country = rng.choices(countries, weights)[0]
        first_name = rng.choice(FIRST_NAMES)
        has_phone = rng.random() < PHONE_RATE
        customers.append({
            "customer_id": ids.next("customer"),
            "first_name": first_name,
            "email": f"{first_name.lower()}.{i:06d}@example.com",
            "phone": f"{DIAL_CODES[country]}{5550000000 + i}" if has_phone else None,
            "country_code": country,
            "created_at": rand_between(rng, earliest, latest),
        })
    return customers


def generate_consents(rng, ids, customers):
    rows = []
    for cust in customers:
        for channel in ("email", "sms"):
            if channel == "sms" and cust["phone"] is None:
                continue  # SMS consent requires a phone number
            rate = EMAIL_OPTIN_RATE if channel == "email" else SMS_OPTIN_RATE
            if rng.random() >= rate:
                continue  # no consent row at all = treated as not consented
            rows.extend(_channel_history(rng, ids, cust, channel))
    return rows


def _event(ids, cust, channel, status, effective_from, source, lag_minutes=0):
    return {
        "consent_id": ids.next("consent"),
        "customer_id": cust["customer_id"],
        "channel": channel,
        "status": status,
        "effective_from": effective_from,
        "recorded_at": effective_from + timedelta(minutes=lag_minutes),
        "source": source,
    }


def _channel_history(rng, ids, cust, channel):
    created = cust["created_at"]
    if rng.random() < 0.7:
        start, source = created, "signup"
    else:
        start = created + timedelta(minutes=rng.randrange(60, 10 * 24 * 60))
        source = "checkout"
    events = [_event(ids, cust, channel, "opt_in", start, source)]

    if rng.random() >= WITHDRAW_RATE:
        return events

    out_at = rand_between(rng, start + timedelta(days=1), config.PERIOD_END)
    out_source = rng.choice(
        ("unsubscribe_link", "preference_center") if channel == "email"
        else ("sms_stop", "preference_center")
    )
    # most withdrawals are recorded immediately; some are recorded late
    lag = 0 if rng.random() < 0.8 else rng.randrange(1, 48 * 60)
    events.append(_event(ids, cust, channel, "opt_out", out_at, out_source, lag))

    if rng.random() < REOPTIN_RATE and out_at + timedelta(days=1) < config.PERIOD_END:
        in_at = rand_between(rng, out_at + timedelta(days=1), config.PERIOD_END)
        events.append(_event(ids, cust, channel, "opt_in", in_at, "preference_center"))
    return events