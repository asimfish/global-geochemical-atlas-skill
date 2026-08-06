#!/usr/bin/env python3
"""Retired compatibility entry point for the former out-of-repo asset split."""

from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    parser.exit(
        2,
        "split_private_assets.py is retired: evaluator sources now live in "
        "evaluation/evaluator_private, and tested agents receive only "
        "evaluation/ai_visible_public.\n",
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
