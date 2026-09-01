from __future__ import annotations

import random
import uuid
from collections import deque
from dataclasses import dataclass

from ..enums import ProviderEventType
from ..models import ProviderEvent, ProviderHealth


@dataclass(slots=True)
class InitiationResult:
    accepted: bool
    provider_call_id: str | None
    reason: str | None = None


@dataclass(slots=True)
class ProviderCallSnapshot:
    provider_call_id: str
    state: str
    terminal: bool
    last_tick: int


@dataclass(slots=True)
class _ScheduledEvent:
    ready_tick: int
    order_key: int
    event: ProviderEvent


class MockProviderBase:
    def __init__(
        self,
        *,
        name: str,
        seed: int = 7,
        answer_rate: float = 0.35,
        setup_ticks: int = 2,
        talk_ticks: int = 4,
        failure_rate: float = 0.05,
        timeout_rate: float = 0.02,
        duplicate_rate: float = 0.0,
        disorder_rate: float = 0.0,
        jitter_ticks: int = 0,
        outage_windows: list[tuple[int, int]] | None = None,
        answer_rate_schedule: list[tuple[int, float]] | None = None,
        talk_ticks_schedule: list[tuple[int, int]] | None = None,
        setup_ticks_schedule: list[tuple[int, int]] | None = None,
    ) -> None:
        self.name = name
        self.rng = random.Random(seed)
        self.default_answer_rate = answer_rate
        self.default_setup_ticks = setup_ticks
        self.default_talk_ticks = talk_ticks
        self.failure_rate = failure_rate
        self.timeout_rate = timeout_rate
        self.duplicate_rate = duplicate_rate
        self.disorder_rate = disorder_rate
        self.jitter_ticks = jitter_ticks
        self.outage_windows = outage_windows or []
        self.answer_rate_schedule = answer_rate_schedule or []
        self.talk_ticks_schedule = talk_ticks_schedule or []
        self.setup_ticks_schedule = setup_ticks_schedule or []
        self.pending_events: list[_ScheduledEvent] = []
        self.snapshots: dict[str, ProviderCallSnapshot] = {}
        self.idempotency_map: dict[str, str] = {}
        self.timeout_ticks: deque[int] = deque(maxlen=100)
        self.failure_ticks: deque[int] = deque(maxlen=100)
        self.accept_ticks: deque[int] = deque(maxlen=100)

    def _value_for_tick(self, default: float | int, schedule: list[tuple[int, float | int]], tick: int) -> float | int:
        value = default
        for start_tick, scheduled_value in sorted(schedule, key=lambda item: item[0]):
            if tick >= start_tick:
                value = scheduled_value
            else:
                break
        return value

    def answer_rate_for_tick(self, tick: int) -> float:
        return float(self._value_for_tick(self.default_answer_rate, self.answer_rate_schedule, tick))

    def talk_ticks_for_tick(self, tick: int) -> int:
        return int(self._value_for_tick(self.default_talk_ticks, self.talk_ticks_schedule, tick))

    def setup_ticks_for_tick(self, tick: int) -> int:
        return int(self._value_for_tick(self.default_setup_ticks, self.setup_ticks_schedule, tick))

    def is_outage(self, tick: int) -> bool:
        return any(start <= tick <= end for start, end in self.outage_windows)

    def initiate_call(
        self,
        *,
        call_attempt_id: str,
        tick: int,
        idempotency_key: str,
    ) -> InitiationResult:
        if idempotency_key in self.idempotency_map:
            return InitiationResult(True, self.idempotency_map[idempotency_key], "idempotent_replay")
        if self.is_outage(tick) or self.rng.random() < self.timeout_rate:
            self.timeout_ticks.append(tick)
            return InitiationResult(False, None, "provider_timeout")
        provider_call_id = f"{self.name}-{uuid.uuid4().hex[:10]}"
        self.idempotency_map[idempotency_key] = provider_call_id
        self.accept_ticks.append(tick)
        self.snapshots[provider_call_id] = ProviderCallSnapshot(
            provider_call_id=provider_call_id,
            state="INITIATED",
            terminal=False,
            last_tick=tick,
        )
        self._schedule_call_events(
            provider_call_id=provider_call_id,
            call_attempt_id=call_attempt_id,
            tick=tick,
        )
        return InitiationResult(True, provider_call_id)

    def _schedule_call_events(self, *, provider_call_id: str, call_attempt_id: str, tick: int) -> None:
        setup_ticks = self.setup_ticks_for_tick(tick)
        talk_ticks = self.talk_ticks_for_tick(tick)
        answered = self.rng.random() < self.answer_rate_for_tick(tick)
        hard_failure = self.rng.random() < self.failure_rate
        timeline: list[tuple[int, ProviderEventType]] = []
        timeline.append((max(tick + 1, tick + setup_ticks - 1), ProviderEventType.RINGING))
        if hard_failure or not answered:
            timeline.append((tick + setup_ticks + 1, ProviderEventType.FAILED))
        else:
            timeline.append((tick + setup_ticks, ProviderEventType.ANSWERED))
            timeline.append((tick + setup_ticks + 1, ProviderEventType.CONNECTED))
            timeline.append((tick + setup_ticks + 1 + max(talk_ticks, 1), ProviderEventType.COMPLETED))
        for index, (base_tick, event_type) in enumerate(timeline):
            jitter = 0
            if self.jitter_ticks:
                jitter = self.rng.randint(-self.jitter_ticks, self.jitter_ticks)
            ready_tick = max(tick + 1, base_tick + jitter)
            event_key = f"{provider_call_id}:{event_type.value}:{index}"
            event = ProviderEvent(
                event_key=event_key,
                provider=self.name,
                provider_call_id=provider_call_id,
                call_attempt_id=call_attempt_id,
                event_type=event_type.value,
                occurred_at=ready_tick,
                payload={"provider": self.name},
            )
            self.pending_events.append(_ScheduledEvent(ready_tick, index, event))
            if self.duplicate_rate and self.rng.random() < self.duplicate_rate:
                duplicate_ready_tick = ready_tick + self.rng.randint(0, 1)
                duplicate_event = ProviderEvent(
                    event_key=event_key,
                    provider=self.name,
                    provider_call_id=provider_call_id,
                    call_attempt_id=call_attempt_id,
                    event_type=event_type.value,
                    occurred_at=duplicate_ready_tick,
                    payload={"provider": self.name, "duplicate": True},
                )
                self.pending_events.append(_ScheduledEvent(duplicate_ready_tick, index + 100, duplicate_event))

    def drain_events(self, tick: int) -> list[ProviderEvent]:
        ready = [item for item in self.pending_events if item.ready_tick <= tick]
        self.pending_events = [item for item in self.pending_events if item.ready_tick > tick]
        if self.disorder_rate and ready and self.rng.random() < self.disorder_rate:
            self.rng.shuffle(ready)
        else:
            ready.sort(key=lambda item: (item.ready_tick, item.order_key))
        events: list[ProviderEvent] = []
        for scheduled in ready:
            snapshot = self.snapshots.get(scheduled.event.provider_call_id)
            if snapshot is None:
                continue
            snapshot.state = scheduled.event.event_type
            snapshot.last_tick = tick
            snapshot.terminal = scheduled.event.event_type in {
                ProviderEventType.COMPLETED.value,
                ProviderEventType.FAILED.value,
                ProviderEventType.CANCELLED.value,
            }
            if snapshot.terminal:
                self.failure_ticks.append(tick) if scheduled.event.event_type == ProviderEventType.FAILED.value else None
            events.append(scheduled.event)
        return events

    def cancel_call(self, provider_call_id: str, tick: int) -> None:
        snapshot = self.snapshots.get(provider_call_id)
        if snapshot is None:
            return
        snapshot.state = ProviderEventType.CANCELLED.value
        snapshot.terminal = True
        snapshot.last_tick = tick
        self.pending_events = [item for item in self.pending_events if item.event.provider_call_id != provider_call_id]

    def get_call_snapshot(self, provider_call_id: str) -> ProviderCallSnapshot | None:
        return self.snapshots.get(provider_call_id)

    def health_snapshot(self, tick: int) -> ProviderHealth:
        if self.is_outage(tick):
            return ProviderHealth(0.15, "provider outage window")
        recent_timeouts = sum(1 for item in self.timeout_ticks if item >= tick - 10)
        recent_failures = sum(1 for item in self.failure_ticks if item >= tick - 10)
        recent_accepts = sum(1 for item in self.accept_ticks if item >= tick - 10)
        denominator = max(1, recent_accepts + recent_timeouts)
        timeout_ratio = recent_timeouts / denominator
        failure_ratio = recent_failures / max(1, recent_accepts)
        score = 1.0 - min(0.6, timeout_ratio) - min(0.3, failure_ratio / 2)
        score = max(0.1, min(1.0, score))
        reason = f"timeout_ratio={timeout_ratio:.2f}, failure_ratio={failure_ratio:.2f}"
        return ProviderHealth(score, reason)

