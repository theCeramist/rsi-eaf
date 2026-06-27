"""
Per-cycle execution traces (JSONL).
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

TRACE_FILE = os.getenv("FACTORY_TRACE_FILE", "observability/cycle_traces.jsonl")


class TraceLogger:
    def __init__(self, trace_path: str = TRACE_FILE):
        self.trace_path = trace_path
        Path(trace_path).parent.mkdir(parents=True, exist_ok=True)

    def log_cycle_trace(
        self,
        cycle_id: int,
        phase: str,
        data: Dict[str, Any],
        duration_ms: Optional[float] = None,
    ) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cycle_id": cycle_id,
            "phase": phase,
            "duration_ms": duration_ms,
            "data": data,
        }
        with open(self.trace_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")


trace_logger = TraceLogger()