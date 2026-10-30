#!/usr/bin/env python3
"""Install the Endurance Training OS into a workspace.

The installer is additive: it never overwrites athlete notes, raw data, or an
existing agent configuration. Hook and instruction changes are placed inside
managed markers so repeated runs can update them safely.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = SKILL_ROOT / "assets" / "workspace"
VERSION = "1.0.0"
AGENT_START = "<!-- >>> training-os managed block; edits inside may be replaced >>> -->"
AGENT_END = "<!-- <<< training-os managed block <<< -->"
CODEX_START = "# >>> training-os hooks; managed by install.py >>>"
CODEX_END = "# <<< training-os hooks <<<"
GIT_START = "# >>> training-os local data >>>"
GIT_END = "# <<< training-os local data <<<"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def validate_account_label(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if len(value) > 200 or re.search(
        r"^(?:sk-|bearer\s+|gh[pousr]_|eyJ[a-z0-9_-]{10,}\.|-----BEGIN)|"
        r"(?:password|passwd|验证码|cookie|token)\s*[:=]",
        value,
        flags=re.IGNORECASE,
    ):
        raise SystemExit("Garmin account label looks like a secret; use only an email/username or leave it blank")
    return value


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".tmp-{os.getpid()}")
    temp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temp, path)


def atomic_json(path: Path, payload: Any) -> None:
    atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def shell_command(parts: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(parts)
    return shlex.join(parts)


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def upsert_marked_block(text: str, start: str, end: str, block: str) -> str:
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    if pattern.search(text):
        return pattern.sub(block.rstrip(), text)
    if text and not text.endswith("\n"):
        text += "\n"
    return text + ("\n" if text else "") + block.rstrip() + "\n"


def detect_agents(target: Path, requested: str) -> list[str]:
    if requested != "auto":
        if requested == "all":
            return ["codex", "claude", "generic"]
        return [requested]
    found: list[str] = []
    if (target / ".codex").exists():
        found.append("codex")
    if (target / ".claude").exists():
        found.append("claude")
    if (target / ".cursor").exists():
        found.append("cursor")
    if (target / ".gemini").exists() or (target / "GEMINI.md").exists():
        found.append("gemini")
    if not found:
        if os.environ.get("CODEX_HOME"):
            found.append("codex")
        elif os.environ.get("CLAUDE_CONFIG_DIR"):
            found.append("claude")
        else:
            found.append("generic")
    return found


def copy_workspace_assets(target: Path, dry_run: bool) -> list[str]:
    actions: list[str] = []
    overwrite = {
        Path(".training_os/bin/agent_memory.py"),
        Path(".training_os/bin/training_os.py"),
        Path(".training_os/AGENT_GUIDE.md"),
        Path(".training_os/hooks/agent-memory.cmd"),
        Path(".training_os/hooks/agent-memory.sh"),
        Path(".training_os/gitignore.fragment"),
    }
    for source in ASSET_ROOT.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(ASSET_ROOT)
        if "__pycache__" in relative.parts:
            continue
        if relative == Path("AGENTS.training-os.md"):
            continue
        if relative.parts[0] == "coach":
            destination = target / relative
            if destination.exists():
                continue
        elif relative.parts[:2] == (".training_os", "mcp"):
            destination = target / relative
            if destination.exists():
                continue
        else:
            destination = target / relative
            if destination.exists() and relative not in overwrite:
                continue
        actions.append(f"copy {relative.as_posix()}")
        if not dry_run:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    if not dry_run:
        hook = target / ".training_os" / "hooks" / "agent-memory.sh"
        if hook.exists() and os.name != "nt":
            hook.chmod(0o755)
    return actions


def write_config(
    target: Path,
    agents: list[str],
    timezone: str,
    garmin_region: str,
    garmin_account_label: str,
    dry_run: bool,
) -> list[str]:
    path = target / ".training_os" / "config.json"
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                existing = payload
        except (OSError, json.JSONDecodeError):
            raise SystemExit(f"Refusing to overwrite invalid JSON config: {path}")
    config = {
        "version": 1,
        "installed_version": VERSION,
        "deployed_at": existing.get("deployed_at") or now_iso(),
        "agent": agents,
        "timezone": timezone,
        "coach_dir": "coach",
        "data_dir": "data",
        "memory": {
            "timezone": timezone,
            "budgets": {
                "startup_chars": 3800,
                "startup_tokens_est": 1600,
                "prompt_chars": 3000,
                "prompt_tokens_est": 1200,
                "search_chars": 7500,
                "search_tokens_est": 2400,
                "max_item_chars": 560,
                "max_turn_excerpt_chars": 700,
                "chars_per_token_estimate": 2.0,
            },
            "scoring": {
                "recent_days": 14,
                "temporary_state_days": 7,
                "major_importance": 9,
                "recency_half_life_days": 45,
            },
            "limits": {
                "long_term_max_items": 220,
                "recent_max_items": 24,
                "index_max_items": 80,
                "max_candidates_per_turn": 8,
            },
            "extraction": {
                "minimum_sentence_chars": 8,
                "maximum_sentence_chars": 700,
                "near_duplicate_ratio": 0.94,
            },
            "privacy": {
                "archive_full_transcripts": True,
                "archive_relative_dir": "archive/sessions",
            },
        },
        "garmin": {
            "mcp_server": "garmin",
            "read_only": True,
            "overlap_days": 3,
            "initial_days": 21,
            "region": garmin_region,
            "account_label": garmin_account_label,
        },
    }
    merged = deep_merge(config, existing)
    merged["installed_version"] = VERSION
    merged["agent"] = sorted(set(agents))
    merged["timezone"] = timezone
    if not isinstance(merged.get("memory"), dict):
        merged["memory"] = {}
    merged["memory"]["timezone"] = timezone
    if not isinstance(merged.get("garmin"), dict):
        merged["garmin"] = {}
    merged["garmin"]["region"] = garmin_region
    if garmin_account_label:
        merged["garmin"]["account_label"] = garmin_account_label
    if not dry_run:
        atomic_json(path, merged)
    return ["write .training_os/config.json"]


def write_mcp_templates(target: Path, garmin_region: str, dry_run: bool) -> list[str]:
    if garmin_region != "cn":
        return []
    actions: list[str] = []
    for relative in (
        Path(".training_os/mcp/codex.fragment.toml"),
        Path(".training_os/mcp/claude.mcp.json"),
        Path(".training_os/mcp/generic.mcp.json"),
    ):
        path = target / relative
        source = ASSET_ROOT / relative
        if not path.exists() or not source.exists():
            continue
        current = path.read_text(encoding="utf-8")
        original = source.read_text(encoding="utf-8")
        if current != original:
            continue
        updated = current.replace('GARMIN_IS_CN = "false"', 'GARMIN_IS_CN = "true"').replace(
            '"GARMIN_IS_CN": "false"', '"GARMIN_IS_CN": "true"'
        )
        if updated != current:
            actions.append(f"set Garmin region to CN in {relative.as_posix()}")
            if not dry_run:
                atomic_write(path, updated)
    return actions


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in base.items():
        incoming = override.get(key)
        if isinstance(value, dict) and isinstance(incoming, dict):
            result[key] = deep_merge(value, incoming)
        elif key in override:
            result[key] = incoming
        else:
            result[key] = value
    for key, value in override.items():
        if key not in result:
            result[key] = value
    return result


def agent_block(target: Path, python: str) -> str:
    short = (ASSET_ROOT / "AGENTS.training-os.md").read_text(encoding="utf-8")
    body = short.replace(AGENT_START, "").replace(AGENT_END, "").strip()
    return f"{AGENT_START}\n{body}\n{AGENT_END}"


def install_agent_entries(target: Path, agents: list[str], python: str, dry_run: bool) -> list[str]:
    actions: list[str] = []
    block = agent_block(target, python)

    agents_md = target / "AGENTS.md"
    existing = agents_md.read_text(encoding="utf-8") if agents_md.exists() else ""
    updated = upsert_marked_block(existing, AGENT_START, AGENT_END, block)
    if updated != existing:
        actions.append("update AGENTS.md")
        if not dry_run:
            atomic_write(agents_md, updated)

    if "claude" in agents:
        claude = target / "CLAUDE.md"
        existing = claude.read_text(encoding="utf-8") if claude.exists() else ""
        claude_block = f"{AGENT_START}\n@AGENTS.md\n{AGENT_END}"
        updated = upsert_marked_block(existing, AGENT_START, AGENT_END, claude_block)
        if not updated.strip():
            updated = "# Project Instructions\n\n@AGENTS.md\n"
        if updated != existing:
            actions.append("update CLAUDE.md")
            if not dry_run:
                atomic_write(claude, updated)

    if "gemini" in agents:
        gemini = target / "GEMINI.md"
        existing = gemini.read_text(encoding="utf-8") if gemini.exists() else ""
        updated = upsert_marked_block(existing, AGENT_START, AGENT_END, block)
        if updated != existing:
            actions.append("update GEMINI.md")
            if not dry_run:
                atomic_write(gemini, updated)

    if "cursor" in agents:
        rule = target / ".cursor" / "rules" / "training-os.mdc"
        existing = rule.read_text(encoding="utf-8") if rule.exists() else ""
        frontmatter = (
            "---\n"
            "description: Local training workspace rules\n"
            "globs:\n"
            "alwaysApply: true\n"
            "---\n\n"
        )
        content = frontmatter + block
        if existing != content:
            actions.append("update .cursor/rules/training-os.mdc")
            if not dry_run:
                atomic_write(rule, content)

    return actions


def hook_command(target: Path, python: str) -> str:
    return shell_command([python, str(target / ".training_os" / "bin" / "agent_memory.py"), "hook"])


def codex_event_snippet(event: str, command: str, timeout: int, status: str) -> str:
    return (
        f"{event} = [\n"
        f"  {{ hooks = [\n"
        f"    {{ type = \"command\", command = {toml_string(command)}, "
        f"timeout = {timeout}, async = false, statusMessage = {toml_string(status)} }}\n"
        f"  ] }}\n"
        f"]"
    )


def section_bounds(text: str, header: str) -> tuple[int, int] | None:
    match = re.search(rf"(?m)^\[{re.escape(header)}\]\s*$", text)
    if not match:
        return None
    start = match.end()
    next_header = re.search(r"(?m)^\[[^\]]+\]\s*$", text[start:])
    end = start + next_header.start() if next_header else len(text)
    return start, end


def install_codex_hooks(target: Path, python: str, dry_run: bool) -> tuple[list[str], list[str]]:
    path = target / ".codex" / "config.toml"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    command = hook_command(target, python)
    events = [
        ("SessionStart", 60, "Loading local memory"),
        ("UserPromptSubmit", 60, "Retrieving relevant local memory"),
        ("Stop", 120, "Archiving local memory"),
        ("Interrupt", 3, "Saving interrupted turn"),
        ("SessionEnd", 3, "Finalizing local memory"),
    ]
    snippets = {name: codex_event_snippet(name, command, timeout, status) for name, timeout, status in events}

    block = CODEX_START + "\n" + "\n".join(snippets.values()) + "\n" + CODEX_END
    warnings: list[str] = []
    if CODEX_START in text and CODEX_END in text:
        text = re.sub(
            re.escape(CODEX_START) + r".*?" + re.escape(CODEX_END),
            block,
            text,
            flags=re.DOTALL,
        )
    else:
        bounds = section_bounds(text, "hooks")
        if bounds is None:
            if text and not text.endswith("\n"):
                text += "\n"
            text += "\n[hooks]\n" + block + "\n"
        else:
            start, end = bounds
            section = text[start:end]
            additions: list[str] = []
            for name, snippet in snippets.items():
                if re.search(rf"(?m)^{re.escape(name)}\s*=", section):
                    value_match = re.search(
                        rf"(?ms)^{re.escape(name)}\s*=\s*(.*?)(?=^[A-Za-z_][A-Za-z0-9_]*\s*=|\Z)",
                        section,
                    )
                    value = value_match.group(1) if value_match else ""
                    if "agent_memory.py" not in value:
                        warnings.append(
                            f"已保留原有的 {name} hook；请手工把 agent_memory.py 合并进去，"
                            "否则该事件的本地记忆不会自动运行。"
                        )
                    continue
                additions.append(snippet)
            if additions:
                insert = "\n" + CODEX_START + "\n" + "\n".join(additions) + "\n" + CODEX_END + "\n"
                text = text[:end] + insert + text[end:]

    memories_bounds = section_bounds(text, "memories")
    if memories_bounds is None:
        text += (
            "\n# Avoid duplicate unbudgeted app-level memory when the local system is active.\n"
            "[memories]\n"
            "generate_memories = false\n"
            "use_memories = false\n"
        )
    else:
        start, end = memories_bounds
        memory_section = text[start:end]
        if re.search(r"(?m)^generate_memories\s*=\s*true\s*$", memory_section) or re.search(
            r"(?m)^use_memories\s*=\s*true\s*$", memory_section
        ):
            warnings.append(
                "现有 [memories] 仍启用了应用自带记忆；为避免重复注入，请评估后改为 false，"
                "安装器没有擅自覆盖该设置。"
            )
    if not dry_run:
        atomic_write(path, text)
    return ["merge .codex/config.toml hooks"], warnings


def claude_hook_entry(command: str, timeout: int) -> dict[str, Any]:
    return {"hooks": [{"type": "command", "command": command, "timeout": timeout}]}


def install_claude_hooks(target: Path, python: str, dry_run: bool) -> list[str]:
    path = target / ".claude" / "settings.json"
    payload: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"Refusing to overwrite invalid JSON: {path}: {exc}")
        if not isinstance(loaded, dict):
            raise SystemExit(f"Refusing to overwrite non-object settings: {path}")
        payload = loaded
    hooks = payload.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise SystemExit(f"Refusing to overwrite non-object hooks: {path}")
    command = hook_command(target, python)
    for event, timeout in [
        ("SessionStart", 60),
        ("UserPromptSubmit", 60),
        ("Stop", 120),
        ("SessionEnd", 10),
        ("PreCompact", 30),
    ]:
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list):
            raise SystemExit(f"Refusing to overwrite non-list hook event {event}: {path}")
        if any(command in json.dumps(item, ensure_ascii=False) for item in entries):
            continue
        entries.append(claude_hook_entry(command, timeout))
    if not dry_run:
        atomic_json(path, payload)
    return ["merge .claude/settings.json hooks"]


def install_gitignore(target: Path, dry_run: bool) -> list[str]:
    path = target / ".gitignore"
    fragment = (ASSET_ROOT / ".training_os" / "gitignore.fragment").read_text(encoding="utf-8")
    block = f"{GIT_START}\n{fragment.strip()}\n{GIT_END}"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    updated = upsert_marked_block(existing, GIT_START, GIT_END, block)
    if updated != existing:
        if not dry_run:
            atomic_write(path, updated)
        return ["update .gitignore"]
    return []


def init_memory(target: Path, python: str, dry_run: bool) -> list[str]:
    if dry_run:
        return ["initialize local memory database"]
    script = target / ".training_os" / "bin" / "agent_memory.py"
    result = subprocess.run(
        [python, str(script), "init"],
        cwd=target,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"Memory initialization failed:\n{result.stdout}\n{result.stderr}")
    return ["initialize local memory database"]


def start_here_text(
    target: Path,
    agents: list[str],
    python: str,
    timezone: str,
    hooks: list[str],
    warnings: list[str] | None = None,
) -> str:
    agent_text = "、".join(agents)
    hook_text = "\n".join(f"- {line}" for line in hooks) if hooks else "- 未写入原生 hooks（通用模式）"
    warning_text = ""
    if warnings:
        warning_text = "\n## 注意\n\n" + "\n".join(f"- {item}" for item in warnings) + "\n"
    return f"""# 从这里开始

训练助手工作区已安装到：

`{target}`

- Agent 适配：{agent_text}
- 时区：{timezone}
- Python：`{python}`
- 版本：{VERSION}

## 1. 先完成三项配置

1. **批准 hooks**
   - Codex：打开本项目，运行 `/hooks`，确认命令只指向本项目 `.training_os/hooks/` 或 `.training_os/bin/agent_memory.py`，再设为信任。
   - Claude Code：检查 `.claude/settings.json`，重启会话。
   - 其他 agent：没有原生 hook 时，按下面“通用模式”使用。
2. **连接 Garmin**
   - 确认 `garmin-mcp` 与认证命令已安装；首次认证只在用户本机完成。
   - 不要把 token、Cookie 或密码写入项目。
   - 在 agent 中加载 MCP 后，先做一次只读的最近活动查询。
3. **填写档案**
   - 打开 `coach/ATHLETE_PROFILE.md`，只填你确认的事实。
   - 至少填写：时区、每周可用时间、主要目标、当前疼痛/伤病、训练体系偏好。

## 2. 安装动作

{hook_text}
{warning_text}
## 3. 常用命令

```bash
python .training_os/bin/training_os.py doctor
python .training_os/bin/training_os.py status
python .training_os/bin/training_os.py garmin-plan --today YYYY-MM-DD
python .training_os/bin/agent_memory.py context --task "本周训练" --budget-kind prompt
python .training_os/bin/agent_memory.py search --query "关键词"
python .training_os/bin/training_os.py backup
```

## 4. 第一次对话怎么问

可以直接说：

> 读取训练档案，检查 Garmin 最近数据，先告诉我数据覆盖到哪天、有哪些缺口；暂时不要给课表。

确认数据后再说：

> 根据我确认的目标、可用时间和身体状态，给我未来 7 天安排。每次训练写清目的、强度口径和调整条件。

## 5. 通用模式

如果当前 agent 没有原生 hooks，在每个新会话开始时运行：

```bash
python .training_os/bin/agent_memory.py context --task "<当前问题>" --budget-kind startup
```

会话结束时，如果 agent 能提供 transcript 路径：

```bash
python .training_os/bin/agent_memory.py ingest --transcript "<路径>"
```

否则用 `capture` 手工保存关键对话：

```bash
python .training_os/bin/agent_memory.py capture --session "<会话名>" --prompt "<用户原话>" --assistant "<助手结论>"
```

## 6. 隐私

- `.training_os/data/`、`.training_os/archive/`、`data/garmin/raw/` 都是本地敏感数据。
- 备份会包含完整对话和健康数据，按敏感资料保管。
- 本地存储不等于模型推理完全离线。
- Garmin 默认只读；上传课表或修改账户配置必须每次明确授权。

## 7. 第一周建议

1. 先建立数据基线，不急着加量。
2. 记录每次训练的完成度、主观感受和疼痛。
3. 一周后只复盘一次，下一周只改变一个主要变量。
"""


def write_start_here(
    target: Path,
    agents: list[str],
    python: str,
    timezone: str,
    hooks: list[str],
    warnings: list[str],
    dry_run: bool,
) -> str:
    text = start_here_text(target, agents, python, timezone, hooks, warnings)
    if not dry_run:
        atomic_write(target / "START_HERE.md", text)
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install Endurance Training OS")
    parser.add_argument("--target", required=True, help="Workspace to install into")
    parser.add_argument(
        "--agent",
        default="auto",
        choices=["auto", "codex", "claude", "cursor", "gemini", "generic", "all"],
        help="Agent adapter; auto detects existing configuration",
    )
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--garmin-region", choices=["cn", "global"], default="global")
    parser.add_argument(
        "--garmin-account-label",
        default="",
        help="Optional local-only account label; never pass a password or token",
    )
    parser.add_argument("--python", default=sys.executable, help="Python executable used by hooks")
    parser.add_argument("--no-hooks", action="store_true", help="Install instructions and files only")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    target = Path(args.target).expanduser().resolve()
    args.garmin_account_label = validate_account_label(args.garmin_account_label)
    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10+ is required")
    if not ASSET_ROOT.exists():
        raise SystemExit(f"Missing asset directory: {ASSET_ROOT}")

    agents = detect_agents(target, args.agent)
    actions: list[str] = []
    if not args.dry_run:
        target.mkdir(parents=True, exist_ok=True)
    actions.extend(copy_workspace_assets(target, args.dry_run))
    actions.extend(
        write_config(
            target,
            agents,
            args.timezone,
            args.garmin_region,
            args.garmin_account_label,
            args.dry_run,
        )
    )
    actions.extend(write_mcp_templates(target, args.garmin_region, args.dry_run))
    actions.extend(install_agent_entries(target, agents, args.python, args.dry_run))

    hooks: list[str] = []
    warnings: list[str] = []
    if not args.no_hooks:
        if "codex" in agents:
            codex_actions, codex_warnings = install_codex_hooks(target, args.python, args.dry_run)
            actions.extend(codex_actions)
            warnings.extend(codex_warnings)
            hooks.append("Codex hooks 已写入 `.codex/config.toml`；需要在 `/hooks` 中批准。")
        if "claude" in agents:
            actions.extend(install_claude_hooks(target, args.python, args.dry_run))
            hooks.append("Claude Code hooks 已写入 `.claude/settings.json`。")
        if not any(item in agents for item in ("codex", "claude")):
            hooks.append("当前为通用模式：会话开始运行 context，结束运行 capture 或 ingest。")
    else:
        hooks.append("按 `--no-hooks` 跳过原生 hook 配置。")

    actions.extend(install_gitignore(target, args.dry_run))
    actions.extend(init_memory(target, args.python, args.dry_run))
    tutorial = write_start_here(target, agents, args.python, args.timezone, hooks, warnings, args.dry_run)

    if not args.dry_run:
        atomic_json(
            target / ".training_os" / "deployment.json",
            {
                "version": VERSION,
                "installed_at": now_iso(),
                "agents": agents,
                "timezone": args.timezone,
                "hooks": hooks,
                "python": args.python,
            },
        )

    print("=" * 68)
    print(f"Endurance Training OS {VERSION}")
    print("=" * 68)
    print(f"Target : {target}")
    print(f"Agents : {', '.join(agents)}")
    print(f"Mode   : {'dry-run' if args.dry_run else 'installed'}")
    print()
    print("Actions")
    print("-" * 68)
    for action in actions:
        print(f"  {action}")
    if warnings:
        print()
        print("Warnings")
        print("-" * 68)
        for warning in warnings:
            print(f"  WARNING: {warning}")
    print()
    print(tutorial)
    if args.dry_run:
        print("Dry run complete. Re-run without --dry-run to apply.")
    else:
        print("Next: run scripts/verify.py --target <workspace>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
