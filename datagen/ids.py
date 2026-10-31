"""Deterministic ID generation (see docs/decisions.md section 12)."""
import re

YEAR = 2026

# prefix -> (format string, validation regex)
_FORMATS = {
    "customer": ("CUS-{n:06d}", r"^CUS-\d{6}$"),
    "consent":  ("CON-{n:06d}", r"^CON-\d{6}$"),
    "session":  (f"SES-{YEAR}-{{n:06d}}", r"^SES-\d{4}-\d{6}$"),
    "device":   ("DEV-{n:06d}", r"^DEV-\d{6}$"),
    "cart":     (f"CART-{YEAR}-{{n:06d}}", r"^CART-\d{4}-\d{6}$"),
    "cart_line": ("CLN-{n:06d}", r"^CLN-\d{6}$"),
    "cart_event": ("CEV-{n:06d}", r"^CEV-\d{6}$"),
    "campaign": (f"CMP-{YEAR}-{{n:06d}}", r"^CMP-\d{4}-\d{6}$"),
    "send":     (f"SEND-{YEAR}-{{n:06d}}", r"^SEND-\d{4}-\d{6}$"),
    "send_event": ("SEV-{n:06d}", r"^SEV-\d{6}$"),
    "order":    (f"ORD-{YEAR}-{{n:06d}}", r"^ORD-\d{4}-\d{6}$"),
    "attribution": (f"ATR-{YEAR}-{{n:06d}}", r"^ATR-\d{4}-\d{6}$"),
}

MESSAGE_ID_PATTERN = r"^MSG-CART-\d{4}-\d{6}-\d{2}$"


class IdGenerator:
    """One counter per entity type. Counters only go up."""

    def __init__(self):
        self._counters = {key: 0 for key in _FORMATS}

    def next(self, kind: str) -> str:
        self._counters[kind] += 1
        return _FORMATS[kind][0].format(n=self._counters[kind])

    @staticmethod
    def message_id(cart_id: str, sequence: int) -> str:
        """MSG-<cart-id>-NN, e.g. MSG-CART-2026-000001-01."""
        return f"MSG-{cart_id}-{sequence:02d}"


def is_valid(kind: str, value: str) -> bool:
    return re.match(_FORMATS[kind][1], value) is not None


def is_valid_message_id(value: str) -> bool:
    return re.match(MESSAGE_ID_PATTERN, value) is not None