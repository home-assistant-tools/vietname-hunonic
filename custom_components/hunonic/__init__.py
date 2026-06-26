"""Integration Hunonic Smart Home cho Home Assistant."""

from __future__ import annotations

import logging

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import CONF_HOME_ID, CONF_PHONE, CONF_USER_ID, DOMAIN, PLATFORMS
from .coordinator import HunonicCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Khởi tạo integration từ configuration.yaml (không dùng)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate entry cũ (1-nhà, v1) → entry tài khoản (mọi nhà, v2)."""
    if entry.version < 2:
        data = {k: v for k, v in entry.data.items() if k != CONF_HOME_ID}
        new_unique = f"hunonic_account_{entry.data.get(CONF_USER_ID) or entry.data.get(CONF_PHONE, '')}"
        hass.config_entries.async_update_entry(
            entry, data=data, unique_id=new_unique, version=2,
            title=f"Hunonic — {entry.data.get(CONF_PHONE, '')}",
        )
        _LOGGER.info("Hunonic: migrate entry %s → tài khoản (mọi nhà)", entry.entry_id)
    return True


def _register_home_hubs(hass: HomeAssistant, entry: ConfigEntry, devices: list) -> None:
    """Đăng ký 1 'trạm trung chuyển' (device hub) cho mỗi nhà để gom thiết bị."""
    reg = dr.async_get(hass)
    seen: set[str] = set()
    for d in devices:
        hid = str(d.get("home_id", ""))
        if not hid or hid in seen:
            continue
        seen.add(hid)
        reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"home_{hid}")},
            name=str(d.get("home_name") or f"Nhà {hid}"),
            manufacturer="Hunonic",
            model="Trạm trung chuyển (Nhà)",
            # SERVICE = hub gom thiết bị, KHÔNG bị HA xóa dù không có entity riêng.
            entry_type=dr.DeviceEntryType.SERVICE,
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Khởi tạo integration từ config entry được tạo bởi config_flow."""
    hass.data.setdefault(DOMAIN, {})

    # Tạo aiohttp session dùng chung cho REST API
    session = aiohttp.ClientSession()

    coordinator = HunonicCoordinator(hass, session, dict(entry.data))

    # Thực hiện lần poll đầu tiên — ném lỗi nếu không kết nối được
    await coordinator.async_config_entry_first_refresh()

    # Đăng ký hub cho từng nhà (để thiết bị gom theo nhà).
    _register_home_hubs(hass, entry, (coordinator.data or {}).get("devices", []))

    # Kết nối MQTT nền sau khi đã có danh sách thiết bị
    hass.async_create_task(coordinator.async_setup_mqtt())

    # Lưu coordinator để các platform sử dụng
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward setup sang tất cả platform (switch, cover, fan, light, sensor)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    homes = {str(d.get("home_id")) for d in (coordinator.data or {}).get("devices", []) if d.get("home_id")}
    _LOGGER.info("Hunonic integration đã khởi tạo: %d nhà", len(homes))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Gỡ integration và dọn dẹp tài nguyên."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unloaded:
        coordinator: HunonicCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        # Ngắt MQTT (đồng bộ)
        coordinator.shutdown_mqtt()
        # Đóng HTTP session
        await coordinator._session.close()
        _LOGGER.info("Hunonic integration đã gỡ: %s", entry.title)

    return unloaded
