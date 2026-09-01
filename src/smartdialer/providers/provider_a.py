from __future__ import annotations

from .base import MockProviderBase


class ProviderA(MockProviderBase):
    def __init__(self, **kwargs: object) -> None:
        defaults = {
            "name": "provider_a",
            "answer_rate": 0.45,
            "setup_ticks": 2,
            "talk_ticks": 4,
            "failure_rate": 0.04,
            "timeout_rate": 0.01,
            "duplicate_rate": 0.0,
            "disorder_rate": 0.0,
            "jitter_ticks": 0,
        }
        defaults.update(kwargs)
        super().__init__(**defaults)
