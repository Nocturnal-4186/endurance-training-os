#!/usr/bin/env python3
"""Conversation-friendly, one-question-at-a-time setup driver.

The agent should call start once, ask the returned question, then call answer
with exactly one user answer. When the final confirmation is accepted, this
script runs install.py and verify.py automatically.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


SKILL_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = SKILL_ROOT / "scripts" / "install.py"
VERIFY_SCRIPT = SKILL_ROOT / "scripts" / "verify.py"
STATE_DIR = Path(tempfile.gettempdir()) / "endurance-training-os-setup"

AGENTS = ["auto", "codex", "claude", "cursor", "gemini", "generic", "all"]
REGIONS = ["cn", "global", "skip"]
HOOK_MODES = ["native", "generic", "none"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".tmp-{os.getpid()}")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(temp, path)
    if os.name != "nt":
        try:
            path.chmod(0o600)
        except OSError:
            pass


def load_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read setup state {path}: {exc}")
    if not isinstance(payload, dict):
        raise SystemExit(f"Invalid setup state: {path}")
    return payload


def save_state(path: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = now_iso()
    atomic_json(path, state)


def detect_agent(target: Path) -> str:
    if (target / ".codex").exists():
        return "codex"
    if (target / ".claude").exists():
        return "claude"
    if (target / ".cursor").exists():
        return "cursor"
    if (target / ".gemini").exists() or (target / "GEMINI.md").exists():
        return "gemini"
    return "auto"


def suggested_timezone() -> str:
    value = os.environ.get("TZ", "").strip()
    if value and "/" in value:
        return value
    if ZoneInfo:
        local = datetime.now().astimezone().tzinfo
        name = getattr(local, "key", "")
        if name and "/" in name:
            return name
    return "Asia/Shanghai"


def order_for(state: dict[str, Any]) -> list[str]:
    order = ["target", "agent", "timezone", "garmin_region"]
    if state.get("answers", {}).get("garmin_region") != "skip":
        order.append("garmin_account_label")
    order.extend(["hooks", "confirm"])
    return order


def next_unanswered(state: dict[str, Any]) -> str | None:
    for step in order_for(state):
        value = state.get("answers", {}).get(step)
        if value is None or value == "" and step not in {"garmin_account_label"}:
            return step
    return None


def question_payload(state: dict[str, Any], state_path: Path) -> dict[str, Any]:
    step = next_unanswered(state)
    if step is None:
        return {"type": "question", "state_path": str(state_path), "step": "confirm", "question": "确认安装吗？"}
    answers = state.get("answers", {})
    target = str(answers.get("target") or Path.cwd())
    questions: dict[str, dict[str, Any]] = {
        "target": {
            "question": "你希望把训练助手安装到哪个文件夹？请输入绝对路径。",
            "hint": "例如当前目录或一个新的空目录。安装器只往这个目录里新增/合并训练系统文件，不会覆盖你的训练档案。",
            "suggested": str(Path.cwd()),
            "sensitive": False,
        },
        "agent": {
            "question": "你主要用哪一个 agent？",
            "hint": "auto 会检测目标目录里已有的配置；不确定就选 auto。",
            "options": AGENTS,
            "suggested": detect_agent(Path(target).expanduser()),
            "sensitive": False,
        },
        "timezone": {
            "question": "你的本地时区是什么？",
            "hint": "请用 IANA 名称，例如 Asia/Shanghai、Europe/London、America/New_York。",
            "suggested": suggested_timezone(),
            "sensitive": False,
        },
        "garmin_region": {
            "question": "你的 Garmin 账号是中国区还是国际区？",
            "hint": "选择 cn 或 global；如果暂时不接 Garmin，选择 skip。",
            "options": REGIONS,
            "suggested": "cn" if os.environ.get("GARMIN_IS_CN", "").lower() == "true" else "global",
            "sensitive": False,
        },
        "garmin_account_label": {
            "question": "你的 Garmin 账号标识是什么？输入邮箱或用户名；不想保存就输入 skip。",
            "hint": "只保存到本机 .training_os/config.json，用于区分账号。绝对不要输入密码、Cookie、验证码或 token。",
            "sensitive": True,
            "optional": True,
        },
        "hooks": {
            "question": "要写入哪种 hooks 模式？",
            "hint": "codex/claude 可选 native；其他客户端选 generic；只装文件不接自动记忆选 none。",
            "options": HOOK_MODES,
            "suggested": "native" if str(answers.get("agent")) in {"codex", "claude", "auto", "all"} else "generic",
            "sensitive": False,
        },
        "confirm": {
            "question": "信息确认后要现在执行安装和验证吗？",
            "options": ["yes", "no"],
            "suggested": "yes",
            "sensitive": False,
        },
    }
    order = order_for(state)
    index = order.index(step) + 1 if step in order else len(order)
    payload = {
        "type": "question",
        "state_path": str(state_path),
        "step": step,
        "index": index,
        "total": len(order),
        "progress": f"{index}/{len(order)}",
        **questions[step],
    }
    if step == "confirm":
        payload["summary"] = public_answers(state)
    return payload


def public_answers(state: dict[str, Any]) -> dict[str, Any]:
    answers = dict(state.get("answers", {}))
    if answers.get("garmin_account_label"):
        answers["garmin_account_label"] = "[已填写，仅保存在本机]"
    return answers


def is_secret_like(value: str) -> bool:
    if len(value) > 200:
        return True
    return bool(
        re.search(
            r"^(?:sk-|bearer\s+|gh[pousr]_|eyJ[a-z0-9_-]{10,}\.|-----BEGIN)|"
            r"(?:password|passwd|验证码|cookie|token)\s*[:=]",
            value,
            flags=re.IGNORECASE,
        )
    )


def validate_answer(step: str, value: str, state: dict[str, Any]) -> tuple[str | None, str | None]:
    value = value.strip().strip('"').strip("'")
    if step == "target":
        if not value:
            return None, "请提供安装目录。"
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        return str(path), None
    if step == "agent":
        lowered = value.lower()
        if lowered not in AGENTS:
            return None, "请选择：" + ", ".join(AGENTS)
        return lowered, None
    if step == "timezone":
        if not value:
            value = suggested_timezone()
        if value != "UTC" and not re.fullmatch(r"[A-Za-z0-9_+-]+(?:/[A-Za-z0-9_+-]+)+", value):
            return None, "时区无效，请用 IANA 名称，例如 Asia/Shanghai。"
        if ZoneInfo and value != "UTC":
            try:
                ZoneInfo(value)
            except Exception:
                # Windows may not ship the IANA database; the installer can
                # still use the syntactically valid name and fall back locally.
                pass
        return value, None
    if step == "garmin_region":
        lowered = value.lower()
        if lowered not in REGIONS:
            return None, "请选择 cn、global 或 skip。"
        return lowered, None
    if step == "garmin_account_label":
        if value.lower() in {"", "skip", "none", "不保存"}:
            return "", None
        if is_secret_like(value):
            return None, "这看起来像密码或 token。请只输入邮箱/用户名，或输入 skip。"
        return value, None
    if step == "hooks":
        lowered = value.lower()
        if lowered not in HOOK_MODES:
            return None, "请选择 native、generic 或 none。"
        agent = str(state.get("answers", {}).get("agent") or "auto")
        if lowered == "native" and agent not in {"codex", "claude", "auto", "all"}:
            return None, f"{agent} 没有本项目已验证的原生 hook；请选 generic 或 none。"
        return lowered, None
    if step == "confirm":
        lowered = value.lower()
        if lowered not in {"yes", "y", "确认", "no", "n", "取消"}:
            return None, "请回答 yes 或 no。"
        return "yes" if lowered in {"yes", "y", "确认"} else "no", None
    return value, None


def run_install(state: dict[str, Any]) -> dict[str, Any]:
    answers = state["answers"]
    target = answers["target"]
    args = [
        sys.executable,
        str(INSTALL_SCRIPT),
        "--target",
        target,
        "--agent",
        answers["agent"],
        "--timezone",
        answers["timezone"],
        "--garmin-region",
        "global" if answers.get("garmin_region") == "skip" else answers["garmin_region"],
    ]
    if answers.get("garmin_account_label"):
        args.extend(["--garmin-account-label", answers["garmin_account_label"]])
    if answers.get("hooks") in {"generic", "none"}:
        args.append("--no-hooks")
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    install = subprocess.run(
        args,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=180,
        env=env,
    )
    if install.returncode != 0:
        return {
            "type": "error",
            "stage": "install",
            "message": (install.stderr or install.stdout).strip()[-2000:],
            "command": " ".join(args),
            "state_path": state["state_path"],
        }
    verify = subprocess.run(
        [sys.executable, str(VERIFY_SCRIPT), "--target", target],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=180,
        env=env,
    )
    tutorial_path = Path(target) / "START_HERE.md"
    tutorial = tutorial_path.read_text(encoding="utf-8") if tutorial_path.exists() else ""
    return {
        "type": "complete" if verify.returncode == 0 else "installed_with_warnings",
        "target": target,
        "install_output": install.stdout.strip(),
        "verify_output": verify.stdout.strip(),
        "verify_ok": verify.returncode == 0,
        "tutorial": tutorial,
        "next": [
            "Approve hooks in the agent client if the tutorial says so.",
            "Open START_HERE.md and fill coach/ATHLETE_PROFILE.md.",
            "Run training_os.py doctor before the first training conversation.",
        ],
    }


def state_path_from_args(args: argparse.Namespace) -> Path:
    if args.state:
        return Path(args.state).expanduser().resolve()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / f"setup-{uuid.uuid4().hex[:12]}.json"


def cmd_start(args: argparse.Namespace) -> int:
    path = state_path_from_args(args)
    if path.exists():
        state = load_state(path)
    else:
        state = {
            "version": 1,
            "id": uuid.uuid4().hex,
            "created_at": now_iso(),
            "status": "active",
            "answers": {},
            "state_path": str(path),
        }
        if args.target:
            state["answers"]["target"] = str(Path(args.target).expanduser().resolve())
        if args.agent:
            state["answers"]["agent"] = args.agent
        if args.timezone:
            state["answers"]["timezone"] = args.timezone
        if args.garmin_region:
            state["answers"]["garmin_region"] = args.garmin_region
        if args.garmin_account_label:
            state["answers"]["garmin_account_label"] = args.garmin_account_label
        if args.hooks:
            state["answers"]["hooks"] = args.hooks
        for step in order_for(state):
            if step not in state["answers"] or step == "confirm":
                continue
            value, error = validate_answer(step, str(state["answers"][step]), state)
            if error:
                print(
                    json.dumps(
                        {
                            "type": "validation_error",
                            "state_path": str(path),
                            "step": step,
                            "error": error,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 2
            state["answers"][step] = value
        save_state(path, state)
    print(json.dumps(question_payload(state, path), ensure_ascii=False, indent=2))
    return 0


def cmd_answer(args: argparse.Namespace) -> int:
    path = Path(args.state).expanduser().resolve()
    state = load_state(path)
    if state.get("status") == "cancelled":
        print(json.dumps({"type": "cancelled", "state_path": str(path)}, ensure_ascii=False, indent=2))
        return 0
    step = next_unanswered(state)
    if step is None:
        print(json.dumps({"type": "complete", "state_path": str(path), "message": "Setup is already complete."}, ensure_ascii=False))
        return 0
    raw_value = sys.stdin.read().strip() if args.value == "-" else args.value
    value, error = validate_answer(step, raw_value, state)
    if error:
        payload = question_payload(state, path)
        payload["type"] = "validation_error"
        payload["error"] = error
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    state.setdefault("answers", {})[step] = value
    if step == "confirm" and value == "no":
        state["status"] = "cancelled"
        save_state(path, state)
        try:
            path.unlink()
        except OSError:
            pass
        print(json.dumps({"type": "cancelled", "message": "已取消，没有安装任何文件。"}, ensure_ascii=False, indent=2))
        return 0
    if step == "confirm" and value == "yes":
        result = run_install(state)
        try:
            path.unlink()
        except OSError:
            pass
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("type") in {"complete", "installed_with_warnings"} else 1
    save_state(path, state)
    print(json.dumps(question_payload(state, path), ensure_ascii=False, indent=2))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    path = Path(args.state).expanduser().resolve()
    state = load_state(path)
    print(json.dumps(question_payload(state, path), ensure_ascii=False, indent=2))
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    path = Path(args.state).expanduser().resolve()
    if path.exists():
        path.unlink()
    print(json.dumps({"type": "reset", "state_path": str(path)}, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Interactive Endurance Training OS setup")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="Start or resume one-question-at-a-time setup")
    start.add_argument("--state")
    start.add_argument("--target")
    start.add_argument("--agent", choices=AGENTS)
    start.add_argument("--timezone")
    start.add_argument("--garmin-region", choices=REGIONS)
    start.add_argument("--garmin-account-label")
    start.add_argument("--hooks", choices=HOOK_MODES)

    answer = sub.add_parser("answer", help="Submit exactly one answer and receive the next question")
    answer.add_argument("--state", required=True)
    answer.add_argument("--value", required=True, help="One answer; use - to read stdin")

    status = sub.add_parser("status")
    status.add_argument("--state", required=True)

    reset = sub.add_parser("reset")
    reset.add_argument("--state", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    if args.command == "start":
        return cmd_start(args)
    if args.command == "answer":
        return cmd_answer(args)
    if args.command == "status":
        return cmd_status(args)
    if args.command == "reset":
        return cmd_reset(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
