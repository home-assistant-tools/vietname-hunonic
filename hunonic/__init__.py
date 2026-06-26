"""
hunonic — Python client library for the Hunonic smart home platform.

Quick start::

    import asyncio
    import aiohttp
    from hunonic import HunonicAPI, HunonicMQTT

    async def main():
        async with aiohttp.ClientSession() as session:
            api = HunonicAPI(session=session)
            await api.request_otp("+84912345678")
            user = await api.login("+84912345678", "123456")

            homes = await api.get_homes()
            devices = await api.get_devices(int(homes[0].id))

            mqtt_info = await api.get_mqtt_info(devices[0].root_id)
            hm = HunonicMQTT(api)
            await hm.connect(
                host=mqtt_info["host"],
                port=int(mqtt_info.get("port", 1883)),
                username=mqtt_info["username"],
                password=mqtt_info["password"],
            )

            await hm.publish_command(devices[0], {"value": 1})
            await hm.disconnect()

    asyncio.run(main())
"""

from .api import HunonicAPI
from .crypto import decrypt_payload, derive_key, encrypt_payload
from .exceptions import (
    HunonicAuthError,
    HunonicConnectionError,
    HunonicDeviceError,
    HunonicError,
)
from .models import (
    Device,
    DeviceCategory,
    DeviceType,
    Home,
    Room,
    SceneCollection,
    User,
    get_category,
    is_door,
    is_gate,
    is_gate_hub,
    is_switch,
)
from .mqtt import HunonicMQTT

__all__ = [
    # API client
    "HunonicAPI",
    # MQTT client
    "HunonicMQTT",
    # Exceptions
    "HunonicError",
    "HunonicAuthError",
    "HunonicConnectionError",
    "HunonicDeviceError",
    # Models
    "User",
    "Home",
    "Room",
    "Device",
    "SceneCollection",
    # Enums
    "DeviceType",
    "DeviceCategory",
    # Helpers
    "get_category",
    "is_switch",
    "is_door",
    "is_gate",
    "is_gate_hub",
    # Crypto
    "derive_key",
    "encrypt_payload",
    "decrypt_payload",
]

__version__ = "0.1.0"
__author__ = "Hunonic"
