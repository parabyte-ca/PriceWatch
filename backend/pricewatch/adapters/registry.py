from .base import Adapter
from .generic import GenericAdapter

_ADAPTERS: dict[str, Adapter] = {"generic": GenericAdapter()}


def get_adapter(name: str | None) -> Adapter:
    return _ADAPTERS.get(name or "generic", _ADAPTERS["generic"])


def register(adapter: Adapter) -> None:
    _ADAPTERS[adapter.name] = adapter
