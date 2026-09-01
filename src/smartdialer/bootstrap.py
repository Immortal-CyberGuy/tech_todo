from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import DialerConfig
from .pacing.predictive import PredictivePacingEngine
from .pacing.progressive import ProgressivePacingEngine
from .pacing.safety_controller import SafetyController
from .providers.provider_a import ProviderA
from .providers.provider_b import ProviderB
from .repository import Repository
from .services.allocator import AllocationService
from .services.campaign_runner import CampaignRunner
from .services.event_ingestor import EventIngestor
from .services.metrics import MetricsService
from .services.recovery import RecoveryService


@dataclass(slots=True)
class AppContainer:
    config: DialerConfig
    repository: Repository
    providers: dict[str, object]
    runner: CampaignRunner


def build_app(
    *,
    db_path: str | Path,
    provider_a_kwargs: dict[str, object] | None = None,
    provider_b_kwargs: dict[str, object] | None = None,
) -> AppContainer:
    config = DialerConfig(db_path=Path(db_path))
    repository = Repository(config.db_path)
    repository.init_db()
    providers = {
        "provider_a": ProviderA(**(provider_a_kwargs or {})),
        "provider_b": ProviderB(**(provider_b_kwargs or {})),
    }
    event_ingestor = EventIngestor(repository, config)
    runner = CampaignRunner(
        repository=repository,
        progressive_engine=ProgressivePacingEngine(),
        predictive_engine=PredictivePacingEngine(),
        safety_controller=SafetyController(config),
        allocator=AllocationService(repository, config),
        metrics_service=MetricsService(repository, config),
        event_ingestor=event_ingestor,
        recovery_service=RecoveryService(repository, config, event_ingestor),
        providers=providers,
    )
    return AppContainer(
        config=config,
        repository=repository,
        providers=providers,
        runner=runner,
    )

