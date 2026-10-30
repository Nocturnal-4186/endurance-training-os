# Memory Engine

## 设计目标

模拟“长期经历 + 重要印象 + 近期优先”的检索，而不是把完整聊天记录塞进每次上下文。完整原文留在归档，SQLite 只保存可检索的记忆和会话索引。

## 数据表

| 表 | 作用 |
|---|---|
| `memories` | 事实、目标、约束、决定、临时状态、更正；带重要性、置信度、状态、来源 |
| `memory_mentions` | 每次提及的来源和摘要 |
| `turns` | 用户/助手轮次索引，指向原始 transcript |
| `sessions` | agent、工作目录、来源路径 |
| `archive_state` | 原文追加归档的偏移和水位线 |
| `prompt_events` | 在 transcript 尚未落盘前暂存当前 prompt |
| `operations` | 维护、导入、错误诊断 |

`memories_fts` 和 `turns_fts` 存在时用于加速；缺失时仍可运行，但检索会变慢。

## 提取规则

- 只从用户消息提取，不把助手推断自动升级为用户事实。
- 识别：个人事实、偏好、目标、事件、决定、限制/安全、任务、临时状态、反复模式、更正、伤病。
- 明确“记住/确认/长期”会提高重要性。
- 临时状态设置过期时间；过期后保留但不再进入默认上下文。
- 近似重复会合并 mention，不重复累计。
- 代码/配置说明和路径行会被抑制，避免把部署过程写成长篇“个人记忆”。

自动提取是启发式，不是语义审阅。用户更正必须用 `correct`，不要靠模型猜。

## 上下文预算

默认：

| 场景 | 字符上限 | token 估算上限 |
|---|---:|---:|
| SessionStart | 3800 | 1600 |
| UserPromptSubmit | 3000 | 1200 |
| 手动检索 | 7500 | 2400 |

运行时同时受字符和估算 token 限制；`2 字符≈1 token` 只是保守估算。优先级：核心长期记忆、近期/未完成、与当前问题相关、最近对话。超出预算会明确写出省略数量。

## 常用命令

```bash
python .training_os/bin/agent_memory.py context --task "当前问题" --budget-kind prompt
python .training_os/bin/agent_memory.py search --query "关键词"
python .training_os/bin/agent_memory.py show --id mem_...
python .training_os/bin/agent_memory.py show-turn --session ... --turn ...
python .training_os/bin/agent_memory.py remember --kind goal --content "..." --importance 9
python .training_os/bin/agent_memory.py correct --id mem_... --content "更正后的内容"
python .training_os/bin/agent_memory.py forget --id mem_...
python .training_os/bin/agent_memory.py maintain
python .training_os/bin/agent_memory.py backup
```

`forget --purge` 只清除派生记忆和 mention，不改写原始会话归档。

## 归档与对账

- transcript 按追加偏移写入 `.training_os/archive/sessions/<session>/transcript-*.jsonl`。
- 同一路径增长时只追加新增字节；路径被替换或截断时新建 segment。
- Codex 和 Claude Code 的 JSONL 格式都能解析；通用 agent 可用 `capture` 手工保存。
- 关闭客户端后没有后台守护进程；下次启动或 `reconcile` 只能补读仍可访问的 transcript。
- `reconcile --agent codex|claude|auto` 按项目路径过滤，避免把无关项目会话导入。

## 已知限制

1. hook 输入格式会随 agent 版本变化；安装后必须实际试运行，不只看配置。
2. 关键词检索不是向量语义检索；跨语言同义表达可能漏检。
3. 自动提取会漏掉含蓄表达，也会误收部分陈述；需要用户纠正。
4. `Interrupt`/`SessionEnd` 有超时上限，极长 transcript 可能来不及完整处理。
5. 本地存储不等于模型推理离线；不要把敏感归档上传第三方。
