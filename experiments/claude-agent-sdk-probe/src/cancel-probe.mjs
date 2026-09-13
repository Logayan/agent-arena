import { execFileSync } from 'node:child_process';
import { mkdirSync, renameSync } from 'node:fs';
import { resolve } from 'node:path';

import { query } from '@anthropic-ai/claude-agent-sdk';

const required = ['PROBE_BASE_URL', 'PROBE_MODEL', 'PROBE_TOKEN', 'PROBE_WORKSPACE', 'PROBE_CONFIG_DIR'];
for (const key of required) {
  if (!process.env[key]) throw new Error(`missing_${key.toLowerCase()}`);
}

const workspace = resolve(process.env.PROBE_WORKSPACE);
const configDir = resolve(process.env.PROBE_CONFIG_DIR);
mkdirSync(workspace, { recursive: true });
mkdirSync(configDir, { recursive: true });
const safeEnv = {
  PATH: process.env.PATH,
  SystemRoot: process.env.SystemRoot,
  ComSpec: process.env.ComSpec,
  TEMP: process.env.TEMP,
  TMP: process.env.TMP,
  USERPROFILE: process.env.USERPROFILE,
  APPDATA: process.env.APPDATA,
  LOCALAPPDATA: process.env.LOCALAPPDATA,
  CLAUDE_CONFIG_DIR: configDir,
  ANTHROPIC_BASE_URL: process.env.PROBE_BASE_URL,
  ANTHROPIC_API_KEY: process.env.PROBE_TOKEN,
  ANTHROPIC_AUTH_TOKEN: process.env.PROBE_TOKEN,
  ANTHROPIC_DEFAULT_SONNET_MODEL: process.env.PROBE_MODEL,
  CLAUDE_AGENT_SDK_CLIENT_APP: 'jianghu-g3-probe/0.1',
  CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: '1',
  CLAUDE_CODE_ENABLE_PROMPT_SUGGESTION: 'false',
  DISABLE_TELEMETRY: '1',
};

function claudeProcessCount() {
  try {
    const output = execFileSync('tasklist.exe', ['/FI', 'IMAGENAME eq claude.exe', '/FO', 'CSV', '/NH'], { encoding: 'utf8' });
    return output.split(/\r?\n/).filter((line) => line.toLowerCase().includes('claude.exe')).length;
  } catch {
    return null;
  }
}

const beforeCount = claudeProcessCount();
const abortController = new AbortController();
let abortRequested = false;
let toolCallSeen = false;
let resultSeen = false;
let error = null;
const started = Date.now();
const fallbackAbort = setTimeout(() => {
  abortRequested = true;
  abortController.abort('cancel_probe_deadline');
}, 10000);
const stream = query({
  prompt: 'Use Bash to run: powershell -NoProfile -Command "Start-Sleep -Seconds 12". Do not do anything else.',
  options: {
    abortController,
    allowedTools: ['Bash'],
    cwd: workspace,
    env: safeEnv,
    maxTurns: 2,
    model: process.env.PROBE_MODEL,
    permissionMode: 'dontAsk',
    permissionPrompts: 'none',
    persistSession: false,
    settingSources: [],
    tools: ['Bash'],
  },
});

try {
  for await (const message of stream) {
    const content = message?.message?.content;
    if (Array.isArray(content) && content.some((block) => block?.type === 'tool_use' && block?.name === 'Bash')) {
      toolCallSeen = true;
      if (!abortRequested) {
        abortRequested = true;
        setTimeout(() => abortController.abort('cancel_after_tool_call'), 500);
      }
    }
    if (message.type === 'result') resultSeen = true;
  }
} catch (caught) {
  error = { name: String(caught?.name || 'Error'), message_code: String(caught?.message || '').slice(0, 200) };
} finally {
  clearTimeout(fallbackAbort);
  stream.close();
}
await new Promise((resolvePromise) => setTimeout(resolvePromise, 1500));
const afterCount = claudeProcessCount();
const elapsedMs = Date.now() - started;
let workspaceHandleReleased = false;
try {
  const renamed = `${workspace}-released`;
  renameSync(workspace, renamed);
  renameSync(renamed, workspace);
  workspaceHandleReleased = true;
} catch {
  workspaceHandleReleased = false;
}
const output = {
  schema_version: 1,
  probe: 'cancel-and-cleanup',
  status:
    abortRequested &&
    elapsedMs < 25000 &&
    workspaceHandleReleased &&
    (beforeCount === null || afterCount === null || afterCount <= beforeCount)
      ? 'passed'
      : 'failed',
  abort_requested: abortRequested,
  tool_call_seen: toolCallSeen,
  result_seen: resultSeen,
  elapsed_ms: elapsedMs,
  claude_process_count_before: beforeCount,
  claude_process_count_after: afterCount,
  process_count_recovered: beforeCount === null || afterCount === null ? null : afterCount <= beforeCount,
  workspace_handle_released: workspaceHandleReleased,
  error,
};
process.stdout.write(`${JSON.stringify(output, null, 2)}\n`);
