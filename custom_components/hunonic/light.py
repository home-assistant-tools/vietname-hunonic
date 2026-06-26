"""Đèn thông minh Hunonic cho Home Assistant."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LED_TYPES
from .coordinator import HunonicCoordinator
from .entity_setup import setup_entities

_LOGGER = logging.getLogger(__name__)

# Action codes cho LED Hunonic
LIGHT_ON = 1
LIGHT_OFF = 2

# Thiết bị hỗ trợ dimmer (điều chỉnh độ sáng)
_DIMMER_TYPES = frozenset({"dled", "duhalled", "radav1", "duhal"})

# Thiết bị đèn LED RGB (màu sắc)
_RGB_TYPES: frozenset[str] = frozenset()  # Cập nhật khi có hardware data


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Thiết lập light entities (tự thêm thiết bị mới khi danh sách thay đổi)."""
    def _build(coordinator: HunonicCoordinator, device: dict[str, Any]):
        if device.get("root_type") in LED_TYPES:
            return [HunonicLight(coordinator, device)]
        return []

    setup_entities(hass, entry, async_add_entities, _build)


class HunonicLight(CoordinatorEntity[HunonicCoordinator], LightEntity):
    """Đèn LED Hunonic.

    Hỗ trợ:
    - Bật/tắt (tất cả LED types)
    - Điều chỉnh độ sáng cho dled, duhalled, radav1, duhal
    """

    def __init__(self, coordinator: HunonicCoordinator, device: dict[str, Any]) -> None:
        super().__init__(coordinator)
        self._device = device
        self._device_id: str = str(device.get("id", ""))
        self._root_id: str = str(device.get("root_id", ""))
        self._root_type: str = str(device.get("root_type", ""))
        self._has_dimmer: bool = self._root_type in _DIMMER_TYPES

    @property
    def unique_id(self) -> str:
        return f"hunonic_light_{self._device_id}"

    @property
    def name(self) -> str:
        return str(self._device.get("name", f"Light {self._device_id}"))

    @property
    def device_info(self) -> DeviceInfo:
        info = DeviceInfo(
            identifiers={(DOMAIN, self._root_id)},
            name=str(self._device.get("name", self._device_id)),
            manufacturer="Hunonic",
            model=self._root_type,
        )
        hid = self._device.get("home_id")
        if hid:  # gom thiết bị dưới "trạm trung chuyển" của nhà
            info["via_device"] = (DOMAIN, f"home_{hid}")
        return info

    @property
    def color_mode(self) -> ColorMode:
        if self._has_dimmer:
            return ColorMode.BRIGHTNESS
        return ColorMode.ONOFF

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        return {self.color_mode}

    @property
    def available(self) -> bool:
        return self.coordinator.is_device_online(self._device_id)

    def _current_action(self) -> int | None:
        """Đọc action code hiện tại."""
        state = self.coordinator.get_device_state(self._root_id)
        for key in ("action", self._root_type, "value"):
            val = state.get(key)
            if val is not None:
                try:
                    return int(val)
                except (TypeError, ValueError):
                    pass
        raw = self.coordinator.get_device_raw(self._device_id)
        val = raw.get("value")
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                pass
        return None

    @property
    def is_on(self) -> bool:
        action = self._current_action()
        if action is None:
            return False
        # action lẻ = bật, chẵn = tắt (bao gồm LIGHT_OFF=2)
        return action % 2 == 1

    @property
    def brightness(self) -> int | None:
        """Độ sáng 0-255 (chỉ cho dimmer types)."""
        if not self._has_dimmer:
            return None
        state = self.coordinator.get_device_state(self._root_id)
        for key in ("brightness", "bri", "dim", "level"):
            val = state.get(key)
            if val is not None:
                try:
                    # Hunonic thường dùng 0-100, chuyển sang 0-255
                    level = int(val)
                    return min(255, int(level * 255 / 100))
                except (TypeError, ValueError):
                    pass
        raw = self.coordinator.get_device_raw(self._device_id)
        for key in ("brightness", "bri", "dim", "level"):
            val = raw.get(key)
            if val is not None:
                try:
                    level = int(val)
                    return min(255, int(level * 255 / 100))
                except (TypeError, ValueError):
                    pass
        return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Bật đèn, tuỳ chọn đặt độ sáng."""
        payload: dict[str, Any] = {
            self._root_type: 1,
            "u": self.coordinator._user_id,
            "act_id": 0,
            "action": LIGHT_ON,
            "src": 1,
        }

        if self._has_dimmer and ATTR_BRIGHTNESS in kwargs:
            # Chuyển 0-255 sang 0-100
            bri_255: int = int(kwargs[ATTR_BRIGHTNESS])
            bri_pct: int = min(100, int(bri_255 * 100 / 255))
            payload["brightness"] = bri_pct
            payload["bri"] = bri_pct

        await self.coordinator.async_control_device(self._device, payload)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Tắt đèn."""
        payload: dict[str, Any] = {
            self._root_type: 0,
            "u": self.coordinator._user_id,
            "act_id": 0,
            "action": LIGHT_OFF,
            "src": 1,
        }
        await self.coordinator.async_control_device(self._device, payload)
