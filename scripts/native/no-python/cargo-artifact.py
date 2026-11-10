#!/usr/bin/env python3
"""Resolve one Cargo executable artifact from --message-format=json output."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def resolve(stream, target_name: str) -> Path:
    matches: set[Path] = set()
    for line_number, line in enumerate(stream, 1):
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid Cargo JSON on line {line_number}: {exc}") from exc
        if message.get("reason") != "compiler-artifact":
            continue
        target = message.get("target") or {}
        executable = message.get("executable")
        if target.get("name") == target_name and executable:
            matches.add(Path(executable))
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one executable artifact named {target_name!r}; "
            f"found {len(matches)}"
        )
    artifact = matches.pop()
    if not artifact.is_file() or not os.access(artifact, os.X_OK):
        raise ValueError(f"Cargo artifact is missing or not executable: {artifact}")
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", required=True, type=Path)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    try:
        with args.json.open(encoding="utf-8") as cargo_output:
            print(resolve(cargo_output, args.target))
    except (OSError, ValueError) as exc:
        print(f"cargo artifact discovery failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
