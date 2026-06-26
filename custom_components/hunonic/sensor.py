"""Sensor trạng thái thiết bị Hunonic cho Home Assistant."""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DOOR_TYPES, GATE_HUB_TYPES, GATE_TYPES, METER_TYPES
from .coordinator import HunonicCoordinator
from .entity_setup import setup_entities

_LOGGER = logging.getLogger(__name__)

# Root types có thể đo công suất điện
_POWER_MEASURE_TYPES = frozenset({"wsm", "swinput", "swinputv2"})

# Root types cổng/cửa để tạo sensor trạng thái riêng
_COVER_TYPES = frozenset(GATE_HUB_TYPES + GATE_TYPES + DOOR_TYPES)

# Root types công tơ điện
_METER_TYPES = frozenset(METER_TYPES)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Thiết lập sensor entities (tự thêm thiết bị mới khi danh sách thay đổi)."""
    def _build(coordinator: HunonicCoordinator, device: dict[str, Any]):
        root_type: str = device.get("root_type", "")
        ents: list[SensorEntity] = [
            # Mọi thiết bị đều có sensor kết nối online/offline
            HunonicConnectivitySensor(coordinator, device)
        ]
        if root_type in _COVER_TYPES:
            ents.append(HunonicCoverPositionSensor(coordinator, device))
        # Công suất tức thời (Watt): thiết bị đo điện chuyên dụng + công tơ (meter
        # đọc từ data_extra.power_current).
        if root_type in _POWER_MEASURE_TYPES or root_type in _METER_TYPES:
            ents.append(HunonicPowerSensor(coordinator, device))
        if root_type in _METER_TYPES:
            ents.append(HunonicMeterEnergySensor(coordinator, device, prev=False))
            ents.append(HunonicMeterEnergySensor(coordinator, device, prev=True))
            ents.append(HunonicMeterCostSensor(coordinator, device, prev=False))
            ents.append(HunonicMeterCostSensor(coordinator, device, prev=True))
        # Sensor chẩn đoán cấp THIẾT BỊ (chung mọi nút) — chỉ tạo 1 lần ở kênh 1.
        if str(device.get("index_in_root", "1")) == "1":
            ents.append(HunonicFirmwareSensor(coordinator, device))
            ents.append(HunonicMacSensor(coordinator, device))
            ents.append(HunonicOfflineNotifySensor(coordinator, device))
        return ents

    setup_entities(hass, entry, async_add_entities, _build)


class _HunonicSensorBase(CoordinatorEntity[HunonicCoordinator], SensorEntity):
    """Base class dùng chung cho sensor Hunonic."""

    def __init__(self, coordinator: HunonicCoordinator, device: dict[str, Any]) -> None:
        super().__init__(coordinator)
        self._device = device
        self._device_id: str = str(device.get("id", ""))
        self._root_id: str = str(device.get("root_id", ""))
        self._root_type: str = str(device.get("root_type", ""))

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


class HunonicConnectivitySensor(_HunonicSensorBase):
    """Sensor theo dõi trạng thái online/offline của thiết bị."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["online", "offline"]
    _attr_icon = "mdi:lan-connect"

    @property
    def unique_id(self) -> str:
        return f"hunonic_sensor_{self._device_id}_status"

    @property
    def name(self) -> str:
        device_name = self._device.get("name", self._device_id)
        return f"{device_name} - Kết nối"

    @property
    def native_value(self) -> str:
        # Dùng is_device_online (field `state` — đã kiểm chứng đáng tin).
        return "online" if self.coordinator.is_device_online(self._device_id) else "offline"

    @property
    def icon(self) -> str:
        return (
            "mdi:lan-connect"
            if self.native_value == "online"
            else "mdi:lan-disconnect"
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Thêm thông tin thiết bị vào attributes."""
        raw = self.coordinator.get_device_raw(self._device_id)
        return {
            "device_type": self._root_type,
            "root_id": self._root_id,
            "fw_version": raw.get("fw_version", raw.get("firmware", "")),
            "ip_address": raw.get("ip", raw.get("ip_address", "")),
        }


class HunonicCoverPositionSensor(_HunonicSensorBase):
    """Sensor hiển thị vị trí (%) của cổng/cửa."""

    _attr_device_class = SensorDeviceClass.POWER_FACTOR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:garage"

    @property
    def unique_id(self) -> str:
        return f"hunonic_sensor_{self._device_id}_position"

    @property
    def name(self) -> str:
        device_name = self._device.get("name", self._device_id)
        return f"{device_name} - Vị trí"

    @property
    def native_value(self) -> int | None:
        """Vị trí hiện tại (0=đóng, 100=mở hoàn toàn)."""
        state = self.coordinator.get_device_state(self._root_id)
        for key in ("pcn", "position", "pos"):
            val = state.get(key)
            if val is not None:
                try:
                    return int(val)
                except (TypeError, ValueError):
                    pass

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
    def icon(self) -> str:
        val = self.native_value
        if val is None:
            return "mdi:garage-alert"
        if val == 0:
            return "mdi:garage"
        if val == 100:
            return "mdi:garage-open"
        return "mdi:garage-variant"


class HunonicPowerSensor(_HunonicSensorBase):
    """Sensor đo công suất tiêu thụ (Watt) cho các thiết bị đo điện."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_icon = "mdi:flash"

    @property
    def unique_id(self) -> str:
        return f"hunonic_sensor_{self._device_id}_power"

    @property
    def name(self) -> str:
        device_name = self._device.get("name", self._device_id)
        return f"{device_name} - Công suất"

    @property
    def native_value(self) -> float | None:
        """Công suất tiêu thụ tính bằng Watt."""
        state = self.coordinator.get_device_state(self._root_id)
        for key in ("power", "watt", "w", "p"):
            val = state.get(key)
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    pass

        raw = self.coordinator.get_device_raw(self._device_id)
        for key in ("power", "watt", "w", "power_current"):
            val = raw.get(key)
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    pass

        # Công tơ (atmwifi/elmeter): công suất tức thời nằm trong data_extra.
        data_extra = raw.get("data_extra")
        if isinstance(data_extra, dict):
            val = data_extra.get("power_current")
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    pass
        return None


class _HunonicMeterBase(_HunonicSensorBase):
    """Base cho sensor công tơ điện — đọc số liệu từ field `root_extra` (REST).

    `root_extra` (chuỗi JSON) chứa: power_of_month, money_of_month,
    power_of_prev_month, money_of_prev_month. Poll lại mỗi chu kỳ coordinator.
    """

    def _root_extra(self) -> dict[str, Any]:
        raw = self.coordinator.get_device_raw(self._device_id)
        extra = raw.get("root_extra")
        if isinstance(extra, str):
            try:
                return json.loads(extra)
            except (ValueError, TypeError):
                return {}
        return extra if isinstance(extra, dict) else {}


class HunonicMeterEnergySensor(_HunonicMeterBase):
    """Điện năng tiêu thụ tháng này / tháng trước (kWh)."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:lightning-bolt"

    def __init__(
        self, coordinator: HunonicCoordinator, device: dict[str, Any], prev: bool
    ) -> None:
        super().__init__(coordinator, device)
        self._prev = prev
        self._key = "power_of_prev_month" if prev else "power_of_month"

    @property
    def unique_id(self) -> str:
        suffix = "energy_prev_month" if self._prev else "energy_month"
        return f"hunonic_sensor_{self._device_id}_{suffix}"

    @property
    def name(self) -> str:
        device_name = self._device.get("name", self._device_id)
        label = "Điện năng tháng trước" if self._prev else "Điện năng tháng này"
        return f"{device_name} - {label}"

    @property
    def native_value(self) -> float | None:
        val = self._root_extra().get(self._key)
        if val is None:
            return None
        try:
            return round(float(val), 2)
        except (TypeError, ValueError):
            return None


class HunonicMeterCostSensor(_HunonicMeterBase):
    """Tiền điện tháng này / tháng trước (VND)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "VND"
    _attr_icon = "mdi:cash"

    def __init__(
        self, coordinator: HunonicCoordinator, device: dict[str, Any], prev: bool
    ) -> None:
        super().__init__(coordinator, device)
        self._prev = prev
        self._key = "money_of_prev_month" if prev else "money_of_month"

    @property
    def unique_id(self) -> str:
        suffix = "cost_prev_month" if self._prev else "cost_month"
        return f"hunonic_sensor_{self._device_id}_{suffix}"

    @property
    def name(self) -> str:
        device_name = self._device.get("name", self._device_id)
        label = "Tiền điện tháng trước" if self._prev else "Tiền điện tháng này"
        return f"{device_name} - {label}"

    @property
    def native_value(self) -> int | None:
        val = self._root_extra().get(self._key)
        if val is None:
            return None
        try:
            return int(float(val))
        except (TypeError, ValueError):
            return None


# ── Sensor chẩn đoán cấp thiết bị (Thông tin chung / cấu hình — read-only) ──────
# Lấy từ field API của thiết bị (per root_id). Phần GHI (đổi cấu hình) cần MITM.

class _HunonicDiagBase(_HunonicSensorBase):
    """Base cho sensor chẩn đoán (đặt vào nhóm 'Chẩn đoán')."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC


class HunonicFirmwareSensor(_HunonicDiagBase):
    """Phiên bản phần cứng/firmware (field `version`)."""

    _attr_icon = "mdi:chip"

    @property
    def unique_id(self) -> str:
        return f"hunonic_{self._root_id}_fw"

    @property
    def name(self) -> str:
        return f"{self._device.get('name', self._device_id)} - Phiên bản"

    @property
    def native_value(self) -> str | None:
        raw = self.coordinator.get_device_raw(self._device_id)
        v = raw.get("version")
        return str(v) if v not in (None, "") else None


class HunonicMacSensor(_HunonicDiagBase):
    """Địa chỉ MAC Bluetooth (root_extra.mac_bt)."""

    _attr_icon = "mdi:bluetooth"

    @property
    def unique_id(self) -> str:
        return f"hunonic_{self._root_id}_mac_bt"

    @property
    def name(self) -> str:
        return f"{self._device.get('name', self._device_id)} - MAC Bluetooth"

    @property
    def native_value(self) -> str | None:
        raw = self.coordinator.get_device_raw(self._device_id)
        extra = raw.get("root_extra")
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except (ValueError, TypeError):
                extra = {}
        if isinstance(extra, dict):
            return extra.get("mac_bt") or None
        return None


class HunonicOfflineNotifySensor(_HunonicDiagBase):
    """Thông báo khi thiết bị mất kết nối (field `notify_offline`)."""

    _attr_icon = "mdi:bell-alert"

    @property
    def unique_id(self) -> str:
        return f"hunonic_{self._root_id}_notify_offline"

    @property
    def name(self) -> str:
        return f"{self._device.get('name', self._device_id)} - Thông báo offline"

    @property
    def native_value(self) -> str:
        raw = self.coordinator.get_device_raw(self._device_id)
        return "Bật" if str(raw.get("notify_offline", "0")) == "1" else "Tắt"
