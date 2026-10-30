# Architecture

## 分层

```text
<workspace>/
├── AGENTS.md / CLAUDE.md / GEMINI.md     agent 入口，只放短规则和路径
├── START_HERE.md                        人类首次配置教程
├── .training_os/
│   ├── AGENT_GUIDE.md                   运行时手册
│   ├── config.json                      时区、预算、Garmin 参数
│   ├── bin/
│   │   ├── agent_memory.py              记忆、归档、hooks、检索
│   │   └── training_os.py               环境检查、Garmin 批次、备份
│   ├── hooks/                           跨平台 hook 入口
│   ├── data/memory.sqlite3              结构化记忆索引
│   ├── archive/sessions/                原始会话追加归档
│   ├── backups/                         本地 ZIP
│   └── logs/                            hook 与维护错误
├── coach/
│   ├── ATHLETE_PROFILE.md               用户确认的事实、目标、约束
│   ├── TRAINING_LOG.md                  训练反馈与阶段记录
│   ├── DATA_AUDIT.md                    每次数据批次与去重审计
│   ├── DECISIONS.md                     训练决策和修订
│   ├── LIBRARY_INDEX.md                 用户自备资料的索引
│   └── phases/                          阶段总结
└── data/
    └── garmin/
        ├── raw/                         只追加的 MCP 原始响应
        └── state.json                   水位线、最近成功日期
```

## 三套证据不要混用

| 层 | 作用 | 权威性 |
|---|---|---|
| `coach/` | 用户确认的事实、目标、决策、当前约束 | 高；冲突时保留修订痕迹 |
| `.training_os/archive/` | 完整对话原文 | 证据；不等于已确认事实 |
| `data/garmin/raw/` | 设备/MCP 原始响应 | 设备事实；不等于用户感受或比赛官方成绩 |

`.training_os/data/memory.sqlite3` 只是索引和派生摘要，不能代替原始归档。

`scripts/setup.py` 不把未完成的安装状态写进目标项目；它把逐题状态放在系统临时目录，最终确认后执行 `install.py` 和 `verify.py`。

## 会话生命周期

1. SessionStart：读取预算化核心记忆、近期状态和最近对话。
2. UserPromptSubmit：保存当前用户消息，按问题检索相关记忆。
3. Stop/SessionEnd：追加会话原文，提取候选记忆，更新 Markdown 视图。
4. Interrupt：尽力保存已完成内容；受超时限制，不能保证完整。

没有常驻守护进程。应用关闭后不会继续采集；下次启动或显式 `reconcile` 只能补读仍可访问的 transcript。

## 写入原则

- 原始归档和 Garmin raw 只追加。
- Markdown 档案按章节增量更新，重要修订保留旧值和日期。
- SQLite 写入使用事务和进程锁。
- 事实标签统一为：用户确认、设备/文件记录、分析推断、待核实。
- 临时状态必须有日期，并设置过期；长期目标、安全约束和明确更正不因时间久远自动消失。
