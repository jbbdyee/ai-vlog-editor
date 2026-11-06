"""Re-send render terminal events from the DB (read-only) to the n8n webhook.

    python -m backend.app.render_event_replay --since 2026-11-06T00:00:00Z [--until ...] [--project-id ...] [--send]

Without --send it only lists the event ids it would send (dry run). Event ids and bodies are the same as
the live ones, so a receiver must treat a replay as a possible duplicate.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import sys
from uuid import UUID

from backend.app.config import PROJECT_ROOT, DatabaseSettings, load_environment
from backend.app.database import create_database_engine, create_session_factory
from backend.app.services.render_events import (
    RenderEventConfigError, RenderEventDispatcher, RenderEventSettings, collect_terminal_events,
)


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp needs a timezone, e.g. 2026-11-06T00:00:00Z")
    return parsed.astimezone(timezone.utc)


def replay(session_factory, *, since: datetime, until: datetime | None = None, project_id: UUID | None = None,
           limit: int = 500, dispatcher: RenderEventDispatcher | None = None, out=print) -> dict:
    events = collect_terminal_events(session_factory, since=since, until=until, project_id=project_id, limit=limit)
    outcomes: dict[str, int] = {}
    for event in events:
        outcome = dispatcher.deliver(event, trigger="replay") if dispatcher is not None else "would_send"
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        out(f"{event.event_id}\t{event.status}\t{event.finished_at}\t{outcome}")
    summary = {"events": len(events), **outcomes}
    out("summary " + " ".join(f"{key}={value}" for key, value in summary.items()))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", required=True, type=parse_utc)
    parser.add_argument("--until", type=parse_utc)
    parser.add_argument("--project-id", type=UUID)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--send", action="store_true", help="actually POST (default: dry run)")
    args = parser.parse_args(argv)
    load_environment()
    dispatcher = None
    if args.send:
        try:
            settings = RenderEventSettings.from_environment()
        except RenderEventConfigError as error:
            print(f"render events not configured: {error.code}", file=sys.stderr)
            return 2
        if settings is None:
            print("render events not configured: RENDER_EVENT_DISABLED", file=sys.stderr)
            return 2
        dispatcher = RenderEventDispatcher(  # same Git-ignored trace file as the server (no secrets)
            settings, start=False,
            log_path=settings.log_path or PROJECT_ROOT / "temporary" / "render-events" / "deliveries.jsonl")
    engine = create_database_engine(DatabaseSettings.from_environment())
    try:
        summary = replay(create_session_factory(engine), since=args.since, until=args.until,
                         project_id=args.project_id, limit=args.limit, dispatcher=dispatcher)
    finally:
        if dispatcher is not None:
            dispatcher.close()
        engine.dispose()
    return 0 if summary["events"] == summary.get("delivered", 0) + summary.get("would_send", 0) else 1


if __name__ == "__main__":
    sys.exit(main())
