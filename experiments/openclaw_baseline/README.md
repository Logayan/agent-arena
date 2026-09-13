# Frozen OpenClaw migration baseline

This directory preserves the pre-cutover OpenClaw adapter only for capability
capture and Claude Code SDK parity regression. It is deliberately outside the
`server.app` package and is not a product Runtime option.

Production invariants:

- `server.app.agent_runtime_registry` constructs only `ClaudeCodeRuntime`;
- `JIANGHU_AGENT_RUNTIME` accepts only `claude_code`;
- product startup, Run execution, deployment, and failover never import this
  package;
- `/api/platform/openclaw/status` and `openclaw.*` event mappings are read-only
  compatibility surfaces for historical clients and data;
- rollback uses a previous release artifact, not an in-process OpenClaw switch.

The legacy class names and protocol strings remain unchanged so frozen baseline
hashes, fixtures, and direct parity tests remain intelligible.
