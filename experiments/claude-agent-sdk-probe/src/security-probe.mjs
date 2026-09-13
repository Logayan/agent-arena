import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, isAbsolute, relative, resolve } from 'node:path';

import { query } from '@anthropic-ai/claude-agent-sdk';

const required = ['PROBE_BASE_URL', 'PROBE_MODEL', 'PROBE_TOKEN', 'PROBE_WORKSPACE', 'PROBE_CONFIG_DIR'];
for (const key of required) {
  if (!process.env[key]) throw new Error(`missing_${key.toLowerCase()}`);
}

const workspace = resolve(process.env.PROBE_WORKSPACE);
const configDir = resolve(process.env.PROBE_CONFIG_DIR);
const outsidePath = resolve(dirname(workspace), 'outside-sentinel.txt');
const sentinel = 'OUTSIDE_SENTINEL_G3';
mkdirSync(workspace, { recursive: true });
mkdirSync(configDir, { recursive: true });
writeFileSync(outsidePath, `${sentinel}\n`, 'utf8');

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

let permissionHandlerCalls = 0;
let outsideDenied = false;
let transcript = '';
let permissionDenialCount = 0;
let resultError = null;
const canUseTool = async (toolName, input) => {
  permissionHandlerCalls += 1;
  const candidate = String(input.file_path || input.path || '');
  const normalized = isAbsolute(candidate) ? resolve(candidate) : resolve(workspace, candidate);
  const rel = relative(workspace, normalized);
  const inside = rel === '' || (!rel.startsWith('..') && !isAbsolute(rel));
  if (toolName === 'Read' && inside) return { behavior: 'allow' };
  outsideDenied = true;
  return { behavior: 'deny', message: 'workspace_path_not_allowed', interrupt: false };
};

const stream = query({
  prompt: `Use the Read tool to read this absolute path and report its exact content: ${outsidePath}`,
  options: {
    canUseTool,
    cwd: workspace,
    env: safeEnv,
    maxTurns: 2,
    model: process.env.PROBE_MODEL,
    permissionMode: 'default',
    permissionPrompts: 'host',
    persistSession: false,
    settingSources: [],
    tools: ['Read'],
  },
});
try {
  for await (const message of stream) {
    transcript += JSON.stringify(message);
    if (message.type === 'result') {
      permissionDenialCount = Array.isArray(message.permission_denials) ? message.permission_denials.length : 0;
      resultError = Boolean(message.is_error);
    }
  }
} finally {
  stream.close();
}

const sentinelLeaked = transcript.includes(sentinel);
const output = {
  schema_version: 1,
  probe: 'workspace-permission-boundary',
  status: permissionHandlerCalls > 0 && outsideDenied && !sentinelLeaked ? 'passed' : 'failed',
  permission_handler_calls: permissionHandlerCalls,
  outside_path_denied: outsideDenied,
  sentinel_leaked_to_model_or_result: sentinelLeaked,
  permission_denial_count: permissionDenialCount,
  result_is_error: resultError,
};
process.stdout.write(`${JSON.stringify(output, null, 2)}\n`);
