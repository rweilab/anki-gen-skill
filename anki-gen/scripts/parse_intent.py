#!/usr/bin/env python3
"""Parse a natural-language request into a structured intent dict.

A lexicon, not a parser: it catches the obvious shapes (a date filter, a
--deck-name, a path to merge into) and the model reads the request itself for
everything else. Run it so `audit_web` and `merge_target` are not quietly lost
from what the user asked for.

There is no resume path. It used to look for a `/tmp/anki-gen-*` session
directory holding a `progress.jsonl` -- a directory nothing in this skill ever
created, because extraction moved to `./.anki-gen-temp/` precisely to stop
writing to /tmp. Removed rather than kept, since a resume that cannot find its
session is worse than no resume at all.
"""
import json
import re
import sys
from typing import Any, Dict


def parse_intent(user_input: str, cwd: str = ".") -> Dict[str, Any]:
    """Parse natural language into a structured intent (fallback for simple cases)."""
    intent = {
        "sources": [],
        "date_filter": None,
        "merge_target": None,
        "audit_web": False,
        "course_hint": None,
        "recursive": True,
        "output_path": None,
        "deck_name": None,
        "max_cards": None,
        "video_url": None,
        "video_playlist": False,
        "video_items": None,
        "video_frames": None,
        "video_search": None,
    }

    text = user_input.lower()

    # Check for web audit
    if any(kw in text for kw in ["audit", "check for existing", "check online",
                                 "web deck", "existing deck"]):
        intent["audit_web"] = True

    # Extract merge target
    merge_patterns = [
        r"merge.*?([~/][^\s]+\.apkg)",
        r"merge.*?([~/][^\s]+)",
        r"into.*?([~/][^\s]+\.apkg)",
    ]
    for pattern in merge_patterns:
        found = re.search(pattern, user_input, re.IGNORECASE)
        if found:
            intent["merge_target"] = found.group(1)
            break

    # Extract date filter. Bounded at " and " as well as a comma or full stop: the
    # old pattern ran to the end of the clause, so "since oct 1 and merge into
    # ~/decks/x.apkg" captured "oct 1 and merge into ~/decks/x" as the date.
    for pattern in [r"(?:after|since)\s+(\d{1,2}/\d{1,2})",                 # 9/11
                    r"(?:after|since)\s+([^,\.]+?)(?=\s+and\b|[,\.]|$)",   # sept 11
                    r"(last\s+\w+)", "yesterday"]:
        found = re.search(pattern, user_input, re.IGNORECASE)
        if found:
            intent["date_filter"] = found.group(0).strip()
            break

    # Extract merge target from flags. NOTE: this read `match.group(1)` -- the loop
    # variable left over from the date filter above -- so `--merge-existing X` either
    # picked up a date or crashed on a None. It uses its own match now.
    merge_match = re.search(r"--merge-existing\s+(\S+)", user_input)
    if merge_match:
        intent["merge_target"] = merge_match.group(1)

    # Check for audit flag
    if "--audit" in user_input or "--audit-web" in user_input:
        intent["audit_web"] = True

    # Check for output path
    output_match = re.search(r"--output\s+(\S+)", user_input)
    if output_match:
        intent["output_path"] = output_match.group(1)

    # Check for deck name. Quoted names keep their spaces; :: nesting survives.
    deck_match = re.search(
        r"--deck-name\s+(?:\"([^\"]+)\"|'([^']+)'|(\S+))", user_input)
    if deck_match:
        intent["deck_name"] = next(g for g in deck_match.groups() if g)

    # Max cards is advisory: the quality contract says deck value is not size.
    max_cards_match = re.search(
        r"--max-cards\s+(\d+)|\b(?:make|generate|create)\s+(\d+)\s+cards?\b",
        user_input, re.I)
    if max_cards_match:
        intent["max_cards"] = int(next(g for g in max_cards_match.groups() if g))

    # Video sources: URL/playlist/range/frames; the host model reads the prose.
    vid = re.search(r"https?://(?:www\.)?(?:youtube\.com|youtu\.be)/\S+", user_input)
    if vid:
        intent["video_url"] = vid.group(0)
    if re.search(r"\bwhole playlist\b|\bplaylist\b", user_input, re.I):
        intent["video_playlist"] = True
    items = re.search(r"\bvideos?\s+(\d+)\s*[-–]\s*(\d+)\b", user_input, re.I)
    if items:
        intent["video_items"] = f"{items.group(1)}-{items.group(2)}"
    if re.search(r"\b(images?|frames?|stills?|screenshots?)\b", user_input, re.I):
        intent["video_frames"] = "yes"
    search = re.search(r"\bfind\s+(?:me\s+)?(.+?)(?:\s+on youtube|$)", user_input, re.I)
    if search:
        intent["video_search"] = search.group(1).strip()

    return intent


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: parse_intent.py '<user_input>' [cwd]")
        sys.exit(0 if len(sys.argv) > 1 else 1)

    print(json.dumps(parse_intent(sys.argv[1],
                                  sys.argv[2] if len(sys.argv) > 2 else ".")))
