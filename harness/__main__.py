"""Command line entry point: python -m harness <command>."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

from . import db
from .resources import ROOT, Snapshot, evaluate, load_config, top_processes
from .runner import run_guarded

ICON = {"OK": "[OK]  ", "WARN": "[WARN]", "BLOCK": "[STOP]"}


def cmd_check(_args) -> int:
    cfg = load_config()
    s = Snapshot.take()
    v = evaluate(s, cfg)
    print(f"{ICON[v.level]} Resources")
    print(f"  RAM  : {s.available_mb} MB free of {s.total_mb} MB")
    print(f"  CPU  : {s.cpu_percent:.0f}% busy")
    print(f"  Disk : {s.disk_free_mb / 1024:.1f} GB free")
    for reason in v.reasons:
        print(f"  - {reason}")
    if v.level != "OK":
        print("  Biggest memory users (close some to free RAM):")
        for name, mb in top_processes():
            print(f"    {name:<28} {mb:>6} MB")
    return 0 if v.allowed else 2


def _report(res) -> int:
    print(f"\n[harness] {res.outcome.upper()}  exit={res.exit_code}  {res.duration_s}s  "
          f"peak={res.peak_task_mb} MB  min_free={res.min_free_mb} MB")
    for reason in res.verdict.reasons:
        print(f"[harness] {res.verdict.level}: {reason}")
    if res.note:
        print(f"[harness] {res.note}")
    if res.outcome == "blocked":
        print("[harness] Not started: free some memory (run `python -m harness check`) or use --force.")
    return {"passed": 0, "failed": 1}.get(res.outcome, 2)


def cmd_test(args) -> int:
    cmd = [sys.executable, "-m", "pytest", *args.rest]
    return _report(run_guarded(cmd, force=args.force, timeout=args.timeout))


def cmd_run(args) -> int:
    rest = args.rest[1:] if args.rest[:1] == ["--"] else args.rest
    if not rest:
        print("usage: python -m harness run -- <command> [args]")
        return 2
    return _report(run_guarded(rest, force=args.force, timeout=args.timeout))


def _git(*a: str) -> str:
    out = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)
    return out.stdout.strip()


def cmd_status(_args) -> int:
    cfg = load_config()
    print("== InsightFlow development status ==")
    print(f"Branch      : {_git('branch', '--show-current')}")
    print(f"Last commit : {_git('log', '-1', '--format=%h %s (%cr)')}")
    changes = _git("status", "--short")
    print(f"Uncommitted : {len(changes.splitlines()) if changes else 0} file(s)")

    progress = (ROOT / "docs" / "progress.md")
    if progress.exists():
        m = re.search(r"## Current\s*\n(.+)", progress.read_text(encoding="utf-8"))
        if m:
            print(f"Current step: {m.group(1).strip()}")

    runs = db.recent(ROOT / cfg["paths"]["db"], limit=1)
    if runs:
        at, outcome, dur, peak, _free, command = runs[0]
        print(f"Last run    : {outcome} ({dur}s, peak {peak} MB) at {at}: {command[-60:]}")
    print()
    return cmd_check(_args)


def cmd_history(args) -> int:
    rows = db.recent(ROOT / load_config()["paths"]["db"], limit=args.limit)
    if not rows:
        print("No runs recorded yet.")
        return 0
    print(f"{'started':<20} {'outcome':<14} {'sec':>6} {'peakMB':>7} {'minFree':>8}  command")
    for at, outcome, dur, peak, free, command in rows:
        print(f"{at:<20} {outcome:<14} {dur or 0:>6} {peak or 0:>7} {free or 0:>8}  {command[-50:]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m harness", description="InsightFlow local harness")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="show free RAM/CPU/disk and whether tasks may run").set_defaults(fn=cmd_check)
    sub.add_parser("status", help="git + progress + last run + resources").set_defaults(fn=cmd_status)
    h = sub.add_parser("history", help="recent guarded runs")
    h.add_argument("-n", "--limit", type=int, default=10)
    h.set_defaults(fn=cmd_history)

    for name, fn, helptext in [("test", cmd_test, "run pytest under the guard"),
                               ("run", cmd_run, "run any command under the guard")]:
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("--force", action="store_true", help="start even if resources are low")
        sp.add_argument("--timeout", type=float, default=None, help="seconds before the task is stopped")
        sp.add_argument("rest", nargs=argparse.REMAINDER)
        sp.set_defaults(fn=fn)

    args, extra = p.parse_known_args(argv)
    if extra:
        if args.command not in ("test", "run"):
            p.error(f"unrecognized arguments: {' '.join(extra)}")
        args.rest = extra + args.rest  # pass unknown options (e.g. -q, -k) through to the task
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
