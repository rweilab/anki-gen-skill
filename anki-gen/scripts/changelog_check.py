#!/usr/bin/env python3
"""Fail if VERSION and CHANGELOG's latest section disagree or the section is empty."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
version = (ROOT / "VERSION").read_text().strip()
text = (ROOT / "CHANGELOG.md").read_text()
headings = re.findall(r"^## v([0-9]+(?:\.[0-9]+)*)\b.*$", text, re.M)
if not headings:
    print("changelog_check: no versioned sections", file=sys.stderr)
    raise SystemExit(1)
if headings[0] != version:
    print(f"changelog_check: VERSION {version} != latest changelog v{headings[0]}",
          file=sys.stderr)
    raise SystemExit(1)
section = text.split(f"## v{headings[0]}", 1)[1]
section = re.split(r"^## v[0-9]", section, maxsplit=1, flags=re.M)[0]
if not re.search(r"^- ", section, re.M):
    print(f"changelog_check: v{version} has no entry", file=sys.stderr)
    raise SystemExit(1)
print(f"ok    changelog v{version}")
