#!/usr/bin/env python3
"""Verify an installed Endurance Training OS without polluting its memory."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def run(parts: list[str], cwd: Path, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        parts,
        cwd=cwd,
        input=stdin,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=90,
    )


def check(name: str, ok: bool, detail: str = "") -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail}


def verify_files(target: Path) -> list[dict[str, Any]]:
    required = [
        "AGENTS.md",
        "START_HERE.md",
        ".training_os/AGENT_GUIDE.md",
        ".training_os/config.json",
        ".training_os/bin/agent_memory.py",
        ".training_os/bin/training_os.py",
        ".training_os/hooks/agent-memory.cmd",
        ".training_os/hooks/agent-memory.sh",
        "coach/ATHLETE_PROFILE.md",
        "coach/TRAINING_LOG.md",
        "coach/DATA_AUDIT.md",
        "coach/DECISIONS.md",
        "coach/LIBRARY_INDEX.md",
    ]
    missing = [item for item in required if not (target / item).exists()]
    agents_text = (target / "AGENTS.md").read_text(encoding="utf-8", errors="replace") if (target / "AGENTS.md").exists() else ""
    content_ok = ".training_os/AGENT_GUIDE.md" in agents_text and "Local Endurance Training OS" in agents_text
    return [
        check("required_files", not missing, "missing: " + ", ".join(missing) if missing else "complete"),
        check("agent_entry_content", content_ok, "entry instructs the agent to read AGENT_GUIDE.md"),
    ]


def verify_config(target: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = target / ".training_os" / "config.json"
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [check("config_json", False, str(exc))], {}
    checks = [
        check("config_json", isinstance(config, dict), "object" if isinstance(config, dict) else "not an object"),
        check("config_timezone", bool(config.get("timezone")), str(config.get("timezone"))),
        check("config_agents", bool(config.get("agent")), str(config.get("agent"))),
    ]
    return checks, config if isinstance(config, dict) else {}


def verify_codex(target: Path) -> list[dict[str, Any]]:
    path = target / ".codex" / "config.toml"
    if not path.exists():
        return [check("codex_config", False, "missing")]
    text = path.read_text(encoding="utf-8", errors="replace")
    missing: list[str] = []
    for event in ("SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"):
        match = re.search(
            rf"(?ms)^{event}\s*=\s*(.*?)(?=^[A-Za-z_][A-Za-z0-9_]*\s*=|\Z)",
            text,
        )
        value = match.group(1) if match else ""
        if not match or "agent_memory.py" not in value:
            missing.append(event)
    return [
        check(
            "codex_hook_commands",
            not missing,
            "all events point to agent_memory.py" if not missing else "fix or merge: " + ", ".join(missing),
        )
    ]


def verify_claude(target: Path) -> list[dict[str, Any]]:
    path = target / ".claude" / "settings.json"
    if not path.exists():
        return [check("claude_settings", False, "missing")]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [check("claude_settings", False, str(exc))]
    hooks = payload.get("hooks") if isinstance(payload, dict) else {}
    ok = isinstance(hooks, dict) and all(
        event in hooks for event in ("SessionStart", "UserPromptSubmit", "Stop", "SessionEnd")
    )
    return [check("claude_hooks", ok, "hook events present" if ok else "hook events incomplete")]


def verify_generic(target: Path) -> list[dict[str, Any]]:
    guide = target / ".training_os" / "AGENT_GUIDE.md"
    text = guide.read_text(encoding="utf-8", errors="replace") if guide.exists() else ""
    ok = "agent_memory.py context" in text and "capture" in text
    return [check("generic_protocol", ok, "manual context/capture documented")]


def isolated_memory_test(target: Path, python: str) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="training-os-verify-") as temp:
        sandbox = Path(temp)
        shutil.copytree(target / ".training_os", sandbox / ".training_os")
        coach = sandbox / "coach"
        coach.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target / "coach" / "ATHLETE_PROFILE.md", coach / "ATHLETE_PROFILE.md")
        state = sandbox / ".training_os"
        for local in ("data", "archive", "backups", "logs"):
            shutil.rmtree(state / local, ignore_errors=True)
        (state / "data").mkdir(parents=True, exist_ok=True)
        (state / "archive").mkdir(parents=True, exist_ok=True)
        (state / "backups").mkdir(parents=True, exist_ok=True)
        (state / "logs").mkdir(parents=True, exist_ok=True)

        script = state / "bin" / "agent_memory.py"
        init = run([python, str(script), "init"], sandbox)
        checks.append(check("memory_init", init.returncode == 0, (init.stderr or init.stdout).strip()[:500]))

        transcript = sandbox / "session.jsonl"
        events = [
            {
                "type": "session_meta",
                "timestamp": "2026-01-01T08:00:00Z",
                "payload": {"id": "verify-session", "cwd": str(sandbox), "originator": "verify"},
            },
            {
                "type": "event_msg",
                "timestamp": "2026-01-01T08:00:01Z",
                "payload": {
                    "type": "user_message",
                    "message": "我的长期目标是安全完成一次十公里比赛，并且不允许未经我确认上传训练数据。",
                },
            },
            {
                "type": "event_msg",
                "timestamp": "2026-01-01T08:00:02Z",
                "payload": {"type": "agent_message", "message": "已记录目标和数据边界。"},
            },
        ]
        transcript.write_text(
            "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
            encoding="utf-8",
        )
        ingest = run([python, str(script), "ingest", "--transcript", str(transcript)], sandbox)
        checks.append(check("transcript_ingest", ingest.returncode == 0, (ingest.stderr or ingest.stdout).strip()[:500]))

        context = run(
            [python, str(script), "context", "--task", "十公里目标", "--budget-kind", "prompt"],
            sandbox,
        )
        checks.append(
            check(
                "memory_context",
                context.returncode == 0 and "核心长期记忆" in context.stdout,
                context.stdout[:700] if context.returncode else (context.stderr or context.stdout)[:700],
            )
        )

        claude_transcript = sandbox / "claude-session.jsonl"
        claude_events = [
            {
                "type": "user",
                "sessionId": "claude-verify",
                "cwd": str(sandbox),
                "timestamp": "2026-01-02T08:00:00Z",
                "message": {"role": "user", "content": "I prefer morning runs and I do not want data uploaded."},
            },
            {
                "type": "assistant",
                "sessionId": "claude-verify",
                "cwd": str(sandbox),
                "timestamp": "2026-01-02T08:00:01Z",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "Noted."}]},
            },
        ]
        claude_transcript.write_text(
            "\n".join(json.dumps(event, ensure_ascii=False) for event in claude_events) + "\n",
            encoding="utf-8",
        )
        claude_ingest = run(
            [python, str(script), "ingest", "--transcript", str(claude_transcript)],
            sandbox,
        )
        checks.append(
            check(
                "claude_transcript_format",
                claude_ingest.returncode == 0 and '"turns": 1' in claude_ingest.stdout,
                (claude_ingest.stderr or claude_ingest.stdout)[:500],
            )
        )

        hook_payload = json.dumps(
            {
                "hook_event_name": "SessionStart",
                "session_id": "verify-session",
                "transcript_path": str(transcript),
            },
            ensure_ascii=False,
        )
        hook = run([python, str(script), "hook"], sandbox, hook_payload)
        hook_ok = False
        if hook.returncode == 0:
            try:
                parsed = json.loads(hook.stdout)
                hook_ok = bool(parsed.get("hookSpecificOutput", {}).get("additionalContext"))
            except json.JSONDecodeError:
                hook_ok = False
        checks.append(check("hook_contract", hook_ok, hook.stdout[:500] or hook.stderr[:500]))

        test_prompt = run(
            [
                python,
                str(script),
                "capture",
                "--session",
                "verify",
                "--prompt",
                "memory hook test",
            ],
            sandbox,
        )
        search = run([python, str(script), "search", "--query", "memory hook test"], sandbox)
        checks.append(
            check(
                "test_prompt_filter",
                test_prompt.returncode == 0 and "未找到匹配的结构化记忆" in search.stdout,
                search.stdout[:300],
            )
        )

        secret = "sk-" + "abcdefghijklmnopqrstuvwxyz123456"
        secret_capture = run(
            [
                python,
                str(script),
                "capture",
                "--session",
                "verify-secret",
                "--prompt",
                f"我的目标是不把 token {secret} 写进记忆。",
            ],
            sandbox,
        )
        secret_context = run([python, str(script), "context", "--task", "token", "--budget-kind", "search"], sandbox)
        checks.append(
            check(
                "secret_redaction",
                secret_capture.returncode == 0
                and secret not in (secret_capture.stdout + secret_context.stdout),
                secret_context.stdout[:500],
            )
        )
    return checks


def verify_garmin_plan(target: Path, python: str) -> list[dict[str, Any]]:
    result = run(
        [python, str(target / ".training_os" / "bin" / "training_os.py"), "garmin-plan", "--today", "2026-01-10"],
        target,
    )
    ok = False
    detail = (result.stderr or result.stdout)[:600]
    if result.returncode == 0:
        try:
            plan = json.loads(result.stdout)
            ok = bool(plan.get("calls")) and plan.get("read_only") is True
        except json.JSONDecodeError:
            ok = False
    return [check("garmin_query_plan", ok, detail)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify an installed training workspace")
    parser.add_argument("--target", required=True)
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args(argv)
    target = Path(args.target).expanduser().resolve()
    if not target.exists():
        raise SystemExit(f"Target does not exist: {target}")
    python = args.python
    checks: list[dict[str, Any]] = []
    checks.extend(verify_files(target))
    config_checks, config = verify_config(target)
    checks.extend(config_checks)
    agents = config.get("agent") if isinstance(config.get("agent"), list) else []
    if "codex" in agents:
        checks.extend(verify_codex(target))
    if "claude" in agents:
        checks.extend(verify_claude(target))
    if not any(item in agents for item in ("codex", "claude")):
        checks.extend(verify_generic(target))
    checks.extend(isolated_memory_test(target, python))
    checks.extend(verify_garmin_plan(target, python))
    ok = all(item["ok"] for item in checks)
    print(
        json.dumps(
            {
                "target": str(target),
                "ok": ok,
                "passed": sum(1 for item in checks if item["ok"]),
                "failed": sum(1 for item in checks if not item["ok"]),
                "checks": checks,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
