// Offline check of the n8n Code node logic (no n8n needed). Usage:
//   node deploy/n8n/check-record-render-event.mjs [events.json]
// events.json (optional): array of bodies produced by Cutory (e.g. RenderTerminalEvent.payload()).
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const source = readFileSync(path.join(here, 'record-render-event.js'), 'utf8');
const DIR_LINE = "const DIR = '/home/node/.n8n-files/cutory-render-events';";
if (!source.includes(DIR_LINE)) throw new Error('DIR line changed; update the check');
const nodeRequire = createRequire(import.meta.url);
const AsyncFunction = Object.getPrototypeOf(async () => {}).constructor;
// Mimic the n8n 2.x task-runner sandbox: only NODE_FUNCTION_ALLOW_BUILTIN modules, no `process` global.
const ALLOWED_BUILTINS = new Set(['fs', 'path']);
const sandboxRequire = (name) => {
  if (!ALLOWED_BUILTINS.has(name)) throw new Error(`module not allowed in sandbox: ${name}`);
  return nodeRequire(name);
};

export async function run(dir, body) {
  const code = source.replace(DIR_LINE, `const DIR = ${JSON.stringify(dir)};`);
  const $input = { all: () => [{ json: { headers: {}, params: {}, query: {}, body } }] };
  const [item] = await new AsyncFunction('$input', 'require', 'process', code)($input, sandboxRequire, undefined);
  return item.json;
}

const completed = {
  schema_version: 1, event_id: 'render-0123456789abcdef0123456789abcdef-completed', event_type: 'render.completed',
  project_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', render_id: '01234567-89ab-cdef-0123-456789abcdef',
  status: 'COMPLETED', safe_error_code: null, finished_at: '2026-11-06T01:02:03.123456Z',
  duration_seconds: 12.5, file_size_bytes: 2048, status_url: '/projects/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/rendering',
};
const failed = { ...completed, event_id: completed.event_id.replace('completed', 'failed'), event_type: 'render.failed',
  status: 'FAILED', safe_error_code: 'OUTPUT_INVALID', duration_seconds: null, file_size_bytes: null };

let failures = 0;
function expect(name, actual, status, result) {
  const ok = actual.httpStatus === status && (result === undefined || actual.response.result === result);
  if (!ok) failures += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name} -> ${actual.httpStatus} ${JSON.stringify(actual.response)}`);
}

async function main() {
const root = mkdtempSync(path.join(tmpdir(), 'cutory-n8n-check-'));
try {
  const dir = path.join(root, 'events');
  expect('completed recorded', await run(dir, completed), 200, 'recorded');
  expect('same event duplicate', await run(dir, completed), 200, 'duplicate');
  expect('same id, different content -> conflict', await run(dir, { ...completed, file_size_bytes: 4096 }), 409, 'conflict');
  expect('failed recorded', await run(dir, failed), 200, 'recorded');
  const stored = readFileSync(path.join(dir, `${completed.event_id}.json`), 'utf8');
  const okContent = JSON.parse(stored).file_size_bytes === 2048;
  if (!okContent) failures += 1;
  console.log(`${okContent ? 'PASS' : 'FAIL'} conflict did not overwrite the first record`);
  const invalid = {
    'missing field': (({ status_url, ...rest }) => rest)(completed),
    'extra field': { ...completed, note: 'x' },
    'event id mismatch': { ...completed, event_id: 'render-ffffffffffffffffffffffffffffffff-completed' },
    'event type mismatch': { ...completed, event_type: 'render.failed' },
    'unknown status': { ...completed, status: 'RUNNING' },
    'failed with output': { ...failed, file_size_bytes: 10 },
    'completed with error code': { ...completed, safe_error_code: 'X' },
    'bad time': { ...completed, finished_at: '2026-11-06 01:02:03' },
    'status url mismatch': { ...completed, status_url: '/projects/other/rendering' },
    'not an object': [completed],
  };
  for (const [name, body] of Object.entries(invalid)) expect(`invalid: ${name}`, await run(dir, body), 400, 'invalid');
  const blocked = path.join(root, 'is-a-file');
  writeFileSync(blocked, 'x');
  expect('storage failure -> 500', await run(blocked, completed), 500, 'error');

  // Concurrent duplicates from separate processes: exactly one "recorded".
  const raceDir = path.join(root, 'race');
  const worker = `import { run } from ${JSON.stringify(new URL(import.meta.url).href)};\n` +
    `const [dir, body] = process.argv.slice(-2); const r = await run(dir, JSON.parse(body)); console.log(JSON.stringify(r));`;
  const children = Array.from({ length: 8 }, () => new Promise((resolve) => {
    const child = spawn(process.execPath, ['--input-type=module', '-e', worker, raceDir, JSON.stringify(completed)],
      { env: { ...process.env, CUTORY_N8N_CHECK_CHILD: '1' } });
    let out = '';
    child.stdout.on('data', (d) => { out += d; });
    child.on('close', () => resolve(JSON.parse(out.trim().split('\n').pop())));
  }));
  const results = (await Promise.all(children)).map((r) => r.response.result).sort();
  const raceOk = results.filter((r) => r === 'recorded').length === 1 && results.filter((r) => r === 'duplicate').length === 7;
  const leftovers = readdirSync(raceDir).filter((f) => f.endsWith('.tmp'));
  if (!raceOk || leftovers.length) failures += 1;
  console.log(`${raceOk && !leftovers.length ? 'PASS' : 'FAIL'} 8 concurrent duplicates -> ${results.join(',')}; tmp left=${leftovers.length}`);

  if (process.argv[2]) {
    const bodies = JSON.parse(readFileSync(process.argv[2], 'utf8'));
    const cutoryDir = path.join(root, 'cutory');
    for (const body of bodies) {
      expect(`cutory body ${body.event_id}`, await run(cutoryDir, body), 200, 'recorded');
      expect(`cutory body again ${body.event_id}`, await run(cutoryDir, body), 200, 'duplicate');
    }
  }
} finally {
  rmSync(root, { recursive: true, force: true });
}
console.log(failures ? `FAILED ${failures}` : 'ALL PASS');
process.exitCode = failures ? 1 : 0;
}

if (process.env.CUTORY_N8N_CHECK_CHILD !== '1') await main(); // children only import run()
