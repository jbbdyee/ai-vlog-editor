"""Regenerate cutory-render-events.workflow.json from record-render-event.js (the single source of the logic).

    python deploy/n8n/build_workflow.py          # write
    python deploy/n8n/build_workflow.py --check  # exit 1 if the JSON is stale

No credentials, ids or secrets are written: the Header Auth credential is attached in n8n after import.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CODE = HERE / "record-render-event.js"
TARGET = HERE / "cutory-render-events.workflow.json"
WEBHOOK_PATH = "cutory-render-events"


def build() -> dict:
    code = CODE.read_text(encoding="utf-8")
    return {
        "name": "Cutory render events (MVP)",
        "nodes": [
            {
                "name": "Render event webhook",
                "type": "n8n-nodes-base.webhook",
                "typeVersion": 2,
                "position": [0, 0],
                "webhookId": "cutory-render-events",
                "parameters": {
                    "httpMethod": "POST",
                    "path": WEBHOOK_PATH,
                    "authentication": "headerAuth",
                    "responseMode": "responseNode",
                    "options": {},
                },
            },
            {
                "name": "Validate and record",
                "type": "n8n-nodes-base.code",
                "typeVersion": 2,
                "position": [260, 0],
                "parameters": {"mode": "runOnceForAllItems", "language": "javaScript", "jsCode": code},
            },
            {
                "name": "Respond",
                "type": "n8n-nodes-base.respondToWebhook",
                "typeVersion": 1.1,
                "position": [520, 0],
                "parameters": {
                    "respondWith": "json",
                    "responseBody": "={{ JSON.stringify($json.response) }}",
                    "options": {"responseCode": "={{ $json.httpStatus }}"},
                },
            },
        ],
        "connections": {
            "Render event webhook": {"main": [[{"node": "Validate and record", "type": "main", "index": 0}]]},
            "Validate and record": {"main": [[{"node": "Respond", "type": "main", "index": 0}]]},
        },
        # The webhook node output contains the request headers (incl. Authorization). n8n 2.46.6 writes the
        # execution while it runs; with these settings it is deleted right after it finishes (see README).
        "settings": {
            "executionOrder": "v1",
            "saveDataSuccessExecution": "none",
            "saveDataErrorExecution": "none",
            "saveManualExecutions": False,
            "saveExecutionProgress": False,
        },
        "active": False,
    }


def render() -> str:
    return json.dumps(build(), ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    if "--check" in sys.argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        sys.exit(0 if current == render() else 1)
    TARGET.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {TARGET.name}")
