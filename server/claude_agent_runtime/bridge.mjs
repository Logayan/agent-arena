import { spawn, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, lstatSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, isAbsolute, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { createSdkMcpServer, query, tool } from '@anthropic-ai/claude-agent-sdk';
import { z } from 'zod';

const here = dirname(fileURLToPath(import.meta.url));
const activeChildren = new Set();
let activeQuery = null;
let providerToken = '';

function emit(value) {
  process.stdout.write(`${JSON.stringify(value)}\n`);
}

export function heartbeatIntervalMs(value) {
  const seconds = Number(value || 15);
  if (!Number.isFinite(seconds)) return 15_000;
  return Math.max(1_000, Math.min(60_000, Math.round(seconds * 1_000)));
}

function redact(value) {
  if (Array.isArray(value)) return value.map(redact);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [
        key,
        /(key|token|secret|password|auth|credential)/i.test(key) ? '[REDACTED]' : redact(item),
      ]),
    );
  }
  if (typeof value !== 'string') return value;
  let text = providerToken ? value.split(providerToken).join('[REDACTED]') : value;
  text = text.replace(/(api[_-]?key|token|secret|password|authorization)(\s*[=:]\s*)[^\s"']+/gi, '$1$2[REDACTED]');
  return text.length > 100000 ? `${text.slice(0, 100000)}…` : text;
}

function publicError(error) {
  return {
    name: String(error?.name || 'Error'),
    message: redact(String(error?.message || error || 'unknown_error')).slice(0, 2000),
  };
}

export function applyOptionalMaxTurns(options, configuredValue) {
  const value = Number(configuredValue);
  if (Number.isFinite(value) && value > 0) options.maxTurns = Math.floor(value);
  return options;
}

function normalizeToolName(name) {
  const value = String(name || 'unknown');
  const suffix = value.split('__').at(-1)?.toLowerCase();
  return { read: 'Read', write: 'Write', edit: 'Edit', bash: 'Bash' }[suffix] || value;
}

function stripDeliveryPrefix(value) {
  return String(value || '').replace(/^[.\\/]*(delivery)[\\/]+/i, '');
}

function inside(root, candidate) {
  const rel = relative(root, candidate);
  return rel === '' || (!rel.startsWith('..') && !isAbsolute(rel));
}

function rejectSymlinkSegments(root, candidate) {
  const rel = relative(root, candidate);
  let current = root;
  for (const segment of rel.split(/[\\/]+/).filter(Boolean)) {
    current = resolve(current, segment);
    if (existsSync(current) && lstatSync(current).isSymbolicLink()) {
      throw new Error('workspace_symlink_not_allowed');
    }
  }
}

function resolveInside(root, rawPath, { deliveryPrefix = false } = {}) {
  const input = deliveryPrefix ? stripDeliveryPrefix(rawPath) : String(rawPath || '');
  if (!input || input.includes('\0')) throw new Error('workspace_path_required');
  const candidate = resolve(root, input);
  if (!inside(root, candidate)) throw new Error('workspace_path_not_allowed');
  rejectSymlinkSegments(root, candidate);
  return candidate;
}

function sanitizedToolEnvironment() {
  const allowed = new Set([
    'PATH', 'Path', 'SYSTEMROOT', 'SystemRoot', 'COMSPEC', 'ComSpec', 'PATHEXT', 'TEMP', 'TMP',
    'APPDATA', 'LOCALAPPDATA', 'PROGRAMFILES', 'PROGRAMFILES(X86)', 'PROGRAMDATA', 'USERPROFILE',
    'HOMEDRIVE', 'HOMEPATH', 'OS', 'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'WINDIR',
    'LANG', 'LC_ALL', 'TERM', 'SHELL',
  ]);
  const output = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (!allowed.has(key) || value === undefined) continue;
    if (/(key|token|secret|password|auth|credential)/i.test(key)) continue;
    output[key] = value;
  }
  output.JIANGHU_TOOL_ENV = 'isolated';
  return output;
}

export function workspaceToolEnvironment(delivery, platform = process.platform) {
  const output = sanitizedToolEnvironment();
  const absoluteDelivery = resolve(delivery);
  output.LANG = 'C.UTF-8';
  output.LC_ALL = 'C.UTF-8';
  output.PYTHONIOENCODING = 'utf-8';
  output.PYTHONUTF8 = '1';
  const windowsDrive = /^([A-Za-z]):[\\/](.*)$/.exec(absoluteDelivery);
  output.GIT_CEILING_DIRECTORIES = platform === 'win32' && windowsDrive
    ? `/${windowsDrive[1].toLowerCase()}/${windowsDrive[2].replaceAll('\\', '/')}`
    : absoluteDelivery;
  output.GIT_DISCOVERY_ACROSS_FILESYSTEM = '0';
  output.GIT_CONFIG_NOSYSTEM = '1';
  output.GIT_CONFIG_GLOBAL = platform === 'win32' ? 'NUL' : '/dev/null';
  output.GIT_DIR = resolve(absoluteDelivery, '.git');
  output.GIT_WORK_TREE = absoluteDelivery;
  return output;
}

export function commandHasPathEscape(command) {
  const value = String(command || '');
  if (/(^|[\s"'])\.\.[\\/]/.test(value)) return true;
  if (/(^|[\s"'=])\.\.($|[\s"'\\/])/.test(value)) return true;
  if (/\$env:|\$HOME|~[\\/]/i.test(value)) return true;
  // Windows variable names in the sanitized environment are at least three
  // characters. Requiring that length avoids treating strftime fragments such
  // as `%dT%` in `date -u +%Y-%m-%dT%H:%M:%SZ` as path expansion.
  if (/%[A-Z_][A-Z0-9_]{2,}%/i.test(value)) return true;
  if (/[A-Za-z]:[\\/]/.test(value)) return true;
  if (/(^|[\s"'])\/[A-Za-z](?:[\\/]|$)/.test(value)) return true;
  if (/(^|[\s"'])\/(etc|home|root|var|usr|opt|proc|sys|dev)([\\/\s"']|$)/i.test(value)) return true;
  return false;
}

export function commandShell(command, platform = process.platform, environment = process.env, pathExists = existsSync) {
  if (platform !== 'win32') return { executable: '/bin/bash', args: ['-lc', command], kind: 'bash' };
  const candidates = [
    environment.JIANGHU_CLAUDE_BASH_PATH,
    environment.ProgramFiles ? `${environment.ProgramFiles}\\Git\\bin\\bash.exe` : '',
    environment['ProgramFiles(x86)'] ? `${environment['ProgramFiles(x86)']}\\Git\\bin\\bash.exe` : '',
    environment.LOCALAPPDATA ? `${environment.LOCALAPPDATA}\\Programs\\Git\\bin\\bash.exe` : '',
  ].filter(Boolean);
  const executable = candidates.find((candidate) => pathExists(candidate));
  if (!executable) throw new Error('claude_bash_runtime_not_found');
  return { executable, args: ['--noprofile', '--norc', '-lc', command], kind: 'git-bash' };
}

function killProcessTree(child) {
  if (!child?.pid) return;
  try {
    if (process.platform === 'win32') {
      spawnSync('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
    } else {
      process.kill(-child.pid, 'SIGKILL');
    }
  } catch {
    try { child.kill('SIGKILL'); } catch { /* best effort */ }
  }
}

function stopEverything() {
  try { activeQuery?.close(); } catch { /* best effort */ }
  for (const child of activeChildren) killProcessTree(child);
}

process.on('SIGTERM', () => {
  stopEverything();
  setTimeout(() => process.exit(143), 50).unref();
});
process.on('SIGINT', () => {
  stopEverything();
  setTimeout(() => process.exit(130), 50).unref();
});

async function readStdinJson() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString('utf8');
  return JSON.parse(raw);
}

function health() {
  const packagePath = resolve(here, 'node_modules', '@anthropic-ai', 'claude-agent-sdk', 'package.json');
  const packageData = JSON.parse(readFileSync(packagePath, 'utf8'));
  const key = `${process.platform}-${process.arch}`;
  const binary = resolve(here, 'node_modules', '@anthropic-ai', `claude-agent-sdk-${key}`, process.platform === 'win32' ? 'claude.exe' : 'claude');
  return {
    available: existsSync(binary),
    runtime: 'claude_code',
    mode: 'agent-sdk-bridge',
    version: packageData.version,
    claude_code_version: packageData.claudeCodeVersion,
    node: process.version,
    platform: process.platform,
    arch: process.arch,
    binary_present: existsSync(binary),
  };
}

function mcpResult(payload, isError = false) {
  const serialized = JSON.stringify(redact(payload));
  return {
    content: [{ type: 'text', text: serialized }],
    structuredContent: redact(payload),
    isError,
  };
}

function workspaceServer(workspace, delivery, commandTimeoutSeconds) {
  const readTool = tool(
    'read',
    'Read a UTF-8 text file inside the current Agent workspace.',
    { path: z.string(), offset: z.number().int().nonnegative().optional(), limit: z.number().int().positive().max(200000).optional() },
    async ({ path, offset = 0, limit = 100000 }) => {
      try {
        const target = resolveInside(workspace, path);
        const text = readFileSync(target, 'utf8');
        return mcpResult({ path: relative(workspace, target).replaceAll('\\', '/'), content: text.slice(offset, offset + limit) });
      } catch (error) {
        return mcpResult({ error: publicError(error).message }, true);
      }
    },
  );
  const writeTool = tool(
    'write',
    'Write a UTF-8 file inside delivery/. Paths may optionally begin with delivery/.',
    { path: z.string(), content: z.string() },
    async ({ path, content }) => {
      try {
        const target = resolveInside(delivery, path, { deliveryPrefix: true });
        mkdirSync(dirname(target), { recursive: true });
        rejectSymlinkSegments(delivery, target);
        writeFileSync(target, content, 'utf8');
        return mcpResult({ path: relative(delivery, target).replaceAll('\\', '/'), bytes: Buffer.byteLength(content, 'utf8') });
      } catch (error) {
        return mcpResult({ error: publicError(error).message }, true);
      }
    },
  );
  const editTool = tool(
    'edit',
    'Replace exact text in a UTF-8 file inside delivery/.',
    { path: z.string(), old_text: z.string(), new_text: z.string(), replace_all: z.boolean().optional() },
    async ({ path, old_text, new_text, replace_all = false }) => {
      try {
        if (!old_text) throw new Error('edit_old_text_required');
        const target = resolveInside(delivery, path, { deliveryPrefix: true });
        const original = readFileSync(target, 'utf8');
        const count = original.split(old_text).length - 1;
        if (count === 0) throw new Error('edit_text_not_found');
        if (!replace_all && count !== 1) throw new Error('edit_text_not_unique');
        const updated = replace_all ? original.split(old_text).join(new_text) : original.replace(old_text, new_text);
        writeFileSync(target, updated, 'utf8');
        return mcpResult({ path: relative(delivery, target).replaceAll('\\', '/'), replacements: replace_all ? count : 1 });
      } catch (error) {
        return mcpResult({ error: publicError(error).message }, true);
      }
    },
  );
  const bashTool = tool(
    'bash',
    'Run a build, test, inspection, or development command inside delivery/ with provider credentials removed.',
    { command: z.string(), timeout_seconds: z.number().int().positive().max(commandTimeoutSeconds).optional() },
    async ({ command, timeout_seconds = commandTimeoutSeconds }) => {
      if (commandHasPathEscape(command)) return mcpResult({ error: 'command_path_not_allowed' }, true);
      let shell;
      try {
        shell = commandShell(command);
      } catch (error) {
        return mcpResult({ error: publicError(error).message }, true);
      }
      return await new Promise((resolvePromise) => {
        const child = spawn(shell.executable, shell.args, {
          cwd: delivery,
          env: workspaceToolEnvironment(delivery),
          detached: process.platform !== 'win32',
          windowsHide: true,
          stdio: ['ignore', 'pipe', 'pipe'],
        });
        activeChildren.add(child);
        const stdout = [];
        const stderr = [];
        let outputBytes = 0;
        const collect = (destination) => (chunk) => {
          if (outputBytes >= 200000) return;
          const buffer = Buffer.from(chunk);
          destination.push(buffer.subarray(0, Math.max(0, 200000 - outputBytes)));
          outputBytes += buffer.length;
        };
        child.stdout.on('data', collect(stdout));
        child.stderr.on('data', collect(stderr));
        let timedOut = false;
        const timer = setTimeout(() => {
          timedOut = true;
          killProcessTree(child);
        }, Math.max(1, timeout_seconds) * 1000);
        child.on('error', (error) => {
          clearTimeout(timer);
          activeChildren.delete(child);
          resolvePromise(mcpResult({ error: publicError(error).message }, true));
        });
        child.on('close', (code) => {
          clearTimeout(timer);
          activeChildren.delete(child);
          const payload = {
            status: timedOut ? 'timeout' : (code === 0 ? 'completed' : 'failed'),
            exit_code: code,
            stdout: Buffer.concat(stdout).toString('utf8'),
            stderr: Buffer.concat(stderr).toString('utf8'),
            cwd: '.',
            shell: shell.kind,
            environment: 'credential-isolated',
          };
          resolvePromise(mcpResult(payload, timedOut || code !== 0));
        });
      });
    },
  );
  return createSdkMcpServer({ name: 'jianghu_workspace', version: '1.0.0', tools: [readTool, writeTool, editTool, bashTool] });
}

function blockOutput(block, toolUseResult) {
  if (toolUseResult !== undefined) return redact(toolUseResult);
  if (typeof block?.content === 'string') return redact(block.content);
  if (Array.isArray(block?.content)) {
    return redact(block.content.map((item) => item?.text || JSON.stringify(item)).join('\n'));
  }
  return redact(block?.content || '');
}

function parseJsonObject(value) {
  if (typeof value !== 'string') return null;
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch {
    return null;
  }
}

export function normalizedToolResult(block, toolUseResult, toolName = '') {
  let payload = toolUseResult;
  if (payload && typeof payload === 'object' && payload.structuredContent && typeof payload.structuredContent === 'object') {
    payload = payload.structuredContent;
  } else if (payload && typeof payload === 'object' && typeof payload.content === 'string') {
    payload = parseJsonObject(payload.content) || payload.content;
  } else if (typeof payload === 'string') {
    payload = parseJsonObject(payload) || payload;
  } else if (payload === undefined) {
    const blockContent = typeof block?.content === 'string' ? block.content : '';
    payload = parseJsonObject(blockContent) || blockOutput(block, undefined);
  }
  const publicPayload = redact(payload);
  const payloadStatus = publicPayload && typeof publicPayload === 'object' ? String(publicPayload.status || '') : '';
  const isError = Boolean(block?.is_error) || ['failed', 'timeout', 'error'].includes(payloadStatus.toLowerCase());
  return {
    kind: 'tool_result',
    tool_call_id: String(block?.tool_use_id || ''),
    tool_name: normalizeToolName(toolName),
    output: typeof publicPayload === 'string' ? publicPayload : JSON.stringify(publicPayload),
    is_error: isError,
    status: payloadStatus || (isError ? 'failed' : 'completed'),
    exit_code: publicPayload && typeof publicPayload === 'object'
      ? (publicPayload.exit_code ?? publicPayload.exitCode ?? null)
      : null,
    cwd: publicPayload && typeof publicPayload === 'object' ? String(publicPayload.cwd || '') : '',
    shell: publicPayload && typeof publicPayload === 'object' ? String(publicPayload.shell || '') : '',
    environment: publicPayload && typeof publicPayload === 'object' ? String(publicPayload.environment || '') : '',
    timestamp: new Date().toISOString(),
  };
}

async function main() {
  if (process.argv.includes('--health')) {
    emit(health());
    return;
  }
  const input = await readStdinJson();
  providerToken = String(input.token || '');
  const workspace = resolve(String(input.workspace));
  const delivery = resolve(workspace, 'delivery');
  const configDir = resolve(String(input.config_dir));
  mkdirSync(delivery, { recursive: true });
  mkdirSync(configDir, { recursive: true });
  const engineering = Boolean(input.engineering);
  const skillIds = Array.isArray(input.skill_ids) ? input.skill_ids.map(String) : [];
  const toolNames = engineering
    ? ['mcp__jianghu_workspace__read', 'mcp__jianghu_workspace__write', 'mcp__jianghu_workspace__edit', 'mcp__jianghu_workspace__bash']
    : [];
  const cliEnv = {
    PATH: process.env.PATH,
    Path: process.env.Path,
    SystemRoot: process.env.SystemRoot,
    ComSpec: process.env.ComSpec,
    PATHEXT: process.env.PATHEXT,
    TEMP: process.env.TEMP,
    TMP: process.env.TMP,
    USERPROFILE: process.env.USERPROFILE,
    APPDATA: process.env.APPDATA,
    LOCALAPPDATA: process.env.LOCALAPPDATA,
    HOME: process.env.HOME,
    CLAUDE_CONFIG_DIR: configDir,
    ANTHROPIC_BASE_URL: String(input.base_url || '').replace(/\/$/, ''),
    ANTHROPIC_API_KEY: providerToken,
    ANTHROPIC_AUTH_TOKEN: providerToken,
    ANTHROPIC_DEFAULT_SONNET_MODEL: String(input.model || ''),
    CLAUDE_AGENT_SDK_CLIENT_APP: 'jianghu-online/0.1',
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: '1',
    CLAUDE_CODE_ENABLE_PROMPT_SUGGESTION: 'false',
    DISABLE_TELEMETRY: '1',
  };
  const abortController = new AbortController();
  const options = {
    abortController,
    allowedTools: toolNames,
    cwd: workspace,
    env: cliEnv,
    includePartialMessages: false,
    model: String(input.model || ''),
    permissionMode: 'dontAsk',
    permissionPrompts: 'none',
    persistSession: true,
    settingSources: ['project'],
    skills: skillIds,
    tools: [],
  };
  applyOptionalMaxTurns(options, input.max_turns);
  if (engineering) {
    options.mcpServers = { jianghu_workspace: workspaceServer(workspace, delivery, Number(input.command_timeout_seconds || 600)) };
    options.strictMcpConfig = true;
    options.toolAliases = {
      Read: 'mcp__jianghu_workspace__read',
      Write: 'mcp__jianghu_workspace__write',
      Edit: 'mcp__jianghu_workspace__edit',
      Bash: 'mcp__jianghu_workspace__bash',
    };
  }
  if (input.resume_session_id) options.resume = String(input.resume_session_id);
  const prompt = engineering
    ? `${String(input.prompt)}\n\n工程工具约束：只能使用 jianghu_workspace MCP 工具。正式文件必须写入 delivery/；命令固定在 delivery/ 执行。不得尝试读取 Workspace 外路径或 Provider 凭据。`
    : String(input.prompt);

  let finalResult = null;
  const seenActions = new Set();
  const toolNamesById = new Map();
  const heartbeat = setInterval(() => {
    emit({ type: 'heartbeat', timestamp: new Date().toISOString() });
  }, heartbeatIntervalMs(input.heartbeat_interval_seconds));
  heartbeat.unref();
  activeQuery = query({ prompt, options });
  try {
    for await (const message of activeQuery) {
      if (message.type === 'system' && message.subtype === 'init') {
        emit({ type: 'meta', session_id: message.session_id, model: message.model, runtime_version: message.claude_code_version });
      }
      const content = message?.message?.content;
      if (Array.isArray(content)) {
        for (const block of content) {
          let action = null;
          if (message.type === 'assistant' && block?.type === 'text' && block.text) {
            action = { kind: 'progress', content: redact(block.text), timestamp: new Date().toISOString() };
          } else if (message.type === 'assistant' && block?.type === 'tool_use') {
            toolNamesById.set(String(block.id || ''), String(block.name || ''));
            action = {
              kind: 'tool_call',
              tool_call_id: String(block.id || ''),
              tool_name: normalizeToolName(block.name),
              arguments: redact(block.input || {}),
              timestamp: new Date().toISOString(),
            };
          } else if (message.type === 'user' && block?.type === 'tool_result') {
            const toolCallId = String(block.tool_use_id || '');
            action = normalizedToolResult(block, message.tool_use_result, toolNamesById.get(toolCallId) || '');
          }
          if (action) {
            const fingerprint = createHash('sha256').update(JSON.stringify(action)).digest('hex');
            if (!seenActions.has(fingerprint)) {
              seenActions.add(fingerprint);
              emit({ type: 'action', action });
            }
          }
        }
      }
      if (message.type === 'result') {
        finalResult = {
          session_id: message.session_id,
          model: String(input.model || ''),
          is_error: Boolean(message.is_error),
          subtype: message.subtype,
          terminal_reason: message.terminal_reason ?? null,
          api_error_status: message.api_error_status ?? null,
          text: redact(typeof message.result === 'string' ? message.result : ''),
          usage: message.usage ? {
            input_tokens: Number(message.usage.input_tokens || 0),
            output_tokens: Number(message.usage.output_tokens || 0),
            cache_read_input_tokens: Number(message.usage.cache_read_input_tokens || 0),
            cache_creation_input_tokens: Number(message.usage.cache_creation_input_tokens || 0),
          } : { input_tokens: 0, output_tokens: 0 },
        };
      }
    }
  } finally {
    clearInterval(heartbeat);
    activeQuery?.close();
    activeQuery = null;
    for (const child of activeChildren) killProcessTree(child);
  }
  if (!finalResult) throw new Error('claude_sdk_result_missing');
  emit({ type: 'result', result: finalResult });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    stopEverything();
    emit({ type: 'error', error: publicError(error) });
    process.exitCode = 1;
  });
}
