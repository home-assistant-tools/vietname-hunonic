"""Quạt thông minh Hunonic cho Home Assistant."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, FAN_TYPES
from .coordinator import HunonicCoordinator
from .entity_setup import setup_entities

_LOGGER = logging.getLogger(__name__)

# ── Action codes Hunonic quạt ─────────────────────────────────────────────────
# action = 1 → bật tốc độ thấp
# action = 2 → tắt
# action = 3 → tốc độ trung bình
# action = 5 → tốc độ cao
FAN_ACTION_OFF = 2
FAN_ACTION_LOW = 1
FAN_ACTION_MED = 3
FAN_ACTION_HIGH = 5

# Preset modes
PRESET_LOW = "low"
PRESET_MED = "medium"
PRESET_HIGH = "high"

_PRESET_TO_ACTION: dict[str, int] = {
    PRESET_LOW: FAN_ACTION_LOW,
    PRESET_MED: FAN_ACTION_MED,
    PRESET_HIGH: FAN_ACTION_HIGH,
}

_ACTION_TO_PRESET: dict[int, str] = {
    FAN_ACTION_LOW: PRESET_LOW,
    FAN_ACTION_MED: PRESET_MED,
    FAN_ACTION_HIGH: PRESET_HIGH,
}

# Phần trăm tương ứng với preset
_PRESET_TO_PCT: dict[str, int] = {
    PRESET_LOW: 33,
    PRESET_MED: 66,
    PRESET_HIGH: 100,
}


def _pct_to_preset(pct: int) -> str:
    """Chuyển phần trăm (1-100) sang preset name."""
    if pct <= 33:
        return PRESET_LOW
    if pct <= 66:
        return PRESET_MED
    return PRESET_HIGH


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Thiết lập fan entities (tự thêm thiết bị mới khi danh sách thay đổi)."""
    def _build(coordinator: HunonicCoordinator, device: dict[str, Any]):
        if device.get("root_type") in FAN_TYPES:
            return [HunonicFan(coordinator, device)]
        return []

    setup_entities(hass, entry, async_add_entities, _build)


class HunonicFan(CoordinatorEntity[HunonicCoordinator], FanEntity):
    """Quạt Hunonic hỗ trợ bật/tắt, 3 mức tốc độ và percentage."""

    _attr_supported_features = (
        FanEntityFeature.PRESET_MODE
        | FanEntityFeature.SET_SPEED
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )
    _attr_preset_modes = [PRESET_LOW, PRESET_MED, PRESET_HIGH]

    def __init__(self, coordinator: HunonicCoordinator, device: dict[str, Any]) -> None:
        super().__init__(coordinator)
        self._device = device
        self._device_id: str = str(device.get("id", ""))
        self._root_id: str = str(device.get("root_id", ""))
        self._root_type: str = str(device.get("root_type", ""))
        self._last_preset: str = PRESET_MED  # nhớ tốc độ cuối khi tắt/bật lại

    @property
    def unique_id(self) -> str:
        return f"hunonic_fan_{self._device_id}"

    @property
    def name(self) -> str:
        return str(self._device.get("name", f"Fan {self._device_id}"))

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
    def available(self) -> bool:
        return self.coordinator.is_device_online(self._device_id)

    def _current_action(self) -> int | None:
        """Đọc action code hiện tại từ MQTT state hoặc REST API."""
        state = self.coordinator.get_device_state(self._root_id)
        for key in ("action", self._root_type, "value"):
            val = state.get(key)
            if val is not None:
                try:
                    return int(val)
                except (TypeError, ValueError):
                    pass

        raw = self.coordinator.get_device_raw(self._device_id)
        for key in ("action", "value"):
            val = raw.get(key)
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
        return action != FAN_ACTION_OFF and action != 0

    @property
    def preset_mode(self) -> str | None:
        """Trả về preset hiện tại (low/medium/high) hoặc None nếu tắt."""
        if not self.is_on:
            return None
        action = self._current_action()
        if action is not None:
            return _ACTION_TO_PRESET.get(action)
        return None

    @property
    def percentage(self) -> int | None:
        """Trả về tốc độ hiện tại (0-100%)."""
        if not self.is_on:
            return 0
        preset = self.preset_mode
        if preset:
            return _PRESET_TO_PCT[preset]
        return None

    @property
    def speed_count(self) -> int:
        return 3

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Bật quạt, tuỳ chọn đặt tốc độ."""
        if preset_mode and preset_mode in _PRESET_TO_ACTION:
            target = preset_mode
        elif percentage is not None and percentage > 0:
            target = _pct_to_preset(percentage)
        else:
            target = self._last_preset

        self._last_preset = target
        await self._send_action(_PRESET_TO_ACTION[target])

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Tắt quạt."""
        # Lưu tốc độ hiện tại trước khi tắt
        if self.preset_mode:
            self._last_preset = self.preset_mode
        await self._send_action(FAN_ACTION_OFF)

    async def async_set_percentage(self, percentage: int) -> None:
        """Đặt tốc độ (%)."""
        if percentage == 0:
            await self.async_turn_off()
            return
        preset = _pct_to_preset(percentage)
        self._last_preset = preset
        await self._send_action(_PRESET_TO_ACTION[preset])

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Đặt tốc độ theo preset."""
        action = _PRESET_TO_ACTION.get(preset_mode, FAN_ACTION_MED)
        self._last_preset = preset_mode
        await self._send_action(action)

    async def _send_action(self, action: int) -> None:
        """Gửi lệnh action đến quạt."""
        payload = {
            self._root_type: 1 if action != FAN_ACTION_OFF else 0,
            "u": self.coordinator._user_id,
            "act_id": 0,
            "action": action,
            "src": 1,
        }
        await self.coordinator.async_control_device(self._device, payload)
