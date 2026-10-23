#!/usr/bin/env python3
"""Attach, audit, revise, snapshot, and revert an imported Anki deck.

Plaintext intent is the interface; note IDs stay internal. Live operations use
AnkiConnect only. New .apkg generation stays offline.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import deck_context as dc  # noqa: E402
from anki_connect import AnkiConnectError  # noqa: E402
from dossier import validate as validator  # noqa: E402
from dossier.errors import DossierError  # noqa: E402
from revision_ops import attach as attach_ops  # noqa: E402
from revision_ops import audit as audit_ops  # noqa: E402
from revision_ops import plan as plan_ops  # noqa: E402
from revision_ops import apply as apply_ops  # noqa: E402
from revision_ops import edit as edit_ops  # noqa: E402
from revision_ops import revert as revert_ops  # noqa: E402
from revision_ops import snapshot as snapshot_ops  # noqa: E402
from revision_ops.common import PlanError, client  # noqa: E402


def _parse_map(values: list[str] | None) -> dict[str, int]:
    out = {}
    for value in values or []:
        if "=" not in value:
            raise PlanError("--map wants REV_ID=NOTE_ID")
        rev, nid = value.split("=", 1)
        out[rev.strip()] = int(nid)
    return out


def cmd_attach(args) -> int:
    ac = client(args.url)
    try:
        result = attach_ops.attach(ac, args.deck, reconstruct=args.reconstruct,
                                   maps=_parse_map(args.map))
    except PlanError as e:
        print(f"revision.py: {e}", file=sys.stderr)
        return 2
    if result["status"] == "ambiguous":
        print("revision.py: attach is ambiguous; nothing was written.", file=sys.stderr)
        for item in result["ambiguous"]:
            print(f"  dossier: {', '.join(item['cards'])}", file=sys.stderr)
            print(f"  notes:   {', '.join(n['front'] for n in item['notes'])}",
                  file=sys.stderr)
        print("  resolve with --map <rev_id>=<note_id>", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"attached   {result['matched']} note(s) to dossier {result['key']}")
        if result["unmatched_rows"] or result["unmatched_notes"]:
            print(f"           {result['unmatched_rows']} dossier card(s) and "
                  f"{result['unmatched_notes']} live note(s) remain unmatched")
        if result["field_drift"]:
            print(f"           {len(result['field_drift'])} note(s) differ from the "
                  "dossier (manual Anki edits preserved)")
    return 0


def cmd_audit(args) -> int:
    ac = client(args.url)
    report = audit_ops.audit(ac, args.deck, as_json=args.json)
    if args.json:
        print(json.dumps(report, indent=2))
    return 0


def cmd_plan(args) -> int:
    ac = client(args.url)
    try:
        result = plan_ops.plan(ac, args)
    except PlanError as e:
        print(f"revision.py: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"plan       {result['plan']}")
        print(f"           {result['counts']['updated']} update(s), "
              f"{result['counts']['added']} new card(s), "
              f"{result['counts']['destructive']} removal candidate(s), "
              f"{result['conflicts']} conflict(s)")
        if result["groups"]:
            print("           destructive groups: " + ", ".join(result["groups"]) +
                  " — choose delete / suspend / keep before applying")
    return 0


def cmd_apply(args) -> int:
    ac = client(args.url)
    try:
        result = apply_ops.apply(
            ac, args.plan, choice=args.choice,
            browser_closed=args.browser_closed,
            overwrite_conflicts=args.overwrite_conflicts,
            allow_card_shape_change=args.allow_card_shape_change,
            allow_low_res=args.allow_low_res, sync=args.sync)
    except PlanError as e:
        print(f"revision.py: {e}", file=sys.stderr)
        return 2
    print(f"applied    {result['updated']} update(s), {result['added']} new card(s), "
          f"{result['suspended']} suspended, {result['deleted']} deleted, "
          f"{result['kept']} kept; {result['conflicts']} conflict(s)")
    print(f"           verification {'ok' if result['verified'] else 'FAILED'} "
          f"-> {result['dir']}")
    print(f"           snapshot {result['snapshot_id']} (revert with --last)")
    if args.json:
        print(json.dumps(result, indent=2))
    return 0 if result["verified"] else 1


def cmd_revert(args) -> int:
    if not args.yes:
        if not sys.stdin.isatty():
            print("revision.py: revert is destructive; pass --yes after asking "
                  "the user.", file=sys.stderr)
            return 2
        answer = input("Revert the last applied revision? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("cancelled")
            return 1
    ac = client(args.url)
    try:
        result = revert_ops.revert(
            ac, args.deck,
            snapshot_id=("last" if args.last else args.snapshot), force=args.force,
            browser_closed=args.browser_closed, sync=args.sync,
            dry_run=args.dry_run)
    except (PlanError, FileNotFoundError) as e:
        print(f"revision.py: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    elif result.get("dry_run"):
        print("revert dry-run: " + ", ".join(
            f"{k}={v}" for k, v in result["counts"].items()))
    else:
        print(f"reverted   {result['restored']} restored, {result['removed']} removed, "
              f"{result['unsuspended']} unsuspended; {result['conflicts']} conflict(s)")
        print(f"           verification {'ok' if result['verified'] else 'FAILED'} "
              f"-> {result['dir']}")
        print(f"           pre-revert snapshot {result['pre_revert_snapshot']}")
    return 0 if result.get("verified", True) else 1


def _mb(value: int) -> str:
    return f"{value / (1024 * 1024):.1f} MB"


def cmd_snapshots(args) -> int:
    context = dc.load(args.deck)
    if not context:
        print("revision.py: no dossier for this deck", file=sys.stderr)
        return 2
    if args.delete and args.prune:
        print("revision.py: choose --delete or --prune, not both", file=sys.stderr)
        return 2
    if args.delete:
        if not args.yes:
            print("revision.py: deleting a snapshot needs --yes", file=sys.stderr)
            return 2
        result = snapshot_ops.delete(context, args.delete, force=args.force)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"deleted {result['snapshot_id']} ({_mb(result['bytes'])} freed)")
        if result.get("warning"):
            print(f"revision.py: warning: {result['warning']}", file=sys.stderr)
        return 0
    if args.prune:
        if not args.yes:
            print("revision.py: pruning snapshots needs --yes", file=sys.stderr)
            return 2
        if args.keep is None:
            print("revision.py: --prune needs --keep N", file=sys.stderr)
            return 2
        result = snapshot_ops.prune(context, args.keep, force=args.force)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"pruned {len(result['deleted'])} snapshot(s), kept "
                  f"{len(result['kept'])}, freed {_mb(result['bytes'])}")
        if result.get("warning"):
            print(f"revision.py: warning: {result['warning']}", file=sys.stderr)
        return 0
    if args.sizes:
        report = snapshot_ops.sizes(context, warn_mb=args.warn_mb,
                                    warn_count=args.warn_count)
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"deck {report['deck_key']}  {report['path']}  "
                  f"{_mb(report['total_bytes'])}")
            for name in ("snapshots", "previews", "revisions", "resources"):
                print(f"  {name:<10} {_mb(report['dirs'][name])}")
            for row in report["snapshots"]:
                print(f"{row['snapshot_id']}  {row['created_at']}  "
                      f"{row['reason']}  ({row['note_count']} notes, "
                      f"{row['card_count']} cards, {_mb(row['bytes'])})")
        if report["warning"]:
            print(f"revision.py: warning: {report['warning']}", file=sys.stderr)
        return 0
    rows = snapshot_ops.list_snapshots(context)
    print(json.dumps(rows, indent=2) if args.json else
          "\n".join(f"{r['snapshot_id']}  {r['created_at']}  {r['reason']}  "
                    f"({r['note_count']} notes, {r['card_count']} cards)"
                    for r in rows) or "no snapshots")
    return 0


def cmd_update(args) -> int:
    ac = client(args.url)
    try:
        result = edit_ops.update(ac, args.deck, args.file,
                                 browser_closed=args.browser_closed,
                                 dry_run=args.dry_run)
    except PlanError as e:
        print(f"revision.py: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    elif result.get("dry_run"):
        print(f"update dry-run: {result['notes']} note(s), "
              f"{result['fields']} field edit(s), {result['tags']} tag edit(s)")
    else:
        print(f"updated    {result['notes']} note(s); verification "
              f"{'ok' if result['verified'] else 'FAILED'} -> {result['dir']}")
        print(f"           snapshot {result['snapshot_id']}")
    return 0 if result.get("verified", True) else 1


def cmd_tags(args) -> int:
    ac = client(args.url)
    try:
        result = edit_ops.lowercase_tags(ac, args.deck, dry_run=args.dry_run)
    except PlanError as e:
        print(f"revision.py: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    elif result.get("dry_run"):
        print(f"tag dry-run: {result['notes']} note(s)")
    elif not result.get("notes"):
        print("tags       already lowercase")
    else:
        print(f"tags       {result['notes']} note(s) lowercased; verification "
              f"{'ok' if result['verified'] else 'FAILED'} -> {result['dir']}")
        print(f"           snapshot {result['snapshot_id']}")
    return 0 if result.get("verified", True) else 1


def cmd_context(args) -> int:
    if args.context_cmd == "pack":
        result = dc.pack(args.work, {"deck_name": args.deck,
                                     "deck_id": args.deck_id,
                                     "profile": args.profile,
                                     "notetypes": args.notetypes})
        print(json.dumps(result, indent=2) if args.json else
              f"dossier {result['key']}: {result['cards']} card(s) -> {result['path']}")
        return 0
    if args.context_cmd == "export":
        path = dc.export(args.deck, args.out,
                         include_snapshots=args.include_snapshots)
        print(path)
        return 0
    if args.context_cmd == "import":
        result = dc.import_archive(args.archive, dry_run=args.dry_run)
        if args.attach and not args.dry_run:
            result["attached"] = attach_ops.attach_key(result["key"], url=args.url)
        if args.json:
            print(json.dumps(result, indent=2))
        elif result.get("dry_run"):
            print(f"dossier {result['key']}: {result['files']} file(s) (dry run)")
        else:
            print(f"dossier {result['key']} -> {result['path']}")
        return 0
    if args.context_cmd == "validate":
        result = dc.validate(deck_key_or_selector=args.deck)
        print(json.dumps(result, indent=2) if args.json else validator.report(result))
        return 1 if result["errors"] else 0
    if args.context_cmd == "resources":
        rows = dc.list_resources(args.deck)
        print(json.dumps(rows, indent=2) if args.json else
              "\n".join(f"{r['resource_id']}  {r['kind']}/{r['role']}  "
                        f"{r['name']}  {r['path']}" for r in rows) or "no resources")
        return 0
    if args.context_cmd == "add-resource":
        row = dc.add_resource(args.deck, args.file, kind=args.kind,
                              role=args.role, name=args.name)
        print(json.dumps(row, indent=2) if args.json else
              f"added {row['resource_id']} -> {row['path']}")
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="revision.py")
    ap.add_argument("--url", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("attach")
    a.add_argument("--deck", required=True)
    a.add_argument("--reconstruct", action="store_true")
    a.add_argument("--map", action="append", default=[], metavar="REV_ID=NOTE_ID")
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=cmd_attach)

    au = sub.add_parser("audit")
    au.add_argument("--deck", required=True)
    au.add_argument("--json", action="store_true")
    au.set_defaults(func=cmd_audit)

    p = sub.add_parser("plan")
    p.add_argument("--deck", required=True)
    p.add_argument("--intent", required=True)
    p.add_argument("--topic", action="append", default=[])
    p.add_argument("--front", default=None)
    p.add_argument("--tag", action="append", default=[])
    p.add_argument("--layer", action="append", default=[])
    p.add_argument("--stratum", action="append", default=[])
    p.add_argument("--score", type=int, choices=range(1, 6))
    p.add_argument("--leech", action="store_true")
    p.add_argument("--allow-anchors", action="store_true")
    p.add_argument("--update-front", action="append", default=[], metavar="OLD=NEW")
    p.add_argument("--update-back", action="append", default=[], metavar="OLD=NEW")
    p.add_argument("--merge-match", default=None)
    p.add_argument("--into", default=None)
    p.add_argument("--split-match", default=None)
    p.add_argument("--split-front", action="append", default=[])
    p.add_argument("--split-back", action="append", default=[])
    p.add_argument("--attach-media", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_plan)

    ap_ = sub.add_parser("apply")
    ap_.add_argument("--plan", required=True)
    ap_.add_argument("--choice", action="append", default=[],
                     metavar="GROUP=delete|suspend|keep")
    ap_.add_argument("--browser-closed", action="store_true")
    ap_.add_argument("--overwrite-conflicts", action="store_true")
    ap_.add_argument("--allow-card-shape-change", action="store_true")
    ap_.add_argument("--allow-low-res", action="store_true")
    ap_.add_argument("--sync", action="store_true")
    ap_.add_argument("--json", action="store_true")
    ap_.set_defaults(func=cmd_apply)

    rv = sub.add_parser("revert")
    rv.add_argument("--deck", required=True)
    rv.add_argument("--snapshot", default="last")
    rv.add_argument("--last", action="store_true",
                    help="revert the latest applied revision")
    rv.add_argument("--yes", action="store_true")
    rv.add_argument("--force", action="store_true")
    rv.add_argument("--browser-closed", action="store_true")
    rv.add_argument("--sync", action="store_true")
    rv.add_argument("--dry-run", action="store_true")
    rv.add_argument("--json", action="store_true")
    rv.set_defaults(func=cmd_revert)

    sn = sub.add_parser("snapshots")
    sn.add_argument("--deck", required=True)
    sn.add_argument("--sizes", action="store_true")
    sn.add_argument("--delete", metavar="ID")
    sn.add_argument("--prune", action="store_true")
    sn.add_argument("--keep", type=int)
    sn.add_argument("--yes", action="store_true")
    sn.add_argument("--force", action="store_true")
    sn.add_argument("--warn-mb", type=int,
                    default=snapshot_ops.DEFAULT_WARN_BYTES // (1024 * 1024))
    sn.add_argument("--warn-count", type=int,
                    default=snapshot_ops.DEFAULT_WARN_COUNT)
    sn.add_argument("--json", action="store_true")
    sn.set_defaults(func=cmd_snapshots)

    up = sub.add_parser("update")
    up.add_argument("--deck", required=True)
    up.add_argument("--file", required=True)
    up.add_argument("--browser-closed", action="store_true")
    up.add_argument("--dry-run", action="store_true")
    up.add_argument("--json", action="store_true")
    up.set_defaults(func=cmd_update)

    tg = sub.add_parser("tags")
    tg.add_argument("--deck", required=True)
    tg.add_argument("--lowercase", action="store_true", required=True)
    tg.add_argument("--dry-run", action="store_true")
    tg.add_argument("--json", action="store_true")
    tg.set_defaults(func=cmd_tags)

    c = sub.add_parser("context")
    cs = c.add_subparsers(dest="context_cmd", required=True)
    cp = cs.add_parser("pack")
    cp.add_argument("--work", required=True)
    cp.add_argument("--deck", required=True)
    cp.add_argument("--deck-id", default="")
    cp.add_argument("--profile", default="")
    cp.add_argument("--notetypes", nargs="*", default=None)
    cp.add_argument("--json", action="store_true")
    ce = cs.add_parser("export")
    ce.add_argument("--deck", required=True)
    ce.add_argument("--out", required=True)
    ce.add_argument("--include-snapshots", action="store_true")
    ci = cs.add_parser("import")
    ci.add_argument("archive")
    ci.add_argument("--attach", action="store_true")
    ci.add_argument("--dry-run", action="store_true")
    ci.add_argument("--json", action="store_true")
    cv = cs.add_parser("validate")
    cv.add_argument("--deck", required=True)
    cv.add_argument("--json", action="store_true")
    cr = cs.add_parser("resources")
    cr.add_argument("--deck", required=True)
    cr.add_argument("--json", action="store_true")
    ca = cs.add_parser("add-resource")
    ca.add_argument("--deck", required=True)
    ca.add_argument("--file", required=True)
    ca.add_argument("--kind", default="other")
    ca.add_argument("--role", default="reference")
    ca.add_argument("--name", default="")
    ca.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_context)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (AnkiConnectError, DossierError) as e:
        print(str(e), file=sys.stderr)
        return 2
    except (PlanError, ValueError, FileNotFoundError, OSError) as e:
        print(f"revision.py: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
