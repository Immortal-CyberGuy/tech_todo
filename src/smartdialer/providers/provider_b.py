from __future__ import annotations

from .base import MockProviderBase


class ProviderB(MockProviderBase):
    def __init__(self, **kwargs: object) -> None:
        defaults = {
            "name": "provider_b",
            "answer_rate": 0.45,
            "setup_ticks": 3,
            "talk_ticks": 5,
            "failure_rate": 0.10,
            "timeout_rate": 0.10,
            "duplicate_rate": 0.35,
            "disorder_rate": 0.50,
            "jitter_ticks": 2,
        }
        defaults.update(kwargs)
        super().__init__(**defaults)
