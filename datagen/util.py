"""Small shared helpers."""
from datetime import datetime, timedelta


def rand_between(rng, start: datetime, end: datetime) -> datetime:
    """Random whole-second timestamp in [start, end). Uses the shared seeded rng."""
    seconds = int((end - start).total_seconds())
    return start + timedelta(seconds=rng.randrange(seconds))