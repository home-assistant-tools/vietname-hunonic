"""DataUpdateCoordinator cho Hunonic - quản lý trạng thái và MQTT."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import timedelta
from typing import Any

import aiohttp
import paho.mqtt.client as paho

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    HunonicAPIClient,
    HunonicAuthError,
    HunonicError,
    decrypt_bytes_payload,
    decrypt_bytes_with_keyiv,
    decrypt_payload,
    decrypt_with_keyiv,
    encrypt_bytes_payload,
    encrypt_bytes_with_keyiv,
)
from .const import (
    CONF_HOME_ID,
    CONF_HOME_IDS,
    CONF_PASSWORD,
    CONF_PHONE,
    CONF_TOKEN_ID,
    CONF_USER_ID,
    DOMAIN,
    MQTT_PASSWORD,
    MQTT_RECONNECT_DELAY,
    MQTT_USERNAME,
    MQTT_WS_PATH,
    MQTT_WS_PORT,
    SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class HunonicCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Điều phối dữ liệu từ Hunonic cloud và MQTT.

    Luồng hoạt động:
    1. Poll REST API mỗi SCAN_INTERVAL giây qua _async_update_data().
    2. Sau lần refresh đầu tiên, async_setup_mqtt() kết nối broker MQTT.
    3. Khi nhận MQTT message → _handle_mqtt_message() cập nhật state tức thì.
    4. Các entity gọi async_control_device() để điều khiển thiết bị.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        entry_data: dict[str, Any],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry_data.get(CONF_USER_ID) or entry_data.get(CONF_PHONE, '')}",
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )
        self._session = session
        # 1 entry = 1 TÀI KHOẢN → nạp TẤT CẢ nhà (gồm nhà được share). home_id chỉ còn
        # để tương thích entry cũ (1-nhà); việc fetch dùng home_id rỗng = mọi nhà.
        self._home_id = str(entry_data.get(CONF_HOME_ID, ""))
        # Nhà được chọn (checkbox). Rỗng = nạp TẤT CẢ nhà của tài khoản.
        self._home_ids = [str(x) for x in (entry_data.get(CONF_HOME_IDS) or [])]
        self._user_id = str(entry_data.get(CONF_USER_ID, ""))
        # Lưu credential để tự đăng nhập lại khi token_id hết hạn.
        self._phone = str(entry_data.get(CONF_PHONE, ""))
        self._password = str(entry_data.get(CONF_PASSWORD, ""))
        self.api = HunonicAPIClient(session, token_id=str(entry_data[CONF_TOKEN_ID]))

        # MQTT state — thiết bị rải nhiều broker (PER-DEVICE), nên giữ NHIỀU client:
        #   _mqtt_clients: broker host -> paho client
        #   _device_brokers: topic-root -> DANH SÁCH broker được gán (primary + backup).
        #     Nối CẢ các broker để thiết bị ở broker nào trong cặp đều với tới.
        self._mqtt_clients: dict[str, paho.Client] = {}
        self._device_brokers: dict[str, list[str]] = {}
        # broker host -> tập topic đang subscribe (nguồn sự thật để re-subscribe khi
        # reconnect; cập nhật khi auto-tracking thêm topic/thiết bị mới).
        self._broker_topics: dict[str, set[str]] = {}
        self._mqtt_loop: asyncio.AbstractEventLoop | None = None

        # Indexes
        self._device_index: dict[str, dict[str, Any]] = {}  # device_id -> raw dict
        self._topic_index: dict[str, dict[str, Any]] = {}   # topicsub -> raw dict
        self._device_state: dict[str, dict[str, Any]] = {}  # root_id -> MQTT state
        # root_id -> {channel(1-based): on?} — TÁCH theo kênh để công tắc đa nút (dùng
        # CHUNG root_id) không đọc nhầm trạng thái của nhau. action: kênh=(a+1)//2, ON=a lẻ.
        self._channel_state: dict[str, dict[int, bool]] = {}
        self._first_refresh_done = False  # re-login 1 lần nếu fetch đầu rỗng (token stale)
        # Thời điểm (monotonic) lần cuối re-resolve broker — throttle auto-tracking.
        self._last_broker_resolve = 0.0
        self._broker_reresolve_interval = 600  # 10 phút: dò server/thiết bị mới

    # ── DataUpdateCoordinator ────────────────────────────────────────────────

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch tất cả thiết bị và kịch bản từ REST API.

        Ưu tiên API mobile (`get_devices_mobile`) vì trả topic PLAINTEXT + key/iv —
        đủ để điều khiển/giải mã MQTT. Nếu token không phải token_id mobile hợp lệ,
        fallback sang web API (`get_devices`, topic mã hóa).
        """
        try:
            devices = await self._fetch_devices()
        except HunonicAuthError as exc:
            # token_id hết hạn → đăng nhập lại bằng credential đã lưu rồi thử lại.
            if not await self._relogin():
                raise UpdateFailed(f"Token hết hạn, đăng nhập lại thất bại: {exc}") from exc
            try:
                devices = await self._fetch_devices()
            except HunonicError as exc2:
                raise UpdateFailed(f"Lỗi sau khi đăng nhập lại: {exc2}") from exc2
        except HunonicError as exc:
            raise UpdateFailed(f"Lỗi kết nối Hunonic: {exc}") from exc
        except aiohttp.ClientError as exc:
            raise UpdateFailed(f"Lỗi HTTP: {exc}") from exc

        # token_id stale đôi khi trả DANH SÁCH RỖNG mà KHÔNG báo lỗi (không phải
        # HunonicAuthError) → lần refresh đầu nếu rỗng thì đăng nhập lại 1 lần rồi
        # lấy lại. Chỉ làm 1 lần lúc khởi động để tránh login thừa với nhà rỗng thật.
        if not devices and not self._first_refresh_done and self._phone and self._password:
            if await self._relogin():
                try:
                    devices = await self._fetch_devices()
                except HunonicError:
                    pass
        self._first_refresh_done = True

        # Lọc theo nhà ĐƯỢC CHỌN (nếu có). Rỗng = giữ tất cả.
        if self._home_ids:
            sel = set(self._home_ids)
            devices = [d for d in devices if str(d.get("home_id", "")) in sel]

        # Scene theo TỪNG NHÀ (gộp). Lấy home_id từ thiết bị đã tag.
        scenes: list[dict[str, Any]] = []
        for hid in {str(d.get("home_id", "")) for d in devices if d.get("home_id")}:
            try:
                scenes.extend(await self.api.get_scenes(hid))
            except HunonicError:
                pass

        # Rebuild indexes. State realtime về trên topicpub (= topicsub + "/ok"),
        # nên index theo topicpub để tra cứu device khi nhận message.
        self._device_index = {str(d.get("id", "")): d for d in devices}
        self._topic_index = {
            d["topicpub"]: d for d in devices if d.get("topicpub")
        }

        # Thiết bị OFFLINE (state=2) → xóa channel_state MQTT cũ. Khi online lại,
        # is_on dùng ngay `value` REST tươi (đúng trạng thái thật) thay vì giá trị
        # MQTT cũ trước lúc offline — tránh hiển thị on/off sai sau reconnect.
        for d in devices:
            if str(d.get("state", "")) == "2":
                self._channel_state.pop(str(d.get("root_id", "")), None)

        # Auto-tracking: nếu MQTT đã chạy, định kỳ re-resolve broker để bắt SERVER MỚI
        # (Hunonic bổ sung) hoặc THIẾT BỊ MỚI được gán broker khác — nối thêm broker /
        # subscribe topic mới mà KHÔNG cần restart. Chạy nền để không chặn poll.
        if self._mqtt_clients and devices:
            now = time.monotonic()
            if now - self._last_broker_resolve >= self._broker_reresolve_interval:
                self._last_broker_resolve = now
                self.hass.async_create_task(self._ensure_brokers(devices))

        return {"devices": devices, "scenes": scenes}

    async def _fetch_devices(self) -> list[dict[str, Any]]:
        """Lấy thiết bị của TẤT CẢ nhà (home_id rỗng) — ưu tiên mobile (plaintext).

        Mobile `listDeviceOfHomeSelect` với home_id RỖNG trả mọi nhà của tài khoản
        (gồm nhà được share) trong 1 call — xác minh qua MITM app. Fallback web chỉ
        cho entry cũ còn home_id.
        """
        devices: list[dict[str, Any]] = []
        try:
            devices = await self.api.get_devices_mobile("")
        except HunonicAuthError:
            raise  # để _async_update_data xử lý đăng nhập lại
        except HunonicError as exc:
            _LOGGER.debug("Mobile API không dùng được (%s) — fallback web API", exc)
        if not devices and self._home_id:
            devices = await self.api.get_devices(self._home_id)
        return devices

    async def _relogin(self) -> bool:
        """Đăng nhập lại bằng SĐT+mật khẩu đã lưu để làm mới token_id."""
        if not self._phone or not self._password:
            return False
        try:
            await self.api.login_mobile(self._phone, self._password)
            _LOGGER.info("Hunonic: đã làm mới token_id sau khi hết hạn")
            return True
        except HunonicError as exc:
            _LOGGER.error("Đăng nhập lại thất bại: %s", exc)
            return False

    # ── MQTT Setup ───────────────────────────────────────────────────────────

    @staticmethod
    def _topic_root(topic: str) -> str:
        """topic 'u/<owner>/<root_id>/<ts>[/ok]' → lấy <root_id> (segment thứ 3)."""
        parts = topic.split("/")
        return parts[2] if len(parts) >= 3 else ""

    async def async_setup_mqtt(self) -> None:
        """Kết nối MQTT theo TỪNG BROKER (per-device).

        Mỗi thiết bị vật lý được getInfoMqtt gán broker riêng (rải khắp pool), nên
        gom thiết bị theo broker rồi mở MỘT kết nối cho mỗi broker (subscribe đúng
        topic của thiết bị thuộc broker đó). Đúng dù các broker có bridge hay không.
        """
        if not self.data or not self.data.get("devices"):
            _LOGGER.debug("Không có thiết bị — bỏ qua MQTT setup")
            return
        self._mqtt_loop = asyncio.get_running_loop()
        devices: list[dict[str, Any]] = self.data["devices"]

        # 1) Lấy broker cho từng topic-root qua getInfoMqtt.
        await self._resolve_brokers(devices)
        self._last_broker_resolve = time.monotonic()

        # 2) Gom topicpub theo broker.
        topics_by_broker = self._group_topics_by_broker(devices)
        if not topics_by_broker:
            _LOGGER.warning("Không có topic MQTT nào để subscribe")
            return

        _LOGGER.info(
            "Hunonic MQTT: kết nối %d broker — %s",
            len(topics_by_broker),
            {b: len(t) for b, t in topics_by_broker.items()},
        )
        # 3) Kết nối từng broker (song song).
        await asyncio.gather(
            *(self._connect_broker(b, t) for b, t in topics_by_broker.items())
        )

    def _group_topics_by_broker(
        self, devices: list[dict[str, Any]]
    ) -> dict[str, set[str]]:
        """Gom topicpub của *devices* theo broker (gồm cả backup của mỗi thiết bị)."""
        from .const import MQTT_BROKER

        topics_by_broker: dict[str, set[str]] = {}
        for d in devices:
            topic = d.get("topicpub")
            if not topic:
                continue
            brokers = self._device_brokers.get(self._topic_root(topic)) or [MQTT_BROKER]
            for broker in brokers:
                topics_by_broker.setdefault(broker, set()).add(topic)
        return topics_by_broker

    async def _ensure_brokers(self, devices: list[dict[str, Any]]) -> None:
        """Re-resolve broker rồi nối broker MỚI / subscribe topic mới (auto-tracking).

        Gọi định kỳ từ poll: bắt được khi Hunonic bổ sung SERVER mới (thiết bị được
        gán broker chưa từng nối) hoặc khi có THIẾT BỊ MỚI — đều xử lý mà không cần
        restart. Broker đã có sẵn thì chỉ subscribe thêm topic mới (nếu có).
        """
        try:
            await self._resolve_brokers(devices)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Re-resolve broker lỗi (bỏ qua lần này): %s", exc)
            return

        topics_by_broker = self._group_topics_by_broker(devices)
        new_brokers = {
            b: t for b, t in topics_by_broker.items() if b not in self._mqtt_clients
        }
        if new_brokers:
            _LOGGER.info(
                "Hunonic MQTT auto-tracking: phát hiện %d broker MỚI — nối thêm: %s",
                len(new_brokers),
                list(new_brokers),
            )
            await asyncio.gather(
                *(self._connect_broker(b, t) for b, t in new_brokers.items())
            )

        # Subscribe topic mới trên broker đã kết nối (thiết bị mới ở broker cũ).
        for broker, topics in topics_by_broker.items():
            known = self._broker_topics.setdefault(broker, set())
            fresh = topics - known
            known.update(topics)
            client = self._mqtt_clients.get(broker)
            if fresh and client is not None and client.is_connected():
                _LOGGER.info(
                    "Hunonic MQTT auto-tracking: subscribe %d topic mới trên %s",
                    len(fresh), broker,
                )
                for topic in fresh:
                    client.subscribe(topic, qos=1)

    async def _resolve_brokers(self, devices: list[dict[str, Any]]) -> None:
        """Điền self._device_brokers: topic-root → DANH SÁCH broker (primary+backup)."""
        from .const import MQTT_BROKER

        reps: dict[str, str] = {}  # topic_root -> root_type đại diện
        for d in devices:
            topic = d.get("topicpub") or d.get("topicsub") or ""
            tr = self._topic_root(topic)
            if tr and tr not in reps:
                reps[tr] = str(d.get("root_type", ""))

        async def _one(root_id: str, root_type: str) -> tuple[str, list[str]]:
            try:
                brokers = await self.api._fetch_mqtt_brokers(root_id, root_type)
            except Exception:  # noqa: BLE001
                brokers = []
            hosts = [b["host"] for b in brokers] or [MQTT_BROKER]
            return root_id, hosts

        for root_id, hosts in await asyncio.gather(
            *(_one(r, t) for r, t in reps.items())
        ):
            self._device_brokers[root_id] = hosts

    async def _connect_broker(self, host: str, topics: set[str]) -> bool:
        """Mở 1 kết nối MQTT-over-WS tới *host*, subscribe đúng *topics*. Lưu client."""
        # Nguồn sự thật topic của broker này (auto-tracking có thể bổ sung về sau).
        self._broker_topics.setdefault(host, set()).update(topics)
        client_id = f"hunonic_ha-{uuid.uuid4().hex[:8]}"
        client = paho.Client(
            client_id=client_id, protocol=paho.MQTTv311, transport="websockets"
        )
        client.ws_set_options(path=MQTT_WS_PATH)
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        client.reconnect_delay_set(min_delay=MQTT_RECONNECT_DELAY, max_delay=120)

        connected_event = asyncio.Event()

        def _on_connect(c: paho.Client, userdata: Any, flags: dict, rc: int) -> None:
            if rc != 0:
                _LOGGER.warning("MQTT %s connect rc=%s", host, rc)
                return
            if self._mqtt_loop:
                self._mqtt_loop.call_soon_threadsafe(connected_event.set)
            # Subscribe LẠI mỗi lần (re)connect (giữ realtime sau khi mất điện→online).
            # Đọc từ _broker_topics để gồm cả topic được auto-tracking thêm sau này.
            live_topics = self._broker_topics.get(host, topics)
            for topic in live_topics:
                c.subscribe(topic, qos=1)
            _LOGGER.info(
                "Hunonic MQTT (re)connect %s — %d topics", host, len(live_topics)
            )
            if self._mqtt_loop:
                self._mqtt_loop.call_soon_threadsafe(
                    lambda: self.hass.async_create_task(self.async_request_refresh())
                )

        def _on_disconnect(c: paho.Client, userdata: Any, rc: int) -> None:
            if rc != 0:
                _LOGGER.warning("MQTT %s mất kết nối (rc=%s) — sẽ tự nối lại", host, rc)

        def _on_message(c: paho.Client, userdata: Any, msg: paho.MQTTMessage) -> None:
            self._handle_mqtt_message(msg)

        client.on_connect = _on_connect
        client.on_disconnect = _on_disconnect
        client.on_message = _on_message

        try:
            client.connect(host, MQTT_WS_PORT, keepalive=60)
        except OSError as exc:
            _LOGGER.warning("Không kết nối được MQTT %s — %s", host, exc)
            return False

        client.loop_start()
        try:
            await asyncio.wait_for(connected_event.wait(), timeout=12)
        except asyncio.TimeoutError:
            _LOGGER.warning("Timeout kết nối MQTT %s", host)
            client.loop_stop()
            return False

        self._mqtt_clients[host] = client
        return True

    # ── MQTT Message Handler ─────────────────────────────────────────────────

    def _mqtt_decrypt_candidates(
        self, raw_bytes: bytes, key_b64: str, iv_b64: str, root_id: str
    ) -> list[str]:
        """Các cách giải mã khả dĩ cho payload /ok, ưu tiên RAW BYTES (thực tế)."""
        out: list[str] = []
        # 1) raw bytes (định dạng thật của thiết bị)
        try:
            if key_b64 and iv_b64:
                out.append(decrypt_bytes_with_keyiv(raw_bytes, key_b64, iv_b64))
            else:
                out.append(decrypt_bytes_payload(raw_bytes, root_id))
        except Exception:  # noqa: BLE001
            pass
        # 2) base64-string (tương thích ngược) + 3) JSON thuần
        raw_str = raw_bytes.decode("utf-8", errors="replace")
        try:
            if key_b64 and iv_b64:
                out.append(decrypt_with_keyiv(raw_str, key_b64, iv_b64))
            else:
                out.append(decrypt_payload(raw_str, root_id))
        except Exception:  # noqa: BLE001
            pass
        out.append(raw_str)
        return out

    def _handle_mqtt_message(self, msg: paho.MQTTMessage) -> None:
        """Xử lý tin nhắn MQTT từ broker (chạy trong paho thread)."""
        raw_bytes: bytes = bytes(msg.payload) if isinstance(
            msg.payload, (bytes, bytearray)
        ) else str(msg.payload).encode("utf-8", "replace")

        device = self._topic_index.get(msg.topic)
        if device is None:
            return

        root_id: str = str(device.get("root_id", ""))
        key_b64 = str(device.get("key", ""))
        iv_b64 = str(device.get("iv", ""))

        # Thiết bị publish /ok dưới dạng CIPHERTEXT NHỊ PHÂN THÔ (đã xác minh qua MITM
        # app). Thử giải mã raw-bytes trước; fallback base64-string (bản cũ) rồi JSON thuần.
        state: dict[str, Any] | None = None
        for decrypted in self._mqtt_decrypt_candidates(raw_bytes, key_b64, iv_b64, root_id):
            try:
                parsed = json.loads(decrypted)
                if isinstance(parsed, dict):
                    state = parsed
                    break
            except Exception:  # noqa: BLE001
                continue
        if state is None:
            _LOGGER.debug("Không parse được MQTT message trên %s", msg.topic)
            return

        if state:
            self._device_state[root_id] = state
            self._record_channel_state(root_id, state)
            _LOGGER.debug("MQTT update root_id=%s state=%s", root_id, state)
            if self._mqtt_loop and self.data:
                # Thông báo HA cập nhật tất cả entities (thread-safe)
                self._mqtt_loop.call_soon_threadsafe(
                    self.async_set_updated_data, self.data
                )

    def _record_channel_state(self, root_id: str, payload: dict[str, Any]) -> None:
        """Cập nhật trạng thái TỪNG KÊNH từ `action`: kênh=(a+1)//2, ON nếu a lẻ.

        Cần cho công tắc đa nút (chung root_id): nếu chỉ lưu 1 action chung, kênh
        không khớp sẽ đọc nhầm → 'tắt nút này nút kia bật'.
        """
        act = payload.get("action")
        if act is None:
            return
        try:
            a = int(act)
        except (TypeError, ValueError):
            return
        if a >= 1:
            self._channel_state.setdefault(root_id, {})[(a + 1) // 2] = (a % 2 == 1)

    def get_channel_state(self, root_id: str, channel: int) -> bool | None:
        """Trạng thái ON/OFF của 1 kênh (1-based); None nếu chưa biết."""
        return self._channel_state.get(root_id, {}).get(channel)

    # ── Control ──────────────────────────────────────────────────────────────

    async def async_control_device(
        self,
        device: dict[str, Any],
        payload: dict[str, Any],
        use_gateway: bool = False,
    ) -> bool:
        """Gửi lệnh điều khiển thiết bị qua MQTT (có fallback refresh).

        Args:
            device: Raw device dict từ coordinator data.
            payload: Dict lệnh (e.g. {"action": 1, "src": 1}).
            use_gateway: True để dùng topicPubGateway (cho cổng gate hub).

        Returns:
            True nếu publish thành công.
        """
        root_id: str = str(device.get("root_id", ""))
        key_b64 = str(device.get("key", ""))
        iv_b64 = str(device.get("iv", ""))

        # Lệnh điều khiển PUBLISH tới topicsub (state sẽ báo về topicpub = .../ok).
        if use_gateway:
            topic: str = str(device.get("topicPubGateway", device.get("topic_pub_gateway", "")))
        else:
            topic = str(device.get("topicsub", device.get("topic_sub", "")))

        # Publish lên TẤT CẢ broker của thiết bị (primary + backup) — thiết bị nối
        # broker nào trong cặp cũng nhận được; không bị hụt nếu nó ở broker backup.
        brokers = self._device_brokers.get(self._topic_root(topic), []) if topic else []
        clients = [
            self._mqtt_clients[b]
            for b in brokers
            if b in self._mqtt_clients and self._mqtt_clients[b].is_connected()
        ]

        if clients and topic:
            raw_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            try:
                # PHẢI publish CIPHERTEXT NHỊ PHÂN THÔ (KHÔNG base64) — thiết bị bỏ qua
                # lệnh base64. Xác minh qua MITM app (app gửi 64 byte thô lên topicsub).
                if key_b64 and iv_b64:
                    payload_bytes = encrypt_bytes_with_keyiv(raw_json, key_b64, iv_b64)
                else:
                    payload_bytes = encrypt_bytes_payload(raw_json, root_id)
            except Exception as exc:
                _LOGGER.error("Lỗi mã hóa lệnh cho %s: %s", device.get("name"), exc)
                return False

            ok = False
            for client in clients:
                if client.publish(topic, payload_bytes, qos=1).rc == paho.MQTT_ERR_SUCCESS:
                    ok = True
            if ok:
                _LOGGER.debug(
                    "MQTT publish '%s' lên %d broker: %s", device.get("name"),
                    len(clients), raw_json,
                )
                # Cập nhật state tức thì (optimistic) — cả state chung + per-channel.
                self._device_state.setdefault(root_id, {}).update(payload)
                self._record_channel_state(root_id, payload)
                self.async_set_updated_data(self.data)
                # Lên lịch refresh sau 2s để đồng bộ trạng thái thật
                self.hass.loop.call_later(
                    2,
                    lambda: self.hass.async_create_task(self.async_request_refresh()),
                )
                return True

            _LOGGER.warning("MQTT publish thất bại cho %s", device.get("name"))

        # Fallback khi không có MQTT
        _LOGGER.debug(
            "MQTT không khả dụng cho device=%s — sẽ poll sau",
            device.get("id"),
        )
        self.hass.loop.call_later(
            3,
            lambda: self.hass.async_create_task(self.async_request_refresh()),
        )
        return False

    # ── State helpers ─────────────────────────────────────────────────────────

    def get_device_state(self, root_id: str) -> dict[str, Any]:
        """Trả về trạng thái MQTT cuối cùng của thiết bị theo root_id."""
        return self._device_state.get(root_id, {})

    def get_device_raw(self, device_id: str) -> dict[str, Any]:
        """Trả về dữ liệu raw từ REST API theo device_id."""
        return self._device_index.get(str(device_id), {})

    def is_device_online(self, device_id: str) -> bool:
        """Thiết bị có online không — dựa trên field `state` (1/2) ĐÁNG TIN.

        Đã kiểm chứng: state=1 phản hồi MQTT (online), state=2 KHÔNG phản hồi
        (offline thật). Dùng cho `available` để không hiện 'bật tắt được' giả
        (optimistic) trên thiết bị offline. Không có `state` → coi như online.
        """
        raw = self._device_index.get(str(device_id), {})
        state = str(raw.get("state", ""))
        if state == "1":
            return True
        if state == "2":
            return False
        status = raw.get("DeviceStatus")
        if status is None:
            return True
        try:
            return bool(int(status))
        except (TypeError, ValueError):
            return bool(status)

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def shutdown_mqtt(self) -> None:
        """Ngắt tất cả kết nối MQTT (đồng bộ, dùng khi unload entry)."""
        for host, client in list(self._mqtt_clients.items()):
            try:
                client.disconnect()
                client.loop_stop()
            except Exception:  # noqa: BLE001
                pass
        if self._mqtt_clients:
            _LOGGER.info("Hunonic MQTT đã ngắt %d kết nối", len(self._mqtt_clients))
        self._mqtt_clients.clear()
        self._broker_topics.clear()
        self._channel_state.clear()
