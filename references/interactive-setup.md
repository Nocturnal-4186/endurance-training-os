# Interactive Setup

## 原则

一次只问一个问题。每个问题都必须等用户回答后再问下一个；不要替用户猜安装目录、账号或 hooks 模式。

对话式安装器把状态保存在系统临时目录的 JSON 文件中，不在项目目录里保存未完成的安装状态。最终确认安装后，状态文件会删除。

## 状态机

```text
target
  -> agent
  -> timezone
  -> garmin_region
  -> garmin_account_label   (region=skip 时跳过)
  -> hooks
  -> confirm
  -> install + verify
```

## 每一步

### 1. 安装目录

问：“你希望把训练助手安装到哪个文件夹？请输入绝对路径。”

不要默认替用户安装到 Skill 所在目录。可以把当前工作区作为建议，但必须由用户确认。

### 2. Agent

选项：`auto`、`codex`、`claude`、`cursor`、`gemini`、`generic`、`all`。

- `auto`：检测目标目录已有配置；不确定时推荐。
- `codex` / `claude`：可以写原生 hooks。
- `cursor` / `gemini`：使用入口文件，hooks 走通用或手工模式。
- `generic`：只保证 AGENTS 指南和手工命令。

### 3. 时区

使用 IANA 名称，例如 `Asia/Shanghai`、`Europe/London`、`America/New_York`。Windows 没有 IANA 数据时安装器仍可保存名称，但本地时间显示可能退化为系统本地时间。

### 4. Garmin 区域

`cn`、`global` 或 `skip`。区域只决定 MCP 模板中的 `GARMIN_IS_CN`，不影响历史数据。

### 5. Garmin 账号标识

只接受邮箱或用户名，最多 200 字符；可输入 `skip`。拒绝包含密码、Cookie、验证码、token 或明显密钥形态的输入。

账号标识保存在目标目录 `.training_os/config.json` 的 `garmin.account_label`，仅供本机识别。不要把它写入 Skill 文件、AGENTS 规则、日志或公开仓库。

### 6. Hooks 模式

- `native`：Codex / Claude Code 写原生 hooks。
- `generic`：不写原生 hooks，使用会话开始/结束命令。
- `none`：只安装文件和档案，不接自动记忆。

### 7. 最终确认

展示不含账号标识明文的摘要。用户回答 `yes` 后，运行安装器和验证器；只有验证通过或明确报告失败项，才能说安装完成。

## 示例对话

```text
AI：你希望把训练助手安装到哪个文件夹？请输入绝对路径。
用户：D:\running-coach
AI：你主要用哪一个 agent？
用户：Codex
AI：你的本地时区是什么？
用户：Asia/Shanghai
AI：你的 Garmin 账号是中国区还是国际区？
用户：中国区
AI：你的 Garmin 账号标识是什么？输入邮箱或用户名；不想保存就输入 skip。
用户：runner@example.com
AI：要写入哪种 hooks 模式？
用户：native
AI：确认安装到 D:\running-coach，使用 Codex、Asia/Shanghai、中国区 Garmin、native hooks 吗？
用户：yes
AI：安装完成，14 项验证通过。下面是 START_HERE 教程……
```

示例邮箱只用于展示，不得替换成真实用户账号写入 Skill。

## 命令

```bash
python "<skill-root>/scripts/setup.py" start
python "<skill-root>/scripts/setup.py" answer --state "<state_path>" --value "<one answer>"
python "<skill-root>/scripts/setup.py" status --state "<state_path>"
python "<skill-root>/scripts/setup.py" reset --state "<state_path>"
```

`start` 可预填用户已经明确提供的参数：

```bash
python "<skill-root>/scripts/setup.py" start --target "D:\running-coach" --agent codex --timezone Asia/Shanghai
```

预填不等于替用户回答；缺失项仍然逐个询问。
