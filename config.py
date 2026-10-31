"""Central configuration. All rules and volumes live here (see docs/decisions.md)."""
from dataclasses import dataclass
from datetime import datetime

SEED = 20261022

# Data period (UTC), decisions.md section 2
PERIOD_START = datetime(2026, 1, 1)
PERIOD_END = datetime(2026, 9, 30, 23, 59, 59)

COUNTRIES = ("IN", "SA", "AE", "US")
CURRENCY_BY_COUNTRY = {"IN": "INR", "SA": "SAR", "AE": "AED", "US": "USD"}


@dataclass(frozen=True)
class Scale:
    name: str
    n_customers: int
    n_carts: int
    abandon_rate: float   # target share of carts that end up abandoned
    n_sends: int          # target number of SendAttempt rows
    n_campaigns: int


SCALES = {
    "starter": Scale("starter", n_customers=400, n_carts=1_000,
                     abandon_rate=0.40, n_sends=200, n_campaigns=4),
    "full": Scale("full", n_customers=20_000, n_carts=50_000,
                  abandon_rate=0.40, n_sends=10_000, n_campaigns=20),
}

# Business rules (decisions.md sections 4 to 8)
ABANDONMENT_WINDOW_MINUTES = 60
ATTRIBUTION_WINDOW_DAYS = 7
MAX_SENDS_PER_CHANNEL_PER_24H = 1
MAX_SENDS_PER_7D = 3

# Message sequence: (sequence, channel, delay_minutes)
MESSAGE_SEQUENCE = (
    (1, "email", 60),
    (2, "email", 1440),
    (3, "sms", 4320),
)