"""Công tắc Hunonic cho Home Assistant."""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SWITCH_TYPES
from .coordinator import HunonicCoordinator
from .entity_setup import setup_entities

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Thiết lập switch entities (tự thêm thiết bị mới khi danh sách thay đổi)."""
    def _build(coordinator: HunonicCoordinator, device: dict[str, Any]):
        if device.get("root_type") in SWITCH_TYPES:
            return [HunonicSwitch(coordinator, device)]
        return []

    setup_entities(hass, entry, async_add_entities, _build)


class HunonicSwitch(CoordinatorEntity[HunonicCoordinator], SwitchEntity):
    """Đại diện cho một kênh công tắc Hunonic.

    Hunonic switch dùng convention sau cho action code:
      - action = (2 * index_in_root - 1)  → BẬT kênh
      - action = (2 * index_in_root)       → TẮT kênh

    Ví dụ: kênh 1 → on=1, off=2 | kênh 2 → on=3, off=4 | kênh 3 → on=5, off=6
    """

    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator: HunonicCoordinator, device: dict[str, Any]) -> None:
        super().__init__(coordinator)
        self._device = device
        self._device_id: str = str(device.get("id", ""))
        self._root_id: str = str(device.get("root_id", ""))
        self._root_type: str = str(device.get("root_type", ""))
        # index_in_root là 1-based (kênh 1, 2, 3, ...)
        self._index: int = max(1, int(device.get("index_in_root", 1)))

    @property
    def unique_id(self) -> str:
        return f"hunonic_switch_{self._device_id}"

    @property
    def name(self) -> str:
        return str(self._device.get("name", f"Switch {self._device_id}"))

    @property
    def device_info(self) -> DeviceInfo:
        info = DeviceInfo(
            identifiers={(DOMAIN, self._root_id)},
            name=str(self._device.get("name", self._device_id)),
            manufacturer="Hunonic",
            model=self._root_type,
            sw_version=str(self._device.get("fw_version", "")),
        )
        hid = self._device.get("home_id")
        if hid:  # gom thiết bị dưới "trạm trung chuyển" của nhà
            info["via_device"] = (DOMAIN, f"home_{hid}")
        return info

    @property
    def is_on(self) -> bool:
        """Trạng thái bật/tắt.

        State realtime /ok có `action` mã hóa CẢ kênh + bật/tắt: kênh N → BẬT=2N-1,
        TẮT=2N. Suy ra: kênh = (action+1)//2, BẬT nếu action lẻ. Chỉ áp dụng nếu
        action thuộc đúng kênh này; nếu không, fallback `value` REST {"turn":1|2}.
        """
        # Trạng thái realtime TÁCH theo kênh (công tắc đa nút dùng chung root_id) —
        # tránh lỗi 'tắt nút này nút kia bật' do đọc chung 1 action.
        ch_on = self.coordinator.get_channel_state(self._root_id, self._index)
        if ch_on is not None:
            return ch_on

        # Fallback: value REST {"turn":1|2}. API trả `value` dạng CHUỖI JSON
        # ('{"turn":1}') nên parse trước khi đọc.
        raw = self.coordinator.get_device_raw(self._device_id)
        value = raw.get("value")
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                value = None
        if isinstance(value, dict):
            turn = value.get("turn")
            if turn is not None:
                try:
                    return int(turn) == 1
                except (TypeError, ValueError):
                    pass
        return False

    @property
    def available(self) -> bool:
        """Online theo field `state` (offline thì xám, không bấm 'ảo' được)."""
        return self.coordinator.is_device_online(self._device_id)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Bật đúng kênh này."""
        await self.coordinator.async_control_device(self._device, self._cmd(True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Tắt đúng kênh này."""
        await self.coordinator.async_control_device(self._device, self._cmd(False))

    def _cmd(self, on: bool) -> dict[str, Any]:
        """Payload điều khiển công tắc (đa kênh).

        Khác bản cũ (sai với công tắc đôi/ba): field `<root_type>` là HẰNG SỐ 0
        (SWITCH_CONTROL_DEVICE), còn KÊNH được mã hóa trong `action`:
          kênh N → BẬT = 2N-1, TẮT = 2N  (kênh1: 1/2, kênh2: 3/4, kênh3: 5/6).
        Code cũ để channel vào field + action 1/2 nên bật kênh 2/3 lại gửi nhầm
        thành lệnh kênh 1 ("bật nút này tắt nút kia").
        """
        action = (2 * self._index - 1) if on else (2 * self._index)
        return {
            "u": int(self.coordinator._user_id or 0),
            self._root_type: 0,  # SWITCH_CONTROL_DEVICE (hằng số), KHÔNG phải channel
            "act_id": 0,
            "action": action,
        }
