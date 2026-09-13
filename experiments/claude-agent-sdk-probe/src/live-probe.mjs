import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

import { query } from '@anthropic-ai/claude-agent-sdk';

const required = ['PROBE_BASE_URL', 'PROBE_MODEL', 'PROBE_TOKEN', 'PROBE_WORKSPACE', 'PROBE_CONFIG_DIR'];
for (const key of required) {
  if (!process.env[key]) {
    throw new Error(`missing_${key.toLowerCase()}`);
  }
}

const workspace = resolve(process.env.PROBE_WORKSPACE);
const configDir = resolve(process.env.PROBE_CONFIG_DIR);
mkdirSync(workspace, { recursive: true });
mkdirSync(configDir, { recursive: true });

const abortController = new AbortController();
const timeoutMs = Number(process.env.PROBE_TIMEOUT_MS || 45000);
const timeout = setTimeout(() => abortController.abort('probe_timeout'), timeoutMs);
const eventCounts = {};
const toolEvents = [];
let init = null;
let resultMessage = null;
let sessionId = null;
let thrown = null;

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

function count(message) {
  const key = message.subtype ? `${message.type}:${message.subtype}` : message.type;
  eventCounts[key] = (eventCounts[key] || 0) + 1;
}

function collectToolBlocks(message) {
  const content = message?.message?.content;
  if (!Array.isArray(content)) return;
  for (const block of content) {
    if (block?.type === 'tool_use') {
      toolEvents.push({ kind: 'tool_call', id: String(block.id || ''), name: String(block.name || '') });
    } else if (block?.type === 'tool_result') {
      toolEvents.push({ kind: 'tool_result', id: String(block.tool_use_id || ''), is_error: Boolean(block.is_error) });
    }
  }
}

try {
  const stream = query({
    prompt: 'Reply with exactly CLAUDE_SDK_ENDPOINT_OK. Do not use tools.',
    options: {
      abortController,
      cwd: workspace,
      env: safeEnv,
      includePartialMessages: true,
      maxTurns: 1,
      model: process.env.PROBE_MODEL,
      permissionMode: 'dontAsk',
      permissionPrompts: 'none',
      persistSession: true,
      settingSources: [],
      tools: [],
    },
  });

  for await (const message of stream) {
    count(message);
    sessionId ||= message.session_id || null;
    if (message.type === 'system' && message.subtype === 'init') {
      init = {
        model: message.model,
        claude_code_version: message.claude_code_version,
        api_key_source: message.apiKeySource,
        permission_mode: message.permissionMode,
        tools: Array.isArray(message.tools) ? message.tools : [],
        skills: Array.isArray(message.skills) ? message.skills : [],
      };
    }
    collectToolBlocks(message);
    if (message.type === 'result') {
      resultMessage = {
        subtype: message.subtype,
        is_error: Boolean(message.is_error),
        api_error_status: message.api_error_status ?? null,
        terminal_reason: message.terminal_reason ?? null,
        num_turns: message.num_turns ?? null,
        duration_ms: message.duration_ms ?? null,
        duration_api_ms: message.duration_api_ms ?? null,
        result_marker_ok: typeof message.result === 'string' && message.result.trim() === 'CLAUDE_SDK_ENDPOINT_OK',
        usage: message.usage
          ? {
              input_tokens: message.usage.input_tokens ?? null,
              output_tokens: message.usage.output_tokens ?? null,
              cache_read_input_tokens: message.usage.cache_read_input_tokens ?? null,
              cache_creation_input_tokens: message.usage.cache_creation_input_tokens ?? null,
            }
          : null,
      };
    }
  }
} catch (error) {
  thrown = {
    name: String(error?.name || 'Error'),
    category: abortController.signal.aborted ? 'timeout_or_cancelled' : 'sdk_exception',
    message_code: String(error?.message || '').slice(0, 300).replace(/https?:\/\/\S+/g, '<url>'),
  };
} finally {
  clearTimeout(timeout);
}

const output = {
  schema_version: 1,
  probe: 'live-minimal',
  status: resultMessage && !resultMessage.is_error && resultMessage.result_marker_ok ? 'passed' : 'failed',
  session_id_present: Boolean(sessionId),
  init,
  result: resultMessage,
  event_counts: eventCounts,
  tool_events: toolEvents,
  error: thrown,
};

process.stdout.write(`${JSON.stringify(output, null, 2)}\n`);
