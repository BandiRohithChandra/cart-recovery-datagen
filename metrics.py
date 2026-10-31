"""Campaign metrics from the exported CSV tables (never reads ground_truth)."""
import argparse
import csv
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path


def load(scale, name):
    path = Path("data") / scale / "tables" / f"{name}.csv"
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def pct(n, d):
        return round(float(100 * n / d), 2) if d else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", default="starter")
    scale = ap.parse_args().scale

    carts = load(scale, "carts")
    msgs = {m["message_id"]: m for m in load(scale, "message_templates")}
    sends = load(scale, "send_attempts")
    events = load(scale, "send_events")
    orders = {o["order_id"]: o for o in load(scale, "orders")}
    attrs = load(scale, "attributions")

    # Cart funnel
    abandoned = [c for c in carts if c["abandoned_at"]]
    recovered = [c for c in abandoned if c["status"] == "recovered"]
    funnel = {
        "carts": len(carts),
        "abandoned_carts": len(abandoned),
        "abandoned_pct": pct(len(abandoned), len(carts)),
        "recovered_carts": len(recovered),
        "recovery_rate_pct": pct(len(recovered), len(abandoned)),
    }

    # Send outcomes per send
    ev = defaultdict(set)
    for e in events:
        ev[e["send_id"]].add(e["event_type"])

    # Attribution: one row per order (lowest attribution_id); extras are reported, not counted
    first = {}
    extra_rows = 0
    for a in sorted(attrs, key=lambda r: r["attribution_id"]):
        if a["order_id"] in first:
            extra_rows += 1
        else:
            first[a["order_id"]] = a
    attr_by_send = defaultdict(list)
    for a in first.values():
        attr_by_send[a["send_id"]].append(a)

    suppressed = defaultdict(int)
    groups = defaultdict(lambda: defaultdict(int))  # (channel, variant) -> counters
    for s in sends:
        m = msgs[s["message_id"]]
        g = groups[(m["channel"], m["variant"])]
        g["attempts"] += 1
        if s["decision"] == "suppressed":
            suppressed[s["suppression_reason"]] += 1
            continue
        g["sent"] += 1
        types = ev[s["send_id"]]
        g["delivered"] += "delivered" in types
        g["bounced"] += "bounced" in types
        g["opened"] += "opened" in types
        g["clicked"] += "clicked" in types
        g["attributed_orders"] += len(attr_by_send.get(s["send_id"], []))

    by_variant = {}
    for (ch, var), g in sorted(groups.items()):
        by_variant[f"{ch}_{var}"] = {
            **g,
            "delivery_rate_pct": pct(g["delivered"], g["sent"]),
            "open_rate_pct": pct(g["opened"], g["delivered"]),
            "click_rate_pct": pct(g["clicked"], g["delivered"]),
            "attributed_conversion_pct": pct(g["attributed_orders"], g["sent"]),
        }

    # Revenue (per currency, never summed across currencies)
    total_rev, attr_rev = defaultdict(Decimal), defaultdict(Decimal)
    for o in orders.values():
        if o["status"] == "placed":
            total_rev[o["currency"]] += Decimal(o["order_total"])
    for a in first.values():
        attr_rev[orders[a["order_id"]]["currency"]] += Decimal(a["attributed_revenue"])
    revenue = {
        cur: {"placed_revenue": str(total_rev[cur]),
              "attributed_revenue": str(attr_rev[cur]),
              "attributed_share_pct": pct(attr_rev[cur], total_rev[cur])}
        for cur in sorted(total_rev)
    }

    placed = [o for o in orders.values() if o["status"] == "placed"]
    late = len(recovered) - len({a["order_id"] for a in first.values()
                                 if orders[a["order_id"]]["cart_id"] in
                                 {c["cart_id"] for c in recovered}})
    reconcile = {
        "placed_orders": len(placed),
        "attributed_orders": len(first),
        "attribution_rows": len(attrs),
        "extra_rows_excluded": extra_rows,
        "recovered_carts_without_attribution": late,
        "attributed_never_exceeds_placed": all(
            attr_rev[c] <= total_rev[c] for c in attr_rev),
    }

    out = {"scale": scale, "funnel": funnel,
           "sends": {"attempts": len(sends),
                     "sent": sum(g["sent"] for g in groups.values()),
                     "suppressed": dict(sorted(suppressed.items()))},
           "by_channel_variant": by_variant, "revenue": revenue,
           "reconciliation": reconcile}

    Path("data", f"metrics_{scale}.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()