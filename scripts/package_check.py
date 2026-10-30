#!/usr/bin/env python3
"""Check a distributable skill for private data and common release mistakes."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SECRET_PATTERNS = [
    (re.compile(r"\bsk-[A-Za-z0-9_-]{18,}\b"), "possible API key"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "possible GitHub token"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "possible AWS access key"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "private key"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}"), "bearer token"),
    (re.compile(r"(?i)\b(?:api[_-]?key|password|secret|token)\s*[:=]\s*['\"][^'\"]{12,}['\"]"), "hard-coded credential"),
]

PRIVATE_PATH_PATTERNS = [
    (re.compile(r"[A-Za-z]:\\Users\\(?!<)[^\\\s]+", re.IGNORECASE), "absolute Windows user path"),
    (re.compile(r"/home/(?!<)[^/\s]+"), "absolute Linux home path"),
    (re.compile(r"/Users/(?!<)[^/\s]+"), "absolute macOS home path"),
]

EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
ALLOWED_EMAIL_DOMAINS = {"example.com", "example.org", "example.net"}

FORBIDDEN_SUFFIXES = {
    ".sqlite3",
    ".sqlite",
    ".db",
    ".jsonl",
    ".zip",
    ".7z",
    ".tar",
    ".gz",
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",
    ".png",
    ".jpg",
    ".jpeg",
    ".mp4",
    ".mov",
    ".wav",
    ".mp3",
}


def scan_text(path: Path, text: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for pattern, label in SECRET_PATTERNS:
            if pattern.search(line):
                issues.append({"path": str(path), "line": line_number, "kind": label})
        for pattern, label in PRIVATE_PATH_PATTERNS:
            if pattern.search(line):
                issues.append({"path": str(path), "line": line_number, "kind": label})
        for match in EMAIL_PATTERN.finditer(line):
            domain = match.group(1).lower()
            if domain in ALLOWED_EMAIL_DOMAINS or domain.endswith(".md"):
                continue
            if domain not in ALLOWED_EMAIL_DOMAINS:
                issues.append({"path": str(path), "line": line_number, "kind": "possible personal email/account"})
    return issues


def parse_frontmatter(skill_file: Path) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    if not skill_file.exists():
        return {}, ["SKILL.md missing"]
    text = skill_file.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, ["SKILL.md frontmatter missing"]
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, ["SKILL.md frontmatter is not closed"]
    fields: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip().strip('"').strip("'")
    if not fields.get("name"):
        errors.append("frontmatter name missing")
    if not fields.get("description"):
        errors.append("frontmatter description missing")
    if fields.get("name") and not re.fullmatch(r"[a-z0-9-]{1,63}", fields["name"]):
        errors.append("frontmatter name must use lowercase letters, digits, and hyphens")
    return fields, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check a skill package for release blockers")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--max-bytes", type=int, default=1_500_000)
    args = parser.parse_args(argv)
    root = Path(args.path).expanduser().resolve()
    issues: list[dict[str, Any]] = []
    large: list[dict[str, Any]] = []
    py_files: list[str] = []
    json_files: list[str] = []
    if not root.exists():
        raise SystemExit(f"Path does not exist: {root}")
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in {"__pycache__", ".git"} for part in relative.parts):
            continue
        if relative.as_posix() == "scripts/package_check.py":
            continue
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            issues.append({"path": str(relative), "line": 0, "kind": "forbidden binary/data file"})
        if path.stat().st_size > args.max_bytes:
            large.append({"path": str(relative), "bytes": path.stat().st_size})
        if path.suffix.lower() == ".py":
            py_files.append(str(path))
        if path.suffix.lower() == ".json":
            json_files.append(str(path))
        if path.suffix.lower() in {".md", ".py", ".json", ".toml", ".yaml", ".yml", ".sh", ".ps1", ".cmd", ".mdc", ".txt"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            issues.extend(scan_text(relative, text))
    fields, skill_errors = parse_frontmatter(root / "SKILL.md")
    for error in skill_errors:
        issues.append({"path": "SKILL.md", "line": 0, "kind": error})
    for file_name in json_files:
        try:
            json.loads(Path(file_name).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            issues.append({"path": str(Path(file_name).relative_to(root)), "line": exc.lineno, "kind": "invalid JSON"})
    compile_errors: list[str] = []
    for file_name in py_files:
        try:
            compile(Path(file_name).read_text(encoding="utf-8"), file_name, "exec")
        except SyntaxError as exc:
            compile_errors.append(f"{file_name}:{exc.lineno}: {exc.msg}")
    for error in compile_errors:
        issues.append({"path": "python", "line": 0, "kind": error})
    result = {
        "root": str(root),
        "ok": not issues and not large,
        "skill": fields,
        "files": len(
            [
                path
                for path in root.rglob("*")
                if path.is_file() and "__pycache__" not in path.relative_to(root).parts
            ]
        ),
        "issues": issues,
        "large_files": large,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
