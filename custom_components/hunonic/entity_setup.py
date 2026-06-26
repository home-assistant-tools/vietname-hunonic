"""Tiện ích thiết lập entity + tự thêm thiết bị mới khi danh sách thay đổi.

Coordinator poll lại danh sách thiết bị mỗi chu kỳ. Nếu tài khoản Hunonic có
thiết bị mới, helper này phát hiện và thêm entity tương ứng **mà không cần
reload tích hợp** (reload vẫn hoạt động bình thường).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import HunonicCoordinator

# builder(coordinator, device) -> list entity cho 1 thiết bị (rỗng nếu không thuộc platform)
EntityBuilder = Callable[["HunonicCoordinator", dict[str, Any]], Iterable[Entity]]


def _device_key(device: dict[str, Any]) -> str:
    """Khóa định danh thiết bị, ổn định giữa các lần poll."""
    return (
        str(device.get("id", ""))
        or f"{device.get('root_id', '')}:{device.get('index_in_root', '')}"
    )


def setup_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    builder: EntityBuilder,
) -> None:
    """Thêm entity hiện có và đăng ký listener tự thêm thiết bị mới sau này."""
    coordinator: HunonicCoordinator = hass.data[DOMAIN][entry.entry_id]
    seen: set[str] = set()

    @callback
    def _discover() -> None:
        devices: list[dict[str, Any]] = (coordinator.data or {}).get("devices", [])
        new_entities: list[Entity] = []
        for device in devices:
            key = _device_key(device)
            if key in seen:
                continue
            ents = list(builder(coordinator, device))
            if ents:
                seen.add(key)
                new_entities.extend(ents)
        if new_entities:
            async_add_entities(new_entities)

    _discover()
    entry.async_on_unload(coordinator.async_add_listener(_discover))
