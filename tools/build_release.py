#!/usr/bin/env python3
"""Build WorkBuddy and portable single-skill ZIPs from the same source."""
import argparse
import re
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
NAME = "roadside-stall-pro"
INCLUDE_FILES = {"SKILL.md", "README.md", "README.en.md", "LICENSE", "CONTRIBUTING.md", "_icon.png"}
INCLUDE_DIRS = {"agents", "assets", "references", "scripts", "tests"}
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".git", ".github", ".idea", ".vscode"}
SKIP_EXTS = {".pyc", ".pyo", ".tmp", ".log", ".bak"}
WORKBUDDY_KEYS = {"name", "description", "display_name", "display_name_en",
                  "description_zh", "description_en", "examples_zh", "version", "author"}


def split_manifest(data):
    if not data.startswith("---\n"):
        raise ValueError("SKILL.md lacks opening YAML frontmatter")
    head, sep, body = data[4:].partition("\n---\n")
    if not sep or not body.strip():
        raise ValueError("SKILL.md lacks closing frontmatter or body")
    return head, body


def validate_manifest(data, platform):
    head, body = split_manifest(data)
    fields = set()
    for line in head.splitlines():
        if not line.strip() or line.startswith("#") or line.startswith("- "):
            continue
        if line[:1].isspace():
            raise ValueError("Nested YAML frontmatter not permitted")
        m = re.match(r"^([a-z][a-z0-9_-]*):", line)
        if not m or m.group(1) in fields:
            raise ValueError("Invalid or repeated YAML field")
        fields.add(m.group(1))
    expected = WORKBUDDY_KEYS if platform == "workbuddy" else {"name", "description"}
    if platform == "workbuddy" and not expected.issubset(fields):
        raise ValueError("Required WorkBuddy metadata missing")
    if platform == "portable" and fields != expected:
        raise ValueError("Portable format must only use name and description")
    if "name: roadside-stall-pro" not in head:
        raise ValueError("Wrong skill name")
    if not body.strip():
        raise ValueError("Empty Skill instructions")


def get_manifest(platform):
    raw = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    validate_manifest(raw, "portable")
    if platform == "portable":
        return raw
    head, body = split_manifest(raw)
    extra = (ROOT / "tools" / "workbuddy-frontmatter.yaml").read_text(encoding="utf-8").strip()
    result = "---\n" + head + "\n" + extra + "\n---\n" + body
    validate_manifest(result, "workbuddy")
    return result


def build(output, platform):
    manifest = get_manifest(platform)
    output.parent.mkdir(parents=True, exist_ok=True)
    paths = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.is_symlink():
            raise ValueError("Refusing symlink: " + str(path))
        rel = path.relative_to(ROOT)
        if SKIP_DIRS.intersection(rel.parts) or path.suffix in SKIP_EXTS:
            continue
        if path.name in {".DS_Store", ".env"}:
            continue
        if rel.parts[0] not in INCLUDE_DIRS and path.name not in INCLUDE_FILES:
            continue
        paths.append(path)
    with ZipFile(output, "w", ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(paths):
            rel = path.relative_to(ROOT).as_posix()
            if rel == "SKILL.md":
                z.writestr(f"{NAME}/{rel}", manifest)
            else:
                z.write(path, f"{NAME}/{rel}")
    with ZipFile(output) as z:
        files = z.namelist()
        if z.testzip() is not None or sum(x.endswith("/SKILL.md") for x in files) != 1:
            raise ValueError("Invalid ZIP contents")
        if any("__pycache__" in x or x.endswith((".pyc", ".pyo")) for x in files):
            raise ValueError("Python cache found in ZIP")
        validate_manifest(z.read(f"{NAME}/SKILL.md").decode("utf-8"), platform)
    print(f"Built {output}: {len(paths)} files")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", choices=("workbuddy", "portable"), default="portable")
    ap.add_argument("--output")
    args = ap.parse_args()
    target = Path(args.output) if args.output else ROOT / "dist" / args.format / "skill.zip"
    build(target.resolve(), args.format)


if __name__ == "__main__":
    sys.exit(main())
