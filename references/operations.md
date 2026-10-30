# Operations

## 首次安装：逐题对话

优先使用：

```bash
python "<skill-root>/scripts/setup.py" start
```

把返回的 `question` 一次只转给用户一题；用户回答后调用 `setup.py answer`。最后确认 `yes` 时，安装器会自动运行安装和验证。命令行参数安装只用于用户已经明确给出全部配置，或 agent 无法执行本地命令的情况。

## 安装与升级

```bash
python "<skill-root>/scripts/install.py" --target <workspace> --agent auto --timezone Asia/Shanghai
python "<skill-root>/scripts/verify.py" --target <workspace>
```

重复运行安装器只更新带标记的块和程序文件，不重复追加 hooks。用户档案、训练日志、原始数据和记忆数据库不会被覆盖。

## Hook 批准

- Codex：打开项目，运行 `/hooks`，确认命令只指向本项目 `.training_os/hooks/`，再批准。
- Claude Code：检查 `.claude/settings.json` 中的命令，重启会话；首次运行可能要求确认。
- 其他 agent：按客户端要求注册命令，或使用通用模式手工调用。

修改 hook 命令后，信任状态通常会失效，需要重新审核。

## 日常命令

```bash
python .training_os/bin/agent_memory.py stats
python .training_os/bin/agent_memory.py reconcile --agent auto
python .training_os/bin/agent_memory.py maintain
python .training_os/bin/agent_memory.py backup
python .training_os/bin/training_os.py doctor
python .training_os/bin/training_os.py status
```

## 恢复

```bash
python .training_os/bin/training_os.py restore \
  --backup .training_os/backups/<file>.zip \
  --target <empty-directory>
```

恢复只允许写入空目录。核对数据库、归档和 Markdown 后再人工替换，不直接覆盖现有状态。

## 迁移到另一家 agent

数据不需要重装。保留整个工作区，重新运行：

```bash
python "<skill-root>/scripts/install.py" --target <workspace> --agent claude
```

安装器会新增对应入口和 hooks，原有 `.training_os/` 与 `coach/` 继续使用。

## 卸载

先备份，再删除该项目中的 `.training_os/`、`data/garmin/raw/` 和带 `training-os` 标记的配置块。不要直接删除整个工作区；用户可能还有其他资料。

## 故障排查

- 没有注入记忆：检查 hook 是否批准、命令路径是否存在、stdin 是否为 JSON。
- 记忆为空：先运行 `context`，再检查 `stats` 和 `logs/hook-errors.log`。
- 归档缺失：运行 `reconcile`；仍缺失时检查 transcript 路径和权限。
- Garmin 无数据：确认 MCP 已认证、区域设置正确、工具列表实际加载；不要改成网页抓取。
- SQLite 损坏：停止写入，保留原文件，从最近备份恢复到新目录。
