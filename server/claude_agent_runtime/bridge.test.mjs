import assert from 'node:assert/strict';
import test from 'node:test';

import {
  applyOptionalMaxTurns,
  commandHasPathEscape,
  commandShell,
  heartbeatIntervalMs,
  normalizedToolResult,
  workspaceToolEnvironment,
} from './bridge.mjs';


test('does not impose an SDK turn limit unless explicitly configured', () => {
  assert.deepEqual(applyOptionalMaxTurns({ model: 'gpt-test' }, undefined), { model: 'gpt-test' });
  assert.deepEqual(applyOptionalMaxTurns({ model: 'gpt-test' }, 0), { model: 'gpt-test' });
  assert.deepEqual(applyOptionalMaxTurns({ model: 'gpt-test' }, 'invalid'), { model: 'gpt-test' });
  assert.deepEqual(applyOptionalMaxTurns({ model: 'gpt-test' }, 250), {
    model: 'gpt-test',
    maxTurns: 250,
  });
});


test('bounds the internal bridge heartbeat without imposing a turn deadline', () => {
  assert.equal(heartbeatIntervalMs(undefined), 15_000);
  assert.equal(heartbeatIntervalMs(0.1), 1_000);
  assert.equal(heartbeatIntervalMs(12.5), 12_500);
  assert.equal(heartbeatIntervalMs(120), 60_000);
  assert.equal(heartbeatIntervalMs('invalid'), 15_000);
});


test('normalizes MCP structured command results with tool name and exit code', () => {
  const action = normalizedToolResult(
    { tool_use_id: 'call-1', type: 'tool_result', is_error: false },
    {
      content: '{"status":"completed","exit_code":0,"stdout":"RUNTIME_PARITY_OK"}',
      structuredContent: {
        status: 'completed',
        exit_code: 0,
        stdout: 'RUNTIME_PARITY_OK',
        stderr: '',
        cwd: '.',
        shell: 'git-bash',
        environment: 'credential-isolated',
      },
    },
    'mcp__jianghu_workspace__bash',
  );

  assert.equal(action.kind, 'tool_result');
  assert.equal(action.tool_call_id, 'call-1');
  assert.equal(action.tool_name, 'Bash');
  assert.equal(action.status, 'completed');
  assert.equal(action.is_error, false);
  assert.equal(action.exit_code, 0);
  assert.equal(action.cwd, '.');
  assert.equal(action.shell, 'git-bash');
  assert.equal(action.environment, 'credential-isolated');
  assert.match(action.output, /RUNTIME_PARITY_OK/);
});


test('normalizes string MCP results and failed status', () => {
  const action = normalizedToolResult(
    { tool_use_id: 'call-2', type: 'tool_result', is_error: true },
    '{"status":"failed","exit_code":7,"stderr":"failure"}',
    'mcp__jianghu_workspace__bash',
  );

  assert.equal(action.tool_name, 'Bash');
  assert.equal(action.status, 'failed');
  assert.equal(action.is_error, true);
  assert.equal(action.exit_code, 7);
});


test('uses a real bash implementation for Windows commands', () => {
  const shell = commandShell('printf ok', 'win32', {
    ProgramFiles: 'C:\\Program Files',
  }, () => true);

  assert.equal(shell.executable, 'C:\\Program Files\\Git\\bin\\bash.exe');
  assert.equal(shell.kind, 'git-bash');
  assert.deepEqual(shell.args, ['--noprofile', '--norc', '-lc', 'printf ok']);
});


test('uses bin bash on non-Windows systems', () => {
  const shell = commandShell('printf ok', 'linux', {});

  assert.equal(shell.executable, '/bin/bash');
  assert.equal(shell.kind, 'bash');
});


test('prevents git from discovering repositories above the delivery root', () => {
  const environment = workspaceToolEnvironment('D:\\workspace\\run\\delivery', 'win32');

  assert.equal(environment.GIT_CEILING_DIRECTORIES, '/d/workspace/run/delivery');
  assert.equal(environment.GIT_DISCOVERY_ACROSS_FILESYSTEM, '0');
  assert.equal(environment.GIT_CONFIG_NOSYSTEM, '1');
  assert.equal(environment.GIT_CONFIG_GLOBAL, 'NUL');
  assert.equal(environment.GIT_DIR, 'D:\\workspace\\run\\delivery\\.git');
  assert.equal(environment.GIT_WORK_TREE, 'D:\\workspace\\run\\delivery');
  assert.equal(environment.LANG, 'C.UTF-8');
  assert.equal(environment.LC_ALL, 'C.UTF-8');
  assert.equal(environment.PYTHONIOENCODING, 'utf-8');
  assert.equal(environment.PYTHONUTF8, '1');
});


test('rejects parent and Git Bash drive path escapes', () => {
  assert.equal(commandHasPathEscape('cd .. && pwd'), true);
  assert.equal(commandHasPathEscape('git -C .. status'), true);
  assert.equal(commandHasPathEscape('ls /d/Users/User'), true);
  assert.equal(commandHasPathEscape('cmd.exe /c type %USERPROFILE%\\secret.txt'), true);
  assert.equal(commandHasPathEscape('python -m unittest discover -s tests -v'), false);
  assert.equal(commandHasPathEscape('python --version && pwd && date -u +%Y-%m-%dT%H:%M:%SZ'), false);
});
