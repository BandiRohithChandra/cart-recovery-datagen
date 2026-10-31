"""Single entry point.

Usage: python generate.py --scale starter|full [--seed 20261022] [--out data]
"""
import argparse
from pathlib import Path

import config
from datagen.export import export_all
from datagen.pipeline import build


def main():
    parser = argparse.ArgumentParser(description="Generate the cart recovery dataset.")
    parser.add_argument("--scale", choices=sorted(config.SCALES), default="starter")
    parser.add_argument("--seed", type=int, default=config.SEED)
    parser.add_argument("--out", default="data")
    args = parser.parse_args()

    tables = build(args.scale, args.seed)
    target = Path(args.out) / args.scale
    manifest = export_all(tables, args.scale, args.seed, target)

    print(f"scale={args.scale} seed={args.seed} output={target}")
    for name, count in manifest["row_counts"].items():
        print(f"  {name:<20}{count:>9,}")


if __name__ == "__main__":
    main()