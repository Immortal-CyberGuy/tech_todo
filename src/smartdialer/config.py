from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DialerConfig:
    db_path: Path
    reserve_timeout_ticks: int = 3
    call_stall_timeout_ticks: int = 8
    wrap_up_ticks: int = 2
    predictive_setup_buffer_ticks: int = 2
    recent_window_calls: int = 50
    provider_event_window_ticks: int = 10


def default_db_path(root: Path | None = None) -> Path:
    base = root or Path.cwd()
    return base / "smartdialer.sqlite3"

