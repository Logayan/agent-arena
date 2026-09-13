# Claude SDK 健康长回合取消默认 Turn 上限

日期：2026-09-13

## 现场与根因

真实 Run `run_bda13e93b2ea` Version 9 的 epoch30 独立贡献阶段中，QA 与安全角色在持续产生工具、文件和测试事件后被平台记为可重试 `runtime_failure`，并非 heartbeat 停滞超时。

Claude Code 持久 Session 的原始记录给出确定性根因：

| 角色 | SDK Session | 终态附件 | 配置 | 实际计数 |
|---|---|---|---:|---:|
| QA | `02ba4382-f8f2-49df-90c3-9335037a3376` | `max_turns_reached` | 100 | 101 |
| 安全 | `9954a43b-88c4-4cab-9658-2f77d59f0513` | `max_turns_reached` | 100 | 101 |
| QA 历史回合 | `80563164-e52f-47a8-9b03-04b0d751bde5` | `max_turns_reached` | 100 | 101 |

此前 Runtime 已把墙钟超时改为 heartbeat 驱动的停滞检测，但启动脚本仍设置 `JIANGHU_CLAUDE_MAX_TURNS=100`，Bridge 又始终向 SDK 下发 `maxTurns`。健康且持续工作的复杂审计因此仍会在第 101 turn 被硬终止，相当于用 Turn 数重新引入隐藏的总执行上限。

## 修复决策

- `JIANGHU_CLAUDE_MAX_TURNS` 改为显式 opt-in；缺失、0、负数或非法值均表示不设置硬 Turn 上限。
- Python Runtime 仅在获得正整数配置时才把 `max_turns` 放入 Bridge payload。
- Node Bridge 仅在正整数配置存在时才设置 SDK `options.maxTurns`；不再回退到隐式 20 turns。
- `scripts/start-real-api.ps1` 默认 `ClaudeMaxTurns=0`，并清除继承的旧环境变量；启动结果以 `null` 表示未启用。
- 不移除 Token/成本预算、Tool 命令超时、人工取消、Provider 错误处理和 heartbeat 不活动检测。健康任务可以持续运行，真正失去心跳的 Bridge 仍会被清理并进入可审计重试。

## 验证

```text
python -m pytest server/tests/runtime_contract/test_runtime_execution_safety.py server/tests/runtime_contract/test_claude_code_runtime_contract.py -q
48 passed, 1 third-party warning

npm --prefix server/claude_agent_runtime test
8 passed, 0 failed

python -m compileall -q server/app server/tests/runtime_contract
exit_code=0
```

新增合同覆盖默认不设置、0/非法值不设置，以及部署显式配置正整数时精确传递。

## 真实 Run 加载结果

旧进程中的安全角色第二次回合最终再次出现 `max_turns_reached`，平台于 sequence 62590 写入人物失败、62591 写入节点整体重试。此时旧 Bridge 已全部退出。平台暂停请求已于 sequence 62608 持久化 Checkpoint；受控重启后启动器明确返回 `ClaudeMaxTurns=null`，Runtime 健康仍为 `claude_code / agent-sdk-bridge / 0.3.268`。

同一 `run_bda13e93b2ea` Version 9 在 paused 边界 resume，sequence 62763 创建 epoch31 不可变 Attempt。五个不带默认 `maxTurns` 的新 Bridge 于 23:07～23:08 启动，事件随后增长到至少 62986。该结果证明修复已经进入真实运行进程，不是只停留在单元测试；最终是否完成仍由后续角色、Judge、Gate 和 Run 终态裁决。
