# 构建与验证命令账本

**固定 workdir：**

```text
D:\Users\User\My Document\多agent协作与对抗实践\.data\workspaces\project_jianghu\runs\run_6940048dd30f\tmp\claude-agents\agent_cb495a9bea1e\delivery
```

所有命令均由 `jianghu_workspace` MCP 在上述 `delivery/` 根目录执行，Provider credentials 已移除；未读取或输出环境变量、Token、密钥、私有会话或私有 Memory。

## 合并前公开提交调试记录【保留失败】

| 来源 | 命令/阶段 | 退出码 | 事实与处理 |
|---|---|---:|---|
| 程观澜提交 | 首次组合编译、测试、回执 | 5 | 验证器只接受对象式 `strictMcpConfig: true`，未接受生产 bridge 的赋值式 `options.strictMcpConfig = true`。修正正则后不降低 `true` 要求，重跑 9/9 PASS。 |
| 谢临川提交 | 首次一键验收 | 1 | OpenClaw policy probe 锚点错误选中 IAM 矩阵中的 sequence 50。改为按 `tool_call_id=policy-probe:*` 选择独立 sequence 90，重跑 22/22 PASS。 |

以上失败没有被删除，也没有被改写为生产源码失败；它们是各自验证实现的问题。最终包采用一个合并验证器。

## 本节点合议工程命令

| 顺序 | 命令 | 退出码 | 结果 |
|---:|---|---:|---|
| 1 | 内联 Python 读取冻结快照、事件、Registry 及 13 项原始字节 | 0 | 94 条事件、92 critical、13/13 原始字节和十入口事实重新计算通过。 |
| 2 | `python -m py_compile src/verify_mapping.py tests/test_verify_mapping.py` | 0 | Python 语法编译通过。 |
| 3 | `python -m unittest discover -s tests -v` | 0 | **17/17 PASS**，0 failure，0 error，0 skipped；包括篡改快照失败关闭负测。 |
| 4 | `python src/verify_mapping.py --write-receipt` | 0 | `events=94 critical=92 artifacts=13/13 routes=10/10 session_bindings=0 gaps=13 overall=NO_GO`。 |
| 5 | 内联 Python 遍历非平台证据 `*.json` 并执行 `json.loads` | 0 | **JSON PASS files=9**。 |
| 6 | `python src/verify_mapping.py --write-manifest` | 0 | 生成 self-excluding SHA-256 Manifest。 |
| 7 | `python src/verify_mapping.py --check-manifest` | 0 | Manifest 文件集合、字节数和 SHA-256 全部通过。 |
| 8 | `python src/verify_mapping.py` | 0 | 最终只读证据校验通过；迁移裁决保持 `NO_GO`。 |

命令 2—5 的完整原始输出保存在 `evidence/build-test-run.log`。命令 6—8 在最终封包命令中再次执行；若任一步失败，封包命令整体失败关闭。

## 结果解释

`VERIFICATION PASS` 仅表示：

- 冻结证据字节、事件身份、critical correspondence、13 项 Artifact、源码契约、映射、缺口、公开提交审查与失败关闭判定内部自洽；
- 当前包没有把短窗探针、源码路径或公开消息文本误记为完整 Runtime 行为通过。

它不表示：

- completed turn/SDK Session binding 已存在；
- 真实 Tool、Memory、Judge、pause/recovery 或 Run 终态已闭环；
- 本节点候选已被平台登记、采集并下载复算；
- OpenClaw 已达到长期退役条件。
