import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';

import { query } from '@anthropic-ai/claude-agent-sdk';

const required = ['PROBE_BASE_URL', 'PROBE_MODEL', 'PROBE_TOKEN', 'PROBE_WORKSPACE', 'PROBE_CONFIG_DIR'];
for (const key of required) {
  if (!process.env[key]) throw new Error(`missing_${key.toLowerCase()}`);
}

const workspace = resolve(process.env.PROBE_WORKSPACE);
const configDir = resolve(process.env.PROBE_CONFIG_DIR);
const skillDir = join(workspace, '.claude', 'skills', 'probe-skill');
mkdirSync(skillDir, { recursive: true });
mkdirSync(configDir, { recursive: true });
writeFileSync(join(workspace, 'CLAUDE.md'), 'For this probe, every final answer must include CLAUDE_MD_OK.\n', 'utf8');
writeFileSync(join(workspace, 'input.txt'), 'INPUT_OK\n', 'utf8');
writeFileSync(
  join(skillDir, 'SKILL.md'),
  '---\nname: probe-skill\ndescription: Adds a deterministic marker for the SDK migration probe.\n---\nWhen invoked, include SKILL_OK in the final answer and in output.txt.\n',
  'utf8',
);

const token = process.env.PROBE_TOKEN;
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
  ANTHROPIC_API_KEY: token,
  ANTHROPIC_AUTH_TOKEN: token,
  ANTHROPIC_DEFAULT_SONNET_MODEL: process.env.PROBE_MODEL,
  CLAUDE_AGENT_SDK_CLIENT_APP: 'jianghu-g3-probe/0.1',
  CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: '1',
  CLAUDE_CODE_ENABLE_PROMPT_SUGGESTION: 'false',
  DISABLE_TELEMETRY: '1',
};

function toolBlocks(message) {
  const content = message?.message?.content;
  return Array.isArray(content) ? content.filter((block) => block?.type === 'tool_use' || block?.type === 'tool_result') : [];
}

async function consume(prompt, extraOptions = {}) {
  const events = [];
  const tools = [];
  let init = null;
  let result = null;
  let sessionId = null;
  let serializedToolResults = '';
  const stream = query({
    prompt,
    options: {
      cwd: workspace,
      env: safeEnv,
      includePartialMessages: true,
      maxTurns: 12,
      model: process.env.PROBE_MODEL,
      permissionMode: 'dontAsk',
      permissionPrompts: 'none',
      persistSession: true,
      ...extraOptions,
    },
  });
  try {
    for await (const message of stream) {
      events.push(message.subtype ? `${message.type}:${message.subtype}` : message.type);
      sessionId ||= message.session_id || null;
      if (message.type === 'system' && message.subtype === 'init') {
        init = {
          model: message.model,
          tools: message.tools,
          skills: message.skills,
          permission_mode: message.permissionMode,
        };
      }
      for (const block of toolBlocks(message)) {
        if (block.type === 'tool_use') {
          tools.push({ kind: 'tool_call', name: String(block.name || ''), id: String(block.id || '') });
        } else {
          tools.push({ kind: 'tool_result', id: String(block.tool_use_id || ''), is_error: Boolean(block.is_error) });
          serializedToolResults += JSON.stringify(block);
        }
      }
      if (message.type === 'result') {
        result = {
          subtype: message.subtype,
          is_error: Boolean(message.is_error),
          terminal_reason: message.terminal_reason ?? null,
          num_turns: message.num_turns ?? null,
          result_text: typeof message.result === 'string' ? message.result : '',
          usage: message.usage
            ? { input_tokens: message.usage.input_tokens ?? null, output_tokens: message.usage.output_tokens ?? null }
            : null,
        };
      }
    }
  } finally {
    stream.close();
  }
  if (token && serializedToolResults.includes(token)) throw new Error('tool_result_contains_token');
  return {
    events,
    tools,
    init,
    result,
    session_id: sessionId,
    bash_marker_seen: serializedToolResults.includes('CLAUDE_BASH_OK'),
    api_key_visible_to_bash: serializedToolResults.includes('KEY_VISIBLE'),
    api_key_hidden_from_bash: serializedToolResults.includes('KEY_HIDDEN'),
  };
}

const nonce = 'RESUME_G3_9C72';
let first;
let resumed;
let error = null;
try {
  first = await consume(
    [
      'Use the probe-skill skill and remember the nonce RESUME_G3_9C72 for the next turn.',
      'You must perform all steps using tools, in this order:',
      '1. Read input.txt.',
      '2. Write output.txt with exactly CLAUDE_MD_OK|SKILL_OK|INPUT_OK followed by a newline.',
      '3. Edit output.txt, replacing INPUT_OK with EDIT_OK.',
      '4. Use Bash to run: echo CLAUDE_BASH_OK',
      '5. Use Bash to run: if [ -n "$ANTHROPIC_API_KEY" ]; then echo KEY_VISIBLE; else echo KEY_HIDDEN; fi',
      'Then reply with FEATURE_DONE, CLAUDE_MD_OK, SKILL_OK, and the nonce.',
    ].join('\n'),
    {
      allowedTools: ['Read', 'Write', 'Edit', 'Bash'],
      settingSources: ['project'],
      skills: ['probe-skill'],
      tools: ['Read', 'Write', 'Edit', 'Bash'],
    },
  );
  resumed = await consume('What nonce did I ask you to remember? Reply with exactly the nonce.', {
    allowedTools: [],
    maxTurns: 1,
    resume: first.session_id,
    settingSources: [],
    tools: [],
  });
} catch (caught) {
  error = { name: String(caught?.name || 'Error'), message_code: String(caught?.message || '').slice(0, 300) };
}

let outputContent = null;
try {
  outputContent = readFileSync(join(workspace, 'output.txt'), 'utf8');
} catch {
  outputContent = null;
}
const toolNames = first?.tools.filter((item) => item.kind === 'tool_call').map((item) => item.name) || [];
const result = {
  schema_version: 1,
  probe: 'features-and-resume',
  status:
    !error &&
    outputContent === 'CLAUDE_MD_OK|SKILL_OK|EDIT_OK\n' &&
    ['Read', 'Write', 'Edit', 'Bash'].every((name) => toolNames.includes(name)) &&
    first?.bash_marker_seen &&
    resumed?.result?.result_text?.trim() === nonce
      ? 'passed'
      : 'failed',
  feature: first
    ? {
        init: first.init,
        event_count: first.events.length,
        tool_event_count: first.tools.length,
        tool_names: toolNames,
        tool_results_before_result: first.events.lastIndexOf('user') < first.events.lastIndexOf('result:success'),
        output_file_exact: outputContent === 'CLAUDE_MD_OK|SKILL_OK|EDIT_OK\n',
        bash_marker_seen: first.bash_marker_seen,
        api_key_visible_to_bash: first.api_key_visible_to_bash,
        api_key_hidden_from_bash: first.api_key_hidden_from_bash,
        final_markers_present:
          Boolean(first.result?.result_text?.includes('FEATURE_DONE')) &&
          Boolean(first.result?.result_text?.includes('CLAUDE_MD_OK')) &&
          Boolean(first.result?.result_text?.includes('SKILL_OK')),
        usage: first.result?.usage ?? null,
      }
    : null,
  resume: resumed
    ? {
        session_id_reused: resumed.session_id === first.session_id,
        nonce_exact: resumed.result?.result_text?.trim() === nonce,
        terminal_reason: resumed.result?.terminal_reason ?? null,
        usage: resumed.result?.usage ?? null,
      }
    : null,
  error,
};
process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
