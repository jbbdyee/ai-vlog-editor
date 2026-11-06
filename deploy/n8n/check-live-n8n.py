"""Live checks against the isolated n8n (127.0.0.1:5678, container `cutory-n8n`). Synthetic events only.

    CUTORY_N8N_TEST_DIR=<Git 밖 임시 폴더> python deploy/n8n/check-live-n8n.py before
    (n8n 재시작 후)                         python deploy/n8n/check-live-n8n.py after

The test directory must hold `test-token.txt` (the Header Auth test secret, outside Git). The token is never
printed; state/delivery logs are written to the same directory. No Cutory server, DB, render or LLM/VLM call.
"""
import json, os, subprocess, sys, time, uuid, pathlib, concurrent.futures as cf
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import site
site.addsitedir(str(ROOT / ".venv" / "Lib" / "site-packages"))
import httpx
from backend.app.services.render_events import terminal_event

HERE = pathlib.Path(os.environ["CUTORY_N8N_TEST_DIR"])
TOKEN = (HERE / "test-token.txt").read_text().strip()
URL = "http://127.0.0.1:5678/webhook/cutory-render-events"
DIR = "/home/node/.n8n-files/cutory-render-events"
STATE = HERE / "state.json"
phase = sys.argv[1]
client = httpx.Client(trust_env=False, follow_redirects=False, timeout=10)
results = []


def post(body: bytes, token=TOKEN, extra=None):
    h = {"Content-Type": "application/json"}
    if token is not None:
        h["Authorization"] = f"Bearer {token}"
    h.update(extra or {})
    r = client.post(URL, content=body, headers=h)
    try:
        j = r.json()
    except Exception:
        j = r.text[:120]
    return r.status_code, j


def cat(event_id):
    p = subprocess.run(["docker", "exec", "cutory-n8n", "cat", f"{DIR}/{event_id}.json"], capture_output=True)
    return p.returncode, p.stdout


def check(name, ok, detail):
    results.append((name, bool(ok), detail))
    print(("PASS" if ok else "FAIL"), name, "|", detail)


def ev(status, **kw):
    pid, rid = uuid.uuid4(), uuid.uuid4()
    fin = datetime.now(timezone.utc)
    if status == "COMPLETED":
        return terminal_event(project_id=pid, render_id=rid, status=status, safe_error_code=None,
                              finished_at=fin, duration_seconds=kw.get("dur", 12.5), file_size_bytes=kw.get("size", 1048576))
    return terminal_event(project_id=pid, render_id=rid, status=status, safe_error_code=kw.get("code", "RENDER_FAILED"),
                          finished_at=fin, duration_seconds=None, file_size_bytes=None)


def canonical(e):
    keys = ['schema_version', 'event_id', 'event_type', 'project_id', 'render_id', 'status',
            'safe_error_code', 'finished_at', 'duration_seconds', 'file_size_bytes', 'status_url']
    p = e.payload()
    return (json.dumps({k: p[k] for k in keys}, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


if phase == "before":
    done = ev("COMPLETED")
    body = done.body()
    eid = done.payload()["event_id"]

    s, j = post(body, token=None)
    check("auth: no header", s in (401, 403), f"{s} {j}")
    s, j = post(body, token="x" * 64)
    check("auth: wrong token", s in (401, 403), f"{s} {j}")
    rc, _ = cat(eid)
    check("auth: nothing recorded on auth failure", rc != 0, f"cat rc={rc}")

    t0 = time.time()
    s, j = post(body)
    rc, data = cat(eid)  # file must already be there once the 200 arrived
    check("normal: recorded", s == 200 and j.get("result") == "recorded", f"{s} {j}")
    check("record-before-response: file present & canonical", rc == 0 and data == canonical(done),
          f"rc={rc} bytes={len(data)} equal={data == canonical(done)}")

    s, j = post(body)
    check("duplicate: same body", s == 200 and j.get("result") == "duplicate", f"{s} {j}")

    p = json.loads(body); p["file_size_bytes"] = 2048
    s, j = post(json.dumps(p).encode())
    rc, data2 = cat(eid)
    check("conflict: same id, different body", s == 409 and j.get("result") == "conflict", f"{s} {j}")
    check("conflict: stored record unchanged", data2 == data, f"equal={data2 == data}")

    p = json.loads(body); p["extra"] = 1
    s, j = post(json.dumps(p).encode())
    check("invalid: extra field -> 400", s == 400 and j.get("error") == "FIELDS", f"{s} {j}")
    p = json.loads(body); p["event_id"] = "render-" + "0" * 32 + "-completed"
    s, j = post(json.dumps(p).encode())
    check("invalid: event_id mismatch -> 400", s == 400 and j.get("error") == "EVENT_ID", f"{s} {j}")
    s, j = post(b"not json")
    check("invalid: not json", s in (400, 422, 500), f"{s} {str(j)[:80]}")

    failed, recon = ev("FAILED"), ev("RECONCILIATION_REQUIRED", code="RENDER_OUTPUT_UNVERIFIED")
    for e in (failed, recon):
        s, j = post(e.body())
        rc, d = cat(e.payload()["event_id"])
        check(f"normal: {e.status}", s == 200 and j.get("result") == "recorded" and d == canonical(e), f"{s} {j}")

    # Concurrent identical deliveries: exactly one 'recorded'.
    race = ev("COMPLETED")
    with cf.ThreadPoolExecutor(8) as pool:
        outs = list(pool.map(lambda _: post(race.body()), range(8)))
    rs = sorted(o[1].get("result") for o in outs if isinstance(o[1], dict))
    check("race: 8 concurrent -> 1 recorded, 7 duplicate", rs.count("recorded") == 1 and rs.count("duplicate") == 7 and all(o[0] == 200 for o in outs), str(rs))

    # Write failure must not be answered with 200: a directory squats the final path.
    blocked = ev("COMPLETED")
    beid = blocked.payload()["event_id"]
    subprocess.run(["docker", "exec", "cutory-n8n", "mkdir", "-p", f"{DIR}/{beid}.json"], check=True)
    s, j = post(blocked.body())
    check("write failure -> 500, not 200", s == 500 and j.get("error") == "RECORD_WRITE_FAILED", f"{s} {j}")
    subprocess.run(["docker", "exec", "cutory-n8n", "rmdir", f"{DIR}/{beid}.json"], check=True)

    # Cutory's own dispatcher against the real receiver (no Cutory server involved).
    from backend.app.services.render_events import RenderEventDispatcher, RenderEventSettings
    log = HERE / "deliveries.jsonl"
    log.unlink(missing_ok=True)
    settings = RenderEventSettings.from_environment({"CUTORY_N8N_WEBHOOK_URL": URL, "CUTORY_N8N_WEBHOOK_TOKEN": TOKEN})
    d = RenderEventDispatcher(settings, log_path=log, start=False, backoff_seconds=(0, 0, 0))
    disp = ev("COMPLETED")
    o1 = d.deliver(disp, trigger="live"); o2 = d.deliver(disp, trigger="replay")
    d.close()
    logtext = log.read_text()
    recs = [json.loads(x) for x in logtext.splitlines()]
    rr = [(r["outcome"], r.get("http_status"), r.get("receiver_result")) for r in recs]
    check("dispatcher: recorded then duplicate", o1 == o2 == "delivered" and rr[0][2] == "recorded" and rr[-1][2] == "duplicate", str(rr))
    check("dispatcher log: no token / no URL", TOKEN not in logtext and "5678" not in logtext, f"lines={len(logtext.splitlines())}")

    STATE.write_text(json.dumps({"done": body.decode(), "eid": eid, "data": data.decode(),
                                 "ids": [eid, failed.payload()["event_id"], recon.payload()["event_id"], race.payload()["event_id"], disp.payload()["event_id"]]}))

elif phase == "after":
    st = json.loads(STATE.read_text())
    body = st["done"].encode()
    rc, data = cat(st["eid"])
    check("restart: record survived", rc == 0 and data.decode() == st["data"], f"rc={rc}")
    s, j = post(body)
    check("restart: duplicate still detected", s == 200 and j.get("result") == "duplicate", f"{s} {j}")
    p = json.loads(body); p["duration_seconds"] = 99.0
    s, j = post(json.dumps(p).encode())
    check("restart: conflict still 409", s == 409, f"{s} {j}")
    s, j = post(body, token=None)
    check("restart: auth still enforced", s in (401, 403), f"{s}")
    ls = subprocess.run(["docker", "exec", "cutory-n8n", "sh", "-c", f"ls -la {DIR}; ls -A {DIR} | grep -c '\\.tmp$' || true"], capture_output=True, text=True)
    print(ls.stdout)

print(f"\n{sum(ok for _, ok, _ in results)}/{len(results)} passed")
sys.exit(0 if all(ok for _, ok, _ in results) else 1)
