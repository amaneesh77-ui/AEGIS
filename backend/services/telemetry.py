"""No-op ChromaDB telemetry client.

AEGIS runs fully air-gapped, so product telemetry has no destination anyway.
The bundled `chromadb.telemetry.product.posthog.Posthog` client also breaks
under posthog>=3 (its call to `posthog.capture(user_id, event, properties)`
no longer matches posthog's current `capture(event, **kwargs)` signature),
logging "Failed to send telemetry event ...: capture() takes 1 positional
argument but 3 were given" on every Chroma client init. Swapping in this
client avoids both the noise and the broken call.
"""

from chromadb.config import System
from chromadb.telemetry.product import ProductTelemetryClient, ProductTelemetryEvent
from overrides import override


class NoopTelemetry(ProductTelemetryClient):
    def __init__(self, system: System):
        super().__init__(system)

    @override
    def capture(self, event: ProductTelemetryEvent) -> None:
        pass
