#!/usr/bin/env python3
"""Install Roadside Stall Pro into local Agent Skills directories.

Dry run unless --apply is provided. Existing skill directories are backed up.
User data under ~/.roadside-stall is never modified.
"""
import argparse
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

TARGETS = {
    "codex": ".agents/skills",
    "claude-code": ".claude/skills",
    "openclaw": ".openclaw/skills",
    "hermes": ".hermes/skills",
}
NAME = "roadside-stall-pro"


def install_one(skill_root, target, apply=False):
    if not (skill_root / "SKILL.md").is_file():
        raise ValueError("SKILL.md is missing from source skill")
    if target.is_symlink():
        raise ValueError(f"{target}: symlink target, refusing to overwrite")
    if target.exists() and not target.is_dir():
        raise ValueError(f"{target}: destination is not a directory")
    if not apply:
        return f"[dry-run] {target} ({'backup and upgrade' if target.exists() else 'install'})"

    target.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{NAME}-stage-", dir=target.parent))
    temp.rmdir()
    previous = None
    try:
        def ignore(directory, entries):
            return {entry for entry in entries if entry in {".git", "__pycache__", ".pytest_cache", ".DS_Store"} or entry.endswith((".pyc", ".pyo"))}
        shutil.copytree(skill_root, temp, ignore=ignore)
        if target.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            previous = target.with_name(f"{NAME}.backup-{stamp}-{os.getpid()}")
            target.rename(previous)
        try:
            temp.rename(target)
        except Exception:
            if previous is not None and previous.exists() and not target.exists():
                previous.rename(target)
            raise
        return f"[installed] {target}" + (f" (backup: {previous})" if previous else "")
    finally:
        if temp.exists():
            shutil.rmtree(temp)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", nargs="+", required=True, choices=sorted(TARGETS))
    ap.add_argument("--apply", action="store_true", help="Install; otherwise preview only")
    ap.add_argument("--home", default=str(Path.home()))
    args = ap.parse_args(argv)
    home = Path(args.home).expanduser().resolve()
    source = Path(__file__).resolve().parent.parent
    try:
        for name in args.targets:
            target = home / TARGETS[name] / NAME
            print(f"{name}: {install_one(source, target, apply=args.apply)}")
    except (ValueError, OSError) as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        return 1
    if not args.apply:
        print("No files changed. Add --apply to install. WorkBuddy uses a ZIP import instead.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
