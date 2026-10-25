#!/usr/bin/env python3
"""Cheap checks before a deck run: stale skill backups and local-media platform."""
from __future__ import annotations

import platform
from pathlib import Path


def check(home: Path | None = None, machine: str | None = None) -> tuple[list[str], list[str]]:
    home = Path(home or Path.home())
    skill_root = Path(__file__).resolve().parents[1]
    errors, warnings = [], []
    roots = [skill_root.parent, home / ".claude" / "skills"]
    seen = set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        stale = list((root / ".backups").rglob("SKILL.md"))
        if stale:
            errors.append(f"discoverable backup SKILL.md: {stale[0]} (run install.sh)")
            break
    active = skill_root / "SKILL.md"
    if not active.is_file():
        warnings.append(f"active skill not found at {active}; using the repo path")
    machine = machine or platform.machine()
    if platform.system() == "Darwin" and machine != "arm64":
        warnings.append("Intel Mac: local transcription is best-effort; PDF/YouTube paths remain")
    return errors, warnings


def main() -> int:
    errors, warnings = check()
    for line in errors:
        print("ERROR", line)
    for line in warnings:
        print("warn ", line)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
