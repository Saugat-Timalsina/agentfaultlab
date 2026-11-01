"""Observable actions only; no hidden model reasoning is requested or persisted."""

import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentfaultlab.schemas import TraceEvent

SECRET_KEY = re.compile(
    r"^(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret|"
    r"authorization|credentials?|OPENAI_API_KEY)$",
    re.I,
)
SECRET_VALUE = re.compile(r"sk-[\w-]{8,}|Bearer\s+[^\s\"']+", re.I)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: "[REDACTED]" if SECRET_KEY.search(k) else redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return SECRET_VALUE.sub("[REDACTED]", value)
    return value


class Trace:
    def __init__(self, run_id: str, scenario_id: str, clock=time.monotonic):
        self.run_id, self.scenario_id = run_id, scenario_id
        self.clock, self.start = clock, clock()
        self.events: list[TraceEvent] = []
        self.calls = {}

    def register_call(self, call):
        self.calls[call.id] = call

    def emit(self, event_type: str, payload=None, **fields) -> None:
        call = self.calls.get(fields.get("call_id"))
        if call:
            for key, value in {
                "root_call_id": call.root_call_id or call.id,
                "parent_call_id": call.parent_call_id,
                "attempt": call.attempt,
                "owner": call.owner,
            }.items():
                fields.setdefault(key, value)
        self.events.append(
            TraceEvent(
                run_id=self.run_id,
                scenario_id=self.scenario_id,
                seq=len(self.events) + 1,
                timestamp=datetime.now(UTC).isoformat(),
                elapsed_s=self.clock() - self.start,
                event_type=event_type,
                payload=redact(payload or {}),
                **fields,
            )
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(e.model_dump_json() + "\n" for e in self.events))


def load_trace(path: Path) -> list[TraceEvent]:
    events = [
        TraceEvent.model_validate(json.loads(line))
        for line in path.read_text().splitlines()
        if line.strip()
    ]
    for seq, event in enumerate(events, 1):
        if event.seq != seq:
            raise ValueError("Trace sequence is not contiguous")
        if events and (event.run_id, event.scenario_id) != (
            events[0].run_id,
            events[0].scenario_id,
        ):
            raise ValueError("Trace mixes runs")
    return events
