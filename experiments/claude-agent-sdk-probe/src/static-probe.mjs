import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import * as sdk from '@anthropic-ai/claude-agent-sdk';

const here = dirname(fileURLToPath(import.meta.url));
const root = dirname(here);
const packagePath = join(root, 'node_modules', '@anthropic-ai', 'claude-agent-sdk', 'package.json');
const packageData = JSON.parse(readFileSync(packagePath, 'utf8'));
const platformKey = `${process.platform}-${process.arch}`;
const platformPackage = `claude-agent-sdk-${platformKey}`;
const binaryName = process.platform === 'win32' ? 'claude.exe' : 'claude';
const platformBinaryCandidates = [
  join(root, 'node_modules', '@anthropic-ai', platformPackage, binaryName),
  join(
    root,
    'node_modules',
    '@anthropic-ai',
    'claude-agent-sdk',
    'node_modules',
    '@anthropic-ai',
    platformPackage,
    binaryName,
  ),
];
const platformBinary = platformBinaryCandidates.find((candidate) => existsSync(candidate));

const exportsList = Object.keys(sdk).sort();
const result = {
  schema_version: 1,
  probe: 'static',
  status: typeof sdk.query === 'function' ? 'passed' : 'failed',
  runtime: {
    node: process.version,
    platform: process.platform,
    arch: process.arch,
  },
  sdk: {
    package: packageData.name,
    version: packageData.version,
    claude_code_version: packageData.claudeCodeVersion,
    node_requirement: packageData.engines?.node ?? null,
    license: packageData.license,
    query_exported: typeof sdk.query === 'function',
    resolve_settings_exported: typeof sdk.resolveSettings === 'function',
    export_count: exportsList.length,
    exports_sha256: createHash('sha256').update(JSON.stringify(exportsList)).digest('hex'),
  },
  platform_binary: {
    path_kind: `bundled-${platformKey}`,
    exists: Boolean(platformBinary),
  },
};

process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
