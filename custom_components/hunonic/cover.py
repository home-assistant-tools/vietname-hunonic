"""Cổng và cửa cuốn Hunonic cho Home Assistant."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DOOR_TYPES, GATE_HUB_TYPES, GATE_TYPES
from .coordinator import HunonicCoordinator
from .entity_setup import setup_entities

_LOGGER = logging.getLogger(__name__)

# ── Action codes ──────────────────────────────────────────────────────────────
# Gate / GateHub
GATE_OPEN = 1
GATE_CLOSE = 2
GATE_STOP = 3

# Door (sdoor*)
DOOR_OPEN = 1
DOOR_CLOSE = 2
DOOR_STOP = 3
DOOR_LOCK = 4
DOOR_UNLOCK = 5


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Thiết lập cover entities (tự thêm thiết bị mới khi danh sách thay đổi)."""
    def _build(coordinator: HunonicCoordinator, device: dict[str, Any]):
        rt: str = device.get("root_type", "")
        if rt in GATE_HUB_TYPES:
            return [HunonicGateHub(coordinator, device)]
        if rt in GATE_TYPES:
            return [HunonicGate(coordinator, device)]
        if rt in DOOR_TYPES:
            return [HunonicDoor(coordinator, device)]
        return []

    setup_entities(hass, entry, async_add_entities, _build)


class _HunonicCoverBase(CoordinatorEntity[HunonicCoordinator], CoverEntity):
    """Base class dùng chung cho Gate Hub, Gate và Door."""

    def __init__(self, coordinator: HunonicCoordinator, device: dict[str, Any]) -> None:
        super().__init__(coordinator)
        self._device = device
        self._device_id: str = str(device.get("id", ""))
        self._root_id: str = str(device.get("root_id", ""))
        self._root_type: str = str(device.get("root_type", ""))

    @property
    def unique_id(self) -> str:
        return f"hunonic_cover_{self._device_id}"

    @property
    def name(self) -> str:
        return str(self._device.get("name", f"Cover {self._device_id}"))

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

    @property
    def current_cover_position(self) -> int | None:
        """Vị trí hiện tại (0=đóng, 100=mở hoàn toàn)."""
        # Ưu tiên MQTT state
        state = self.coordinator.get_device_state(self._root_id)
        for key in ("pcn", "position", "pos"):
            val = state.get(key)
            if val is not None:
                try:
                    return int(val)
                except (TypeError, ValueError):
                    pass

        # Fallback REST API
        raw = self.coordinator.get_device_raw(self._device_id)
        for key in ("pcn", "position"):
            val = raw.get(key)
            if val is not None:
                try:
                    return int(val)
                except (TypeError, ValueError):
                    pass

        return None

    @property
    def is_closed(self) -> bool | None:
        """True nếu cover đang đóng hoàn toàn (position=0)."""
        pos = self.current_cover_position
        if pos is not None:
            return pos == 0
        return None

    @property
    def is_opening(self) -> bool | None:
        """True nếu đang mở (đọc từ state nếu có)."""
        state = self.coordinator.get_device_state(self._root_id)
        moving = state.get("moving") or state.get("status")
        if moving == "opening":
            return True
        return None

    @property
    def is_closing(self) -> bool | None:
        """True nếu đang đóng."""
        state = self.coordinator.get_device_state(self._root_id)
        moving = state.get("moving") or state.get("status")
        if moving == "closing":
            return True
        return None


class HunonicGateHub(_HunonicCoverBase):
    """Cổng điều khiển qua Hub (gatehun / gatehuwf).

    Hub nhận lệnh qua topicPubGateway với code 200 và gate_address.
    """

    _attr_device_class = CoverDeviceClass.GARAGE
    _attr_supported_features = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Mở cổng qua gateway topic."""
        payload = {
            "u": self.coordinator._user_id,
            self._root_type: 200,
            "gate_address": GATE_OPEN,
            "value": 1,
            "src": 1,
        }
        await self.coordinator.async_control_device(
            self._device, payload, use_gateway=True
        )

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Đóng cổng qua gateway topic."""
        payload = {
            "u": self.coordinator._user_id,
            self._root_type: 200,
            "gate_address": GATE_CLOSE,
            "value": 1,
            "src": 1,
        }
        await self.coordinator.async_control_device(
            self._device, payload, use_gateway=True
        )

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Dừng cổng."""
        payload = {
            "u": self.coordinator._user_id,
            self._root_type: 200,
            "gate_address": GATE_STOP,
            "value": 1,
            "src": 1,
        }
        await self.coordinator.async_control_device(
            self._device, payload, use_gateway=True
        )


class HunonicGate(_HunonicCoverBase):
    """Cổng tự động trực tiếp (gate / gatev2 / wsgate)."""

    _attr_device_class = CoverDeviceClass.GARAGE
    _attr_supported_features = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._send_gate(GATE_OPEN)

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._send_gate(GATE_CLOSE)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self._send_gate(GATE_STOP)

    async def _send_gate(self, action: int) -> None:
        payload = {
            "u": self.coordinator._user_id,
            self._root_type: 1,
            "src": 1,
            "action": action,
        }
        await self.coordinator.async_control_device(self._device, payload)


class HunonicDoor(_HunonicCoverBase):
    """Cửa cuốn thông minh (sdoor2 - sdoor12).

    Hỗ trợ mở/đóng/dừng/đặt vị trí và khóa/mở khóa.
    """

    _attr_device_class = CoverDeviceClass.SHUTTER
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._send_door(DOOR_OPEN)

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._send_door(DOOR_CLOSE)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self._send_door(DOOR_STOP)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Đặt vị trí cửa (0=đóng, 100=mở)."""
        pos: int = int(kwargs.get("position", 0))
        payload = {
            "sdr": DOOR_OPEN if pos > 0 else DOOR_CLOSE,
            "u": self.coordinator._user_id,
            "src": 1,
            "pcn": pos,
        }
        await self.coordinator.async_control_device(self._device, payload)

    async def _send_door(self, action: int) -> None:
        """Gửi lệnh action đến cửa cuốn."""
        payload = {
            "sdr": action,
            "u": self.coordinator._user_id,
            "src": 1,
        }
        await self.coordinator.async_control_device(self._device, payload)
