import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

import { createSdkMcpServer, query, tool } from '@anthropic-ai/claude-agent-sdk';
import { z } from 'zod';

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

let mcpHandlerCalls = 0;
const probeServer = createSdkMcpServer({
  name: 'probe',
  version: '1.0.0',
  tools: [
    tool('marker', 'Return the deterministic MCP probe marker.', {}, async () => {
      mcpHandlerCalls += 1;
      return { content: [{ type: 'text', text: 'MCP_OK' }] };
    }),
  ],
});

const toolNames = [];
let childFrames = 0;
let transcript = '';
let initTools = [];
let result = null;
let error = null;
const stream = query({
  prompt: [
    'First call the MCP tool mcp__probe__marker.',
    'Then invoke the probe-child Agent exactly once.',
    'Finally reply with EXTENSIONS_OK, MCP_OK, and CHILD_OK.',
  ].join('\n'),
  options: {
    agents: {
      'probe-child': {
        description: 'A deterministic child used only by the G3 migration probe.',
        prompt: 'Reply with exactly CHILD_OK. Do not use tools.',
        tools: [],
        model: process.env.PROBE_MODEL,
        maxTurns: 1,
      },
    },
    allowedTools: ['Agent', 'mcp__probe__marker'],
    cwd: workspace,
    env: safeEnv,
    maxTurns: 5,
    mcpServers: { probe: probeServer },
    model: process.env.PROBE_MODEL,
    permissionMode: 'dontAsk',
    permissionPrompts: 'none',
    persistSession: false,
    settingSources: [],
    tools: ['Agent'],
  },
});
try {
  for await (const message of stream) {
    transcript += JSON.stringify(message);
    if (message.parent_tool_use_id) childFrames += 1;
    if (message.type === 'system' && message.subtype === 'init') initTools = message.tools || [];
    const content = message?.message?.content;
    if (Array.isArray(content)) {
      for (const block of content) {
        if (block?.type === 'tool_use') toolNames.push(String(block.name || ''));
      }
    }
    if (message.type === 'result') {
      result = {
        is_error: Boolean(message.is_error),
        terminal_reason: message.terminal_reason ?? null,
        text: typeof message.result === 'string' ? message.result : '',
        usage: message.usage
          ? { input_tokens: message.usage.input_tokens ?? null, output_tokens: message.usage.output_tokens ?? null }
          : null,
      };
    }
  }
} catch (caught) {
  error = { name: String(caught?.name || 'Error'), message_code: String(caught?.message || '').slice(0, 300) };
} finally {
  stream.close();
}

const finalText = result?.text || '';
const output = {
  schema_version: 1,
  probe: 'mcp-and-controlled-subagent',
  status:
    !error &&
    mcpHandlerCalls === 1 &&
    toolNames.includes('mcp__probe__marker') &&
    toolNames.includes('Agent') &&
    transcript.includes('CHILD_OK') &&
    finalText.includes('EXTENSIONS_OK')
      ? 'passed'
      : 'failed',
  init_has_mcp_tool: initTools.includes('mcp__probe__marker'),
  init_has_agent_tool: initTools.includes('Agent'),
  mcp_handler_calls: mcpHandlerCalls,
  tool_names: toolNames,
  child_frame_count: childFrames,
  child_marker_seen: transcript.includes('CHILD_OK'),
  final_markers_present: finalText.includes('EXTENSIONS_OK') && finalText.includes('MCP_OK') && finalText.includes('CHILD_OK'),
  terminal_reason: result?.terminal_reason ?? null,
  usage: result?.usage ?? null,
  error,
};
process.stdout.write(`${JSON.stringify(output, null, 2)}\n`);
