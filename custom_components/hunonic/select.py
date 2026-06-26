"""Select cấu hình thiết bị Hunonic: Khi cấp điện + Khóa công tắc.

Lệnh reverse từ app (MITM, mã hóa raw key/iv, publish tới topicsub):
- Khi cấp điện: {"<root_type>":121, "po":<0|1|2>, "u":<uid>}
- Khóa công tắc: {"u":<uid>, "index":0, "lock":<0..3>, "<root_type>":133}
Cấu hình theo TỪNG thiết bị vật lý (root_id) — chung mọi nút. Chỉ tạo ở kênh 1.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LED_TYPES, SWITCH_TYPES
from .coordinator import HunonicCoordinator
from .entity_setup import setup_entities

_LOGGER = logging.getLogger(__name__)

# Loại thiết bị có cấu hình cấp điện/khóa (công tắc + đèn LED tích hợp công tắc).
_CFG_TYPES = frozenset(list(SWITCH_TYPES) + list(LED_TYPES))

# Nhãn → giá trị. (Nhãn theo app; thứ tự giá trị một phần SUY LUẬN — xác minh thêm.)
POWER_ON_OPTIONS: dict[str, int] = {"Tắt": 0, "Bật": 1, "Giữ nguyên": 2}
LOCK_OPTIONS: dict[str, int] = {
    "Không khóa": 0,
    "Khóa trên app": 1,
    "Khóa ứng dụng": 2,
    "Khóa trên app và ứng dụng": 3,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Thiết lập select cấu hình (tự thêm thiết bị mới)."""
    def _build(coordinator: HunonicCoordinator, device: dict[str, Any]):
        if (
            device.get("root_type") in _CFG_TYPES
            and str(device.get("index_in_root", "1")) == "1"
        ):
            return [
                HunonicPowerOnSelect(coordinator, device),
                HunonicLockSelect(coordinator, device),
            ]
        return []

    setup_entities(hass, entry, async_add_entities, _build)


class _HunonicConfigSelect(CoordinatorEntity[HunonicCoordinator], SelectEntity):
    """Base select cấu hình — cấp thiết bị (root_id)."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: HunonicCoordinator, device: dict[str, Any]) -> None:
        super().__init__(coordinator)
        self._device = device
        self._device_id = str(device.get("id", ""))
        self._root_id = str(device.get("root_id", ""))
        self._root_type = str(device.get("root_type", ""))

    @property
    def device_info(self) -> DeviceInfo:
        info = DeviceInfo(
            identifiers={(DOMAIN, self._root_id)},
            name=str(self._device.get("name", self._device_id)),
            manufacturer="Hunonic",
            model=self._root_type,
        )
        hid = self._device.get("home_id")
        if hid:
            info["via_device"] = (DOMAIN, f"home_{hid}")
        return info

    @property
    def available(self) -> bool:
        return self.coordinator.is_device_online(self._device_id)

    @property
    def _uid(self) -> int:
        try:
            return int(self.coordinator._user_id or 0)
        except (TypeError, ValueError):
            return 0


class HunonicPowerOnSelect(_HunonicConfigSelect, RestoreEntity):
    """Trạng thái khi cấp điện (code 121).

    Hunonic KHÔNG trả field nào để đọc lại trạng thái này (đã kiểm tra
    listDeviceByHome + getMultiDeviceInfo — chỉ có block_control cho khóa). Vì vậy
    đây là assumed-state: nhớ giá trị người dùng đã chọn qua HA (RestoreEntity) để
    không hiện 'unknown' sau mỗi lần khởi động lại.
    """

    _attr_icon = "mdi:power-plug"
    _attr_options = list(POWER_ON_OPTIONS)

    def __init__(self, coordinator: HunonicCoordinator, device: dict[str, Any]) -> None:
        super().__init__(coordinator, device)
        self._cur: str | None = None

    async def async_added_to_hass(self) -> None:
        """Khôi phục lựa chọn lần trước (vì API không đọc được)."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in POWER_ON_OPTIONS:
            self._cur = last.state

    @property
    def unique_id(self) -> str:
        return f"hunonic_{self._root_id}_power_on"

    @property
    def name(self) -> str:
        return f"{self._device.get('name', self._device_id)} - Khi cấp điện"

    @property
    def current_option(self) -> str | None:
        return self._cur

    async def async_select_option(self, option: str) -> None:
        po = POWER_ON_OPTIONS[option]
        await self.coordinator.async_control_device(
            self._device, {self._root_type: 121, "po": po, "u": self._uid}
        )
        self._cur = option
        self.async_write_ha_state()


class HunonicLockSelect(_HunonicConfigSelect):
    """Khóa công tắc (code 133). Đọc trạng thái hiện tại từ `block_control`."""

    _attr_icon = "mdi:lock"
    _attr_options = list(LOCK_OPTIONS)

    @property
    def unique_id(self) -> str:
        return f"hunonic_{self._root_id}_lock"

    @property
    def name(self) -> str:
        return f"{self._device.get('name', self._device_id)} - Khóa công tắc"

    @property
    def current_option(self) -> str | None:
        raw = self.coordinator.get_device_raw(self._device_id)
        bc = str(raw.get("block_control", "0"))
        for label, val in LOCK_OPTIONS.items():
            if str(val) == bc:
                return label
        return None

    async def async_select_option(self, option: str) -> None:
        lock = LOCK_OPTIONS[option]
        await self.coordinator.async_control_device(
            self._device,
            {"u": self._uid, "index": 0, "lock": lock, self._root_type: 133},
        )
        self.async_write_ha_state()
