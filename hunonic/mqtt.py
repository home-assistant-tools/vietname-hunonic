"""
Async MQTT client wrapper for Hunonic smart home devices.

Uses paho-mqtt with asyncio integration via a background thread loop.

Requires:
    pip install paho-mqtt
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Callable, Optional

import paho.mqtt.client as mqtt

from .api import HunonicAPI
from .crypto import decrypt_payload, encrypt_payload
from .exceptions import HunonicConnectionError, HunonicDeviceError
from .models import Device

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

DeviceStateCallback = Callable[[Device, dict[str, Any]], None]
RawMessageCallback = Callable[[str, bytes], None]


class HunonicMQTT:
    """Asyncio-friendly MQTT client for Hunonic devices.

    The underlying paho client runs its own network loop in a background
    thread (``loop_start``).  All public methods are safe to ``await``
    from any asyncio coroutine.

    Example::

        api = HunonicAPI(session=session)
        # ... authenticate ...
        mqtt_info = await api.get_mqtt_info(device.root_id)

        hm = HunonicMQTT(api)
        await hm.connect(
            host=mqtt_info["host"],
            port=int(mqtt_info.get("port", 1883)),
            username=mqtt_info["username"],
            password=mqtt_info["password"],
        )

        async def on_state(device: Device, state: dict) -> None:
            print(device.name, state)

        hm.on_device_state(on_state)
        await hm.subscribe_device(device, on_state)

        await hm.publish_command(device, {"value": 1})
        ...
        await hm.disconnect()
    """

    def __init__(self, api: HunonicAPI) -> None:
        self._api = api
        self._client: Optional[mqtt.Client] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # topic -> Device mapping built by subscribe_device
        self._topic_device_map: dict[str, Device] = {}

        # Global device-state observers
        self._state_callbacks: list[DeviceStateCallback] = []

        # Per-topic callbacks registered via subscribe_device
        self._topic_callbacks: dict[str, list[DeviceStateCallback]] = {}

        self._connected = asyncio.Event()
        self._disconnected = asyncio.Event()
        self._disconnected.set()

    # ------------------------------------------------------------------
    # Paho callbacks (run in paho background thread)
    # ------------------------------------------------------------------

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: dict[str, Any],
        rc: int,
    ) -> None:
        if rc == 0:
            logger.info("MQTT connected (rc=0)")
            if self._loop:
                self._loop.call_soon_threadsafe(self._connected.set)
                self._loop.call_soon_threadsafe(self._disconnected.clear)
        else:
            logger.error("MQTT connection refused, rc=%s", rc)

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        rc: int,
    ) -> None:
        logger.info("MQTT disconnected (rc=%s)", rc)
        if self._loop:
            self._loop.call_soon_threadsafe(self._connected.clear)
            self._loop.call_soon_threadsafe(self._disconnected.set)

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: Any,
        msg: mqtt.MQTTMessage,
    ) -> None:
        topic: str = msg.topic
        payload_bytes: bytes = msg.payload

        device = self._topic_device_map.get(topic)
        if device is None:
            logger.debug("Received message on untracked topic: %s", topic)
            return

        # Attempt decryption; fall back to raw JSON
        try:
            raw = payload_bytes.decode("utf-8").strip()
            if raw.startswith("{"):
                state: dict[str, Any] = json.loads(raw)
            else:
                decrypted = decrypt_payload(raw, device.root_id)
                state = json.loads(decrypted)
        except Exception as exc:
            logger.warning(
                "Could not decode payload on topic %s: %s", topic, exc
            )
            return

        # Fire per-topic callbacks
        for cb in self._topic_callbacks.get(topic, []):
            if self._loop:
                self._loop.call_soon_threadsafe(
                    asyncio.ensure_future,
                    self._maybe_await(cb, device, state),
                )

        # Fire global callbacks
        for cb in self._state_callbacks:
            if self._loop:
                self._loop.call_soon_threadsafe(
                    asyncio.ensure_future,
                    self._maybe_await(cb, device, state),
                )

    @staticmethod
    async def _maybe_await(
        cb: Callable[..., Any], *args: Any
    ) -> None:
        """Call *cb* and await the result if it is a coroutine."""
        try:
            result = cb(*args)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            logger.exception("Exception in MQTT callback: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def connect(
        self,
        host: str,
        port: int = 1883,
        username: str = "",
        password: str = "",
        client_id_prefix: str = "",
        keepalive: int = 60,
    ) -> None:
        """Connect to the MQTT broker.

        Args:
            host: Broker hostname or IP address.
            port: Broker port (default 1883).
            username: MQTT username.
            password: MQTT password.
            client_id_prefix: Optional prefix for the generated client ID.
            keepalive: Keepalive interval in seconds.

        Raises:
            HunonicConnectionError: If the connection cannot be established
                within 30 seconds.
        """
        self._loop = asyncio.get_event_loop()

        client_id = f"{client_id_prefix}hunonic-{uuid.uuid4().hex[:8]}"
        self._client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)

        if username:
            self._client.username_pw_set(username, password)

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        self._connected.clear()
        self._disconnected.clear()

        try:
            self._client.connect(host, port, keepalive)
        except OSError as exc:
            raise HunonicConnectionError(
                f"Could not reach MQTT broker at {host}:{port}: {exc}"
            ) from exc

        self._client.loop_start()

        try:
            await asyncio.wait_for(self._connected.wait(), timeout=30)
        except asyncio.TimeoutError:
            self._client.loop_stop()
            raise HunonicConnectionError(
                f"Timed out waiting for MQTT connection to {host}:{port}"
            )

    async def disconnect(self) -> None:
        """Gracefully disconnect from the MQTT broker."""
        if self._client is None:
            return
        self._client.disconnect()
        try:
            await asyncio.wait_for(self._disconnected.wait(), timeout=10)
        except asyncio.TimeoutError:
            logger.warning("MQTT disconnect timed out — forcing stop.")
        self._client.loop_stop()
        self._client = None

    def on_device_state(self, callback: DeviceStateCallback) -> None:
        """Register a global callback that fires on every device state update.

        The callback signature is::

            def cb(device: Device, state: dict) -> None: ...

        or an ``async def`` coroutine with the same signature.

        Args:
            callback: The callable to register.
        """
        self._state_callbacks.append(callback)

    async def subscribe_device(
        self,
        device: Device,
        callback: Optional[DeviceStateCallback] = None,
    ) -> None:
        """Subscribe to state updates for *device*.

        Args:
            device: The :class:`~hunonic.models.Device` to subscribe to.
            callback: Optional per-device callback invoked on state updates.

        Raises:
            HunonicDeviceError: If the device has no subscription topic.
            HunonicConnectionError: If the MQTT client is not connected.
        """
        if not device.topicsub:
            raise HunonicDeviceError(
                f"Device '{device.name}' ({device.id}) has no topicsub."
            )
        if self._client is None or not self._connected.is_set():
            raise HunonicConnectionError(
                "MQTT client is not connected. Call connect() first."
            )

        topic = device.topicsub
        self._topic_device_map[topic] = device

        if callback is not None:
            self._topic_callbacks.setdefault(topic, []).append(callback)

        result, _ = self._client.subscribe(topic, qos=1)
        if result != mqtt.MQTT_ERR_SUCCESS:
            raise HunonicConnectionError(
                f"Failed to subscribe to topic '{topic}' (rc={result})."
            )
        logger.info("Subscribed to topic: %s", topic)

    async def publish_command(
        self, device: Device, payload: dict[str, Any]
    ) -> bool:
        """Publish an encrypted command to *device*.

        The *payload* dict is JSON-serialised, encrypted with the device's
        ``root_id`` via :func:`~hunonic.crypto.encrypt_payload`, and
        published to ``device.topicpub``.

        Args:
            device: Target device.
            payload: Command dictionary (e.g. ``{"value": 1}``).

        Returns:
            ``True`` if the message was queued successfully.

        Raises:
            HunonicDeviceError: If the device has no publish topic.
            HunonicConnectionError: If the MQTT client is not connected.
        """
        if not device.topicpub:
            raise HunonicDeviceError(
                f"Device '{device.name}' ({device.id}) has no topicpub."
            )
        if self._client is None or not self._connected.is_set():
            raise HunonicConnectionError(
                "MQTT client is not connected. Call connect() first."
            )

        raw_json = json.dumps(payload, separators=(",", ":"))
        encrypted = encrypt_payload(raw_json, device.root_id)

        info = self._client.publish(device.topicpub, encrypted, qos=1)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            logger.error(
                "Failed to publish to topic '%s' (rc=%s)", device.topicpub, info.rc
            )
            return False

        logger.debug("Published to %s: %s", device.topicpub, raw_json)
        return True

    async def publish_command_via_gateway(
        self, device: Device, payload: dict[str, Any]
    ) -> bool:
        """Publish a command through the gateway topic (``topicPubGateway``).

        Some devices (e.g. door/gate controllers) require commands to be
        routed via the gateway topic rather than the direct publish topic.

        Args:
            device: Target device.
            payload: Command dictionary.

        Returns:
            ``True`` if the message was queued successfully.
        """
        if not device.topicPubGateway:
            raise HunonicDeviceError(
                f"Device '{device.name}' ({device.id}) has no topicPubGateway."
            )
        if self._client is None or not self._connected.is_set():
            raise HunonicConnectionError(
                "MQTT client is not connected. Call connect() first."
            )

        raw_json = json.dumps(payload, separators=(",", ":"))
        encrypted = encrypt_payload(raw_json, device.root_id)

        info = self._client.publish(device.topicPubGateway, encrypted, qos=1)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            logger.error(
                "Failed to publish to gateway topic '%s' (rc=%s)",
                device.topicPubGateway,
                info.rc,
            )
            return False

        logger.debug(
            "Published (gateway) to %s: %s", device.topicPubGateway, raw_json
        )
        return True

    @property
    def is_connected(self) -> bool:
        """``True`` if the MQTT client is currently connected."""
        return self._connected.is_set()
