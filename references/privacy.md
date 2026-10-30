# Privacy and Release Checks

发布这个 Skill 前，运行：

```bash
python "<skill-root>/scripts/package_check.py" .
```

检查项：

- 不含 `memory.sqlite3`、JSONL 会话归档、ZIP 备份、Garmin raw；
- 不含 API Key、Bearer token、Cookie、密码、私钥；
- 不含部署者姓名、城市、学校、单位、比赛成绩、伤病、书籍偏好；
- 不含真实邮箱或 Garmin 账号标识；示例邮箱只允许 `example.com` 等保留域名；
- 不含绝对个人路径（如 `C:\Users\<name>`、`/home/<name>`）；
- 示例只使用明显的占位符，如 `example.com`、`<workspace>`、`2026-01-01`。

## 安装后的本地隐私

- `.training_os/`、`data/`、`coach/` 默认加入 `.gitignore` 的本地数据规则。
- 对话式安装收集的 Garmin 账号标识只写入目标目录的 `.training_os/config.json`；密码、Cookie、验证码和 token 永远不进入本项目。
- 若用户要提交训练项目到 Git，先确认哪些 Markdown 可以公开；数据库、归档和 raw 数据默认不提交。
- 备份可能包含完整对话和健康数据，按敏感资料保管。
- 模型推理可能经过远程 API；“本地存储”不等于“推理完全离线”。
- 不把 `library/` 或用户资料上传到第三方解析服务，除非用户明确要求。
