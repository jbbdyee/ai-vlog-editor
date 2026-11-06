// Cutory render event → validate, record once (atomic create), verify, then answer the webhook.
// n8n Code node, "Run Once for All Items". Needs NODE_FUNCTION_ALLOW_BUILTIN=fs,path.
// The webhook node already checked the Authorization header (Header Auth credential).
// Event ids are stable but NOT trusted alone: a duplicate is accepted only if the stored record is identical.
const fs = require('fs');
const path = require('path');

const DIR = '/home/node/.n8n-files/cutory-render-events';
const KEYS = ['schema_version', 'event_id', 'event_type', 'project_id', 'render_id', 'status',
  'safe_error_code', 'finished_at', 'duration_seconds', 'file_size_bytes', 'status_url'];
const SUFFIX = { COMPLETED: 'completed', FAILED: 'failed', RECONCILIATION_REQUIRED: 'reconciliation_required' };
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const CODE_RE = /^[A-Z0-9_]{1,64}$/;
const TIME_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/;

function answer(httpStatus, response) {
  return [{ json: { httpStatus, response } }];
}

function invalidReason(b) {
  if (!b || typeof b !== 'object' || Array.isArray(b)) return 'BODY_NOT_OBJECT';
  const keys = Object.keys(b);
  if (keys.length !== KEYS.length || keys.some((k) => !KEYS.includes(k))) return 'FIELDS';
  if (b.schema_version !== 1) return 'SCHEMA_VERSION';
  const suffix = SUFFIX[b.status];
  if (!suffix) return 'STATUS';
  if (typeof b.render_id !== 'string' || !UUID_RE.test(b.render_id)) return 'RENDER_ID';
  if (typeof b.project_id !== 'string' || !UUID_RE.test(b.project_id)) return 'PROJECT_ID';
  if (b.event_id !== `render-${b.render_id.replace(/-/g, '')}-${suffix}`) return 'EVENT_ID';
  if (b.event_type !== `render.${suffix}`) return 'EVENT_TYPE';
  if (typeof b.finished_at !== 'string' || !TIME_RE.test(b.finished_at)) return 'FINISHED_AT';
  if (b.status_url !== `/projects/${b.project_id}/rendering`) return 'STATUS_URL';
  if (b.status === 'COMPLETED') {
    if (b.safe_error_code !== null) return 'SAFE_ERROR_CODE';
    if (typeof b.duration_seconds !== 'number' || !Number.isFinite(b.duration_seconds) || b.duration_seconds < 0) return 'DURATION';
    if (!Number.isSafeInteger(b.file_size_bytes) || b.file_size_bytes <= 0) return 'FILE_SIZE';
  } else {
    if (typeof b.safe_error_code !== 'string' || !CODE_RE.test(b.safe_error_code)) return 'SAFE_ERROR_CODE';
    if (b.duration_seconds !== null || b.file_size_bytes !== null) return 'FAILED_WITH_OUTPUT';
  }
  return null;
}

const items = $input.all();
if (items.length !== 1) return answer(400, { result: 'invalid', error: 'ITEM_COUNT' });
const body = items[0].json.body;
const reason = invalidReason(body);
if (reason) return answer(400, { result: 'invalid', error: reason });

// Canonical record: fixed key order, no receive time, so every duplicate produces the same bytes.
const record = JSON.stringify(Object.fromEntries(KEYS.map((k) => [k, body[k]]))) + '\n';
const finalPath = path.join(DIR, `${body.event_id}.json`);
// n8n 2.x task-runner sandbox has no `process` global; a random name is enough because 'wx' refuses collisions.
const rand = () => Math.random().toString(16).slice(2);
const tmpPath = path.join(DIR, `.${body.event_id}.${Date.now()}.${rand()}${rand()}.tmp`);
let result;
try {
  fs.mkdirSync(DIR, { recursive: true });
  fs.writeFileSync(tmpPath, record, { flag: 'wx' });
  try {
    fs.linkSync(tmpPath, finalPath); // atomic create-if-absent, also under concurrent duplicates
    result = 'recorded';
  } catch (error) {
    if (error.code !== 'EEXIST') throw error;
    result = 'duplicate';
  } finally {
    try { fs.unlinkSync(tmpPath); } catch (ignored) { /* best effort */ }
  }
  const stored = fs.readFileSync(finalPath, 'utf8'); // verify what is actually on disk
  if (stored !== record) {
    return result === 'duplicate'
      ? answer(409, { result: 'conflict', error: 'EVENT_CONTENT_MISMATCH', event_id: body.event_id })
      : answer(500, { result: 'error', error: 'RECORD_VERIFY_FAILED', event_id: body.event_id });
  }
} catch (error) {
  return answer(500, { result: 'error', error: 'RECORD_WRITE_FAILED', event_id: body.event_id });
}
return answer(200, { result, event_id: body.event_id });
