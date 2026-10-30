# Onboarding

安装完成后，先给用户一个“现在就能用”的版本，再逐项补配置。不要一次问十几个问题。

首次安装应优先使用 `<skill-root>/scripts/setup.py start` 的逐题模式；下面的问卷用于安装后的训练档案补充，不要和安装参数混在一起一次问完。

## 第一屏必须包含

1. 已安装到哪个目录、识别成哪个 agent；
2. 哪些 hooks 已写入，哪些需要用户在客户端里批准；
3. Garmin 是否已实际探测成功；若未配置，说明下一步；
4. 三条最常用命令；
5. 下一步只需要用户回答的 3 个问题。

## 最小配置问卷

先问这三项：

1. 你的时区，以及一周通常哪几天、每次多少分钟可以训练？
2. 你现在最想解决的目标是什么？有近期比赛或可靠计时吗？
3. 当前有没有疼痛、伤病、疾病、睡眠问题或医生限制？

得到回答后写入 `coach/ATHLETE_PROFILE.md`，标明“用户确认”和日期。

## 第二轮配置

- 训练体系与术语：用户指定哪套体系，就按哪套；未指定时先做能力与安全评估，不擅自套模板。
- 数据来源：Garmin 账号区域、MCP 名称、是否有历史导出。
- 可用设备：手表型号、心率带、跑鞋、场地/跑步机。
- 生活约束：课程/工作、通勤、天气、旅行。
- 记录偏好：每周课表直接在对话中给，还是同时写入阶段文件。

## 第一周操作

1. 建立基线：最近 21 天活动、7 天睡眠、21 天 HRV、最近一次可靠计时。
2. 只做一次轻量能力判断；证据不足时标“待核实”。
3. 给出 7 天安排，明确每天目的、强度、时长和调整条件。
4. 每次训练后记录主观感受、疼痛和完成度；不要只抄设备数据。
5. 一周后复盘：完成率、疲劳、疼痛、睡眠、下一周只改变一个变量。

## 记忆使用说明

- 自动注入的记忆是摘要，需要原文时查看来源路径。
- 用户说“记住”时立即写入；用户更正时保留旧记录并标记 `superseded`。
- 用户说“忘掉”时先软删除；需要彻底清除派生记录时才 `--purge`，原始归档不擅自改写。
- 不要把完整数据库、Garmin raw 或归档提交到公开仓库。

## 常用命令

```bash
python .training_os/bin/agent_memory.py context --task "本周训练" --budget-kind prompt
python .training_os/bin/agent_memory.py search --query "膝盖"
python .training_os/bin/agent_memory.py remember --kind constraint --content "..." --importance 9
python .training_os/bin/training_os.py doctor
python .training_os/bin/training_os.py backup
```

Windows 将 `python` 换成实际解释器；路径使用双引号。
