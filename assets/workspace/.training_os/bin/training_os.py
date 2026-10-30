#!/usr/bin/env python3
"""Operational CLI for a portable endurance training workspace."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


SCRIPT_PATH = Path(__file__).resolve()
STATE_ROOT = SCRIPT_PATH.parents[1]
PROJECT_ROOT = SCRIPT_PATH.parents[2]
CONFIG_PATH = STATE_ROOT / "config.json"
COACH_DIR = PROJECT_ROOT / "coach"
DATA_DIR = PROJECT_ROOT / "data" / "garmin"
RAW_DIR = DATA_DIR / "raw"
STATE_PATH = DATA_DIR / "state.json"


def load_config() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        try:
            payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except (OSError, json.JSONDecodeError):
            pass
    return {}


CONFIG = load_config()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def local_now() -> datetime:
    zone_name = str(CONFIG.get("timezone") or "UTC")
    if ZoneInfo:
        try:
            return datetime.now(ZoneInfo(zone_name))
        except Exception:
            pass
    return datetime.now().astimezone()


def iso_now() -> str:
    return local_now().isoformat(timespec="seconds")


def local_today() -> date:
    return local_now().date()


def parse_date(value: str | None, fallback: date | None = None) -> date:
    if not value:
        if fallback is not None:
            return fallback
        raise ValueError("Date is required")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid date: {value}; expected YYYY-MM-DD") from exc


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".tmp-{os.getpid()}")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(temp, path)


def append_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def command_plan(today: date, last_checked: date | None) -> dict[str, Any]:
    garmin = CONFIG.get("garmin") if isinstance(CONFIG.get("garmin"), dict) else {}
    overlap = int(garmin.get("overlap_days", 3))
    initial = int(garmin.get("initial_days", 21))
    if last_checked and last_checked > today:
        last_checked = today
    start = today - timedelta(days=initial)
    if last_checked:
        start = min(start, last_checked - timedelta(days=overlap))
    end = today
    server = str(garmin.get("mcp_server", "garmin"))
    return {
        "generated_at": iso_now(),
        "mcp_server": server,
        "read_only": True,
        "today": end.isoformat(),
        "last_checked": last_checked.isoformat() if last_checked else None,
        "window": {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "overlap_days": overlap,
            "initial_days": initial,
        },
        "calls": [
            {
                "tool": "get_activities_by_date",
                "arguments": {
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "page": 0,
                    "page_size": 100,
                },
                "purpose": "List new or revised activities; walk next_page until has_more is false.",
            },
            {
                "tool": "get_activity",
                "arguments": {"activity_id": "<each new or revised activity id>"},
                "purpose": "Read activity details without inferring missing fields.",
            },
            {
                "tool": "get_stats",
                "arguments": {"date": end.isoformat()},
                "purpose": "Read today's partial-day daily summary.",
            },
            {
                "tool": "get_stats",
                "arguments": {"date": (end - timedelta(days=1)).isoformat()},
                "purpose": "Read the last complete daily summary.",
            },
            {
                "tool": "get_sleep_summary_range",
                "arguments": {
                    "start_date": (end - timedelta(days=6)).isoformat(),
                    "end_date": end.isoformat(),
                },
                "purpose": "Read seven nights of sleep trends.",
            },
            {
                "tool": "get_hrv_trend",
                "arguments": {
                    "start_date": (end - timedelta(days=20)).isoformat(),
                    "end_date": end.isoformat(),
                },
                "purpose": "Read HRV trend; never act on one night in isolation.",
            },
            {
                "tool": "get_training_status",
                "arguments": {"date": end.isoformat()},
                "purpose": "Read training load/status when the device supports it.",
            },
            {
                "tool": "get_recovery_time_remaining",
                "arguments": {"date": end.isoformat()},
                "purpose": "Read recovery clock when available; optional.",
            },
        ],
        "after_reading": [
            "Save each complete JSON response with garmin-record.",
            "Compare activity IDs and revise coach/DATA_AUDIT.md.",
            "Mark missing, partial, or failed data explicitly.",
            "Never claim a successful sync without actual tool output.",
        ],
    }


def cmd_garmin_plan(args: argparse.Namespace) -> int:
    state = read_json(STATE_PATH)
    last_checked = None
    if args.last_checked:
        last_checked = parse_date(args.last_checked)
    elif state.get("last_checked_date"):
        last_checked = parse_date(str(state["last_checked_date"]))
    today = parse_date(args.today, local_today())
    print(json.dumps(command_plan(today, last_checked), ensure_ascii=False, indent=2))
    return 0


def validate_jsonish(payload: Any) -> None:
    if not isinstance(payload, (dict, list)):
        raise ValueError("Garmin response must be a JSON object or array")


def cmd_garmin_record(args: argparse.Namespace) -> int:
    if args.input == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(args.input).read_text(encoding="utf-8")
    payload = json.loads(raw)
    validate_jsonish(payload)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    safe_tool = re.sub(r"[^A-Za-z0-9_.-]+", "-", args.tool).strip("-") or "response"
    snapshot = RAW_DIR / f"{stamp}-{safe_tool}.json"
    snapshot.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    meta = {
        "recorded_at": iso_now(),
        "tool": args.tool,
        "window": args.window or "",
        "status": args.status,
        "latest_activity_date": args.latest_activity_date or "",
        "latest_data_date": args.latest_data_date or "",
        "notes": args.notes or "",
        "source_file": str(snapshot.relative_to(PROJECT_ROOT)),
        "bytes": snapshot.stat().st_size,
    }
    write_json(snapshot.with_suffix(".meta.json"), meta)

    state = read_json(STATE_PATH)
    state["last_checked_at"] = meta["recorded_at"]
    state["last_checked_date"] = local_today().isoformat()
    state["last_status"] = args.status
    if args.window:
        state["last_window"] = args.window
    if args.latest_activity_date:
        current = str(state.get("latest_activity_date") or "")
        state["latest_activity_date"] = max(current, args.latest_activity_date)
    if args.latest_data_date:
        current = str(state.get("latest_data_date") or "")
        state["latest_data_date"] = max(current, args.latest_data_date)
    tools = state.get("tools") if isinstance(state.get("tools"), dict) else {}
    tools[args.tool] = {
        "last_status": args.status,
        "last_recorded_at": meta["recorded_at"],
        "last_file": meta["source_file"],
    }
    state["tools"] = tools
    write_json(STATE_PATH, state)

    audit = COACH_DIR / "DATA_AUDIT.md"
    if not audit.exists():
        append_text(audit, "# 数据审计\n\n## 批次记录\n\n")
    append_text(
        audit,
        "- "
        + " | ".join(
            [
                meta["recorded_at"],
                args.tool,
                args.window or "-",
                args.status,
                args.latest_activity_date or "-",
                args.latest_data_date or "-",
                f"`{meta['source_file']}`",
                args.notes or "",
            ]
        ).rstrip()
        + "\n",
    )
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


def _check_python() -> dict[str, Any]:
    ok = sys.version_info >= (3, 10)
    return {
        "name": "python",
        "ok": ok,
        "value": sys.version.split()[0],
        "detail": "Python 3.10+ required; 3.11+ recommended.",
    }


def _check_fts() -> dict[str, Any]:
    try:
        con = sqlite3.connect(":memory:")
        con.execute("CREATE VIRTUAL TABLE ft USING fts5(x)")
        con.close()
        return {"name": "sqlite_fts5", "ok": True, "value": sqlite3.sqlite_version}
    except sqlite3.OperationalError as exc:
        return {"name": "sqlite_fts5", "ok": False, "value": str(exc)}


def _check_write() -> dict[str, Any]:
    try:
        probe = STATE_ROOT / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return {"name": "write_permission", "ok": True, "value": str(STATE_ROOT)}
    except OSError as exc:
        return {"name": "write_permission", "ok": False, "value": str(exc)}


def _check_files() -> dict[str, Any]:
    required = [
        CONFIG_PATH,
        STATE_ROOT / "AGENT_GUIDE.md",
        STATE_ROOT / "bin" / "agent_memory.py",
        COACH_DIR / "ATHLETE_PROFILE.md",
        PROJECT_ROOT / "AGENTS.md",
    ]
    missing = [str(path.relative_to(PROJECT_ROOT)) for path in required if not path.exists()]
    return {"name": "workspace_files", "ok": not missing, "value": missing or "complete"}


def _check_hooks() -> dict[str, Any]:
    indicators: list[str] = []
    agents = CONFIG.get("agent") or []
    if isinstance(agents, str):
        agents = [agents]
    if "codex" in agents:
        path = PROJECT_ROOT / ".codex" / "config.toml"
        if path.exists() and "training-os hooks" in path.read_text(encoding="utf-8", errors="replace"):
            indicators.append("codex")
    if "claude" in agents:
        path = PROJECT_ROOT / ".claude" / "settings.json"
        if path.exists() and "agent_memory.py" in path.read_text(encoding="utf-8", errors="replace"):
            indicators.append("claude")
    return {
        "name": "hooks",
        "ok": bool(indicators),
        "value": indicators or "generic mode (manual context/capture commands)",
        "detail": "Codex hooks may still require approval in /hooks.",
    }


def _check_garmin() -> dict[str, Any]:
    executable = shutil.which("garmin-mcp") or shutil.which("garmin-mcp.exe")
    configured = bool(CONFIG.get("garmin", {}).get("mcp_server"))
    return {
        "name": "garmin_mcp_cli",
        "ok": True,
        "value": executable or ("configured, executable not discovered" if configured else "not configured"),
        "detail": "This check is local only. Actual MCP availability must be verified inside the agent.",
    }


def cmd_doctor(args: argparse.Namespace) -> int:
    checks = [_check_python(), _check_fts(), _check_write(), _check_files(), _check_hooks(), _check_garmin()]
    critical = [item for item in checks if not item["ok"] and item["name"] in {"python", "write_permission", "workspace_files"}]
    result = {
        "project": str(PROJECT_ROOT),
        "generated_at": iso_now(),
        "ok": not critical,
        "checks": checks,
        "notes": [
            "MCP tools cannot be enumerated by this local script.",
            "Approve hooks in the agent client before expecting automatic memory.",
            "Raw Garmin data stays under data/garmin/raw and is local-only.",
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


def profile_status() -> dict[str, Any]:
    path = COACH_DIR / "ATHLETE_PROFILE.md"
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    placeholders = re.findall(r"<[^>\n]{2,80}>", text)
    filled = bool(text.strip()) and len(placeholders) <= 3
    return {
        "path": str(path.relative_to(PROJECT_ROOT)) if path.exists() else None,
        "exists": path.exists(),
        "placeholder_count": len(placeholders),
        "ready_for_planning": filled,
    }


def cmd_status(args: argparse.Namespace) -> int:
    state = read_json(STATE_PATH)
    memory_db = STATE_ROOT / "data" / "memory.sqlite3"
    memory = {"exists": memory_db.exists(), "bytes": memory_db.stat().st_size if memory_db.exists() else 0}
    result = {
        "project": str(PROJECT_ROOT),
        "profile": profile_status(),
        "garmin": state or {"status": "no batches recorded"},
        "memory": memory,
        "next": [
            "Fill coach/ATHLETE_PROFILE.md with confirmed facts.",
            "Run doctor and approve hooks in the agent client.",
            "Verify Garmin MCP with a read-only recent-activities call.",
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _import_memory():
    sys.path.insert(0, str(STATE_ROOT / "bin"))
    import agent_memory  # type: ignore

    return agent_memory


def cmd_backup(args: argparse.Namespace) -> int:
    module = _import_memory()
    print(str(module.MemoryStore().backup()))
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    module = _import_memory()
    target = module.MemoryStore().restore(Path(args.backup), Path(args.target))
    print(str(target))
    return 0


def cmd_onboard(args: argparse.Namespace) -> int:
    path = PROJECT_ROOT / "START_HERE.md"
    if path.exists():
        print(path.read_text(encoding="utf-8"))
    else:
        print("START_HERE.md is missing. Re-run the installer.")
    return 0


def cmd_garmin_check(args: argparse.Namespace) -> int:
    plan = command_plan(parse_date(args.today, local_today()), None)
    executable = shutil.which("garmin-mcp") or shutil.which("garmin-mcp.exe")
    auth = shutil.which("garmin-mcp-auth") or shutil.which("garmin-mcp-auth.exe")
    result = {
        "server": plan["mcp_server"],
        "garmin_mcp": executable,
        "garmin_auth": auth,
        "token_dir": str(Path.home() / ".garminconnect"),
        "next": [
            "If the CLI is missing, install the Garmin MCP implementation selected by the user.",
            "Run the vendor's auth command once; do not paste tokens into this project.",
            "Register the MCP server in the agent, restart, then verify a read-only call.",
        ],
        "example_window": plan["window"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Training workspace operations")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    sub.add_parser("status")
    sub.add_parser("onboard")
    sub.add_parser("backup")
    sub.add_parser("garmin-check")

    plan = sub.add_parser("garmin-plan")
    plan.add_argument("--today")
    plan.add_argument("--last-checked")

    record = sub.add_parser("garmin-record")
    record.add_argument("--input", required=True, help="JSON file, or - for stdin")
    record.add_argument("--tool", required=True)
    record.add_argument("--window", default="")
    record.add_argument("--status", choices=["success", "partial", "failed"], default="success")
    record.add_argument("--latest-activity-date", default="")
    record.add_argument("--latest-data-date", default="")
    record.add_argument("--notes", default="")

    restore = sub.add_parser("restore")
    restore.add_argument("--backup", required=True)
    restore.add_argument("--target", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    commands = {
        "doctor": cmd_doctor,
        "status": cmd_status,
        "onboard": cmd_onboard,
        "backup": cmd_backup,
        "restore": cmd_restore,
        "garmin-plan": cmd_garmin_plan,
        "garmin-record": cmd_garmin_record,
        "garmin-check": cmd_garmin_check,
    }
    return commands[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
