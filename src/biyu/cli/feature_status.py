"""Print one public feature boolean without exposing the private config file."""
from __future__ import annotations

import argparse

from biyu.config import feature_enabled


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    args = parser.parse_args()
    print("true" if feature_enabled(args.name) else "false")


if __name__ == "__main__":
    main()
