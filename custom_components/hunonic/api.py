"""
REST API client và crypto tự chứa cho HACS integration Hunonic.
Không import từ package hunonic/ để tránh phụ thuộc ngoài.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
from typing import Any, Optional

import aiohttp
from cryptography.hazmat.primitives import padding as crypto_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .const import BASE_URL, MOBILE_API_URL
from .sign import hunonic_sign, signed_query

_LOGGER = logging.getLogger(__name__)

# ── Crypto ────────────────────────────────────────────────────────────────────

_KEY_ZERO = b"0000000000000000"
_IV_ZERO = b"0000000000000000"


def _pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
    padder = crypto_padding.PKCS7(block_size * 8).padder()
    return padder.update(data) + padder.finalize()


def _pkcs7_unpad(data: bytes, block_size: int = 16) -> bytes:
    unpadder = crypto_padding.PKCS7(block_size * 8).unpadder()
    return unpadder.update(data) + unpadder.finalize()


def _aes_cbc(data: bytes, key: bytes, iv: bytes, encrypt: bool = True) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    ctx = cipher.encryptor() if encrypt else cipher.decryptor()
    return ctx.update(data) + ctx.finalize()


def derive_key(root_id: str) -> tuple[bytes, bytes]:
    """Derive AES-128 key/iv từ root_id theo thuật toán Hunonic.

    Steps:
      1. PKCS7-pad root_id bytes lên bội số 16.
      2. Encrypt bằng AES-CBC(KEY_ZERO, IV_ZERO).
      3. key = encrypted[4:20], iv = KEY_ZERO.
    """
    padded = _pkcs7_pad(root_id.encode("utf-8"))
    encrypted = _aes_cbc(padded, _KEY_ZERO, _IV_ZERO, encrypt=True)
    return encrypted[4:20], _IV_ZERO


def encrypt_payload(payload: str, root_id: str) -> str:
    """Mã hóa payload MQTT bằng AES-128-CBC và trả về chuỗi base64."""
    key, iv = derive_key(root_id)
    padded = _pkcs7_pad(payload.encode("utf-8"))
    return base64.b64encode(_aes_cbc(padded, key, iv, encrypt=True)).decode("ascii")


def decrypt_payload(data: str, root_id: str) -> str:
    """Giải mã payload MQTT từ chuỗi base64."""
    key, iv = derive_key(root_id)
    ciphertext = base64.b64decode(data)
    return _pkcs7_unpad(_aes_cbc(ciphertext, key, iv, encrypt=False)).decode("utf-8")


def encrypt_with_keyiv(payload: str, key_b64: str, iv_b64: str) -> str:
    """Mã hóa payload MQTT bằng key/iv của device (cách ĐÃ verify thực tế).

    `key`/`iv` lấy thẳng từ field device của mobile API; base64-decode trực tiếp
    thành 16 byte AES-128-CBC (KHÔNG derive từ root_id).
    """
    key = base64.b64decode(key_b64)
    iv = base64.b64decode(iv_b64)
    padded = _pkcs7_pad(payload.encode("utf-8"))
    return base64.b64encode(_aes_cbc(padded, key, iv, encrypt=True)).decode("ascii")


def decrypt_with_keyiv(data: str, key_b64: str, iv_b64: str) -> str:
    """Giải mã payload MQTT bằng key/iv của device (cặp với encrypt_with_keyiv)."""
    key = base64.b64decode(key_b64)
    iv = base64.b64decode(iv_b64)
    ciphertext = base64.b64decode(data)
    return _pkcs7_unpad(_aes_cbc(ciphertext, key, iv, encrypt=False)).decode("utf-8")


# ── Biến thể RAW BYTES (KHÔNG base64) ─────────────────────────────────────────
# QUAN TRỌNG: thiết bị Hunonic publish/nhận lệnh MQTT dưới dạng CIPHERTEXT NHỊ PHÂN
# THÔ, KHÔNG phải chuỗi base64 (xác minh bằng MITM app: app publish 64 byte thô lên
# topicsub, giải mã ra {"u":...,"<rt>":0,"act_id":0,"action":N}). Gửi base64 →
# thiết bị BỎ QUA lệnh (không có /ok, không vào history). Dùng các hàm này để publish.

def encrypt_bytes_with_keyiv(payload: str, key_b64: str, iv_b64: str) -> bytes:
    """Mã hóa payload → CIPHERTEXT NHỊ PHÂN THÔ (key/iv device)."""
    key = base64.b64decode(key_b64)
    iv = base64.b64decode(iv_b64)
    return _aes_cbc(_pkcs7_pad(payload.encode("utf-8")), key, iv, encrypt=True)


def decrypt_bytes_with_keyiv(data: bytes, key_b64: str, iv_b64: str) -> str:
    """Giải mã ciphertext NHỊ PHÂN THÔ (key/iv device)."""
    key = base64.b64decode(key_b64)
    iv = base64.b64decode(iv_b64)
    return _pkcs7_unpad(_aes_cbc(data, key, iv, encrypt=False)).decode("utf-8")


def encrypt_bytes_payload(payload: str, root_id: str) -> bytes:
    """Mã hóa payload → ciphertext NHỊ PHÂN THÔ (key derive từ root_id)."""
    key, iv = derive_key(root_id)
    return _aes_cbc(_pkcs7_pad(payload.encode("utf-8")), key, iv, encrypt=True)


def decrypt_bytes_payload(data: bytes, root_id: str) -> str:
    """Giải mã ciphertext NHỊ PHÂN THÔ (key derive từ root_id)."""
    key, iv = derive_key(root_id)
    return _pkcs7_unpad(_aes_cbc(data, key, iv, encrypt=False)).decode("utf-8")


# ── Exceptions ────────────────────────────────────────────────────────────────

class HunonicError(Exception):
    """Base exception cho tất cả lỗi Hunonic."""


class HunonicAuthError(HunonicError):
    """Lỗi xác thực: sai OTP, token hết hạn, v.v."""


class HunonicConnectionError(HunonicError):
    """Lỗi kết nối mạng."""


# ── REST API Client ───────────────────────────────────────────────────────────

class HunonicAPIClient:
    """Client REST API không đồng bộ cho Hunonic.

    Sử dụng aiohttp.ClientSession được truyền từ ngoài vào để tận dụng
    connection pooling của Home Assistant.
    """

    def __init__(self, session: aiohttp.ClientSession, token_id: str = "") -> None:
        self._session = session
        self.token_id = token_id

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _sign(self, params: dict[str, Any]) -> str:
        """Chữ ký `hunonicEncodeSign` của API mobile (xem sign.py).

        Ký các tham số nằm trong QUERY của URL (gồm `app_role`); KHÔNG ký body.
        """
        return hunonic_sign(params)

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.token_id:
            h["Authorization"] = f"Bearer {self.token_id}"
            h["token_id"] = self.token_id
        return h

    async def _request(
        self,
        method: str,
        url: str,
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        try:
            async with self._session.request(
                method,
                url,
                params=params,
                json=json,
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 401:
                    raise HunonicAuthError(
                        f"Xác thực thất bại (HTTP 401) — {url}"
                    )
                resp.raise_for_status()
                return await resp.json(content_type=None)
        except aiohttp.ClientConnectionError as exc:
            raise HunonicConnectionError(f"Lỗi kết nối: {exc}") from exc
        except aiohttp.ClientError as exc:
            raise HunonicError(f"Lỗi HTTP: {exc}") from exc

    # ── Authentication ────────────────────────────────────────────────────────

    async def login_mobile(self, phone: str, password: str) -> dict[str, Any]:
        """Đăng nhập API mobile bằng SĐT + mật khẩu → token_id (đã verify thực tế).

        Request thật (bắt qua MITM): `POST /v3/user/login`, **multipart/form-data**,
        TẤT CẢ field nằm trong body (gồm cả `app_role` và `signature`), query rỗng.
        Field ký: {password=md5(pw), app_name, lang, is_pro_app, phone, app_role}.

        Returns:
            dict profile gồm `token_id`, `id` (user_id), `name`, ...

        Raises:
            HunonicAuthError: Sai mật khẩu / chữ ký (error_code 1026).
        """
        fields = {
            "password": hashlib.md5(password.encode("utf-8")).hexdigest(),
            "app_name": "hunonic",
            "lang": "vi",
            "is_pro_app": "0",
            "phone": phone,
            "app_role": "1",
        }
        body = dict(fields)
        body["signature"] = hunonic_sign(fields)

        form = aiohttp.FormData()
        for key, value in body.items():
            form.add_field(key, str(value))

        try:
            async with self._session.post(
                MOBILE_API_URL + "user/login",
                data=form,
                headers={"User-Agent": "okhttp/4.9.2"},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                resp.raise_for_status()
                payload = await resp.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise HunonicConnectionError(f"Lỗi đăng nhập mobile: {exc}") from exc

        if not payload.get("status"):
            raise HunonicAuthError(
                f"Đăng nhập thất bại ({payload.get('error_code')}): "
                f"{payload.get('message')}"
            )

        data: dict[str, Any] = payload.get("data", {})
        token = str(data.get("token_id", ""))
        if not token:
            raise HunonicAuthError("Đăng nhập OK nhưng không có token_id.")
        self.token_id = token

        # Tự động chấp nhận các nhà được chia sẻ nhưng chưa chấp nhận (active=0),
        # để chúng xuất hiện trong home/list và có thể chọn/lấy thiết bị.
        try:
            accepted = await self.accept_pending_shares()
            if accepted:
                _LOGGER.info("Hunonic: tự chấp nhận share nhà: %s", accepted)
        except HunonicError as exc:
            _LOGGER.debug("Auto-accept share lỗi (bỏ qua): %s", exc)

        return data

    async def _list_received_homes(self) -> list[dict[str, Any]]:
        """Danh sách nhà được chia sẻ tới (gồm cả lời mời chưa chấp nhận, active=0)."""
        query = signed_query({"token_id": self.token_id, "app_role": "1"})
        qs = "&".join(f"{k}={v}" for k, v in query.items())
        try:
            async with self._session.post(
                f"{MOBILE_API_URL}home/listHomeReceived?{qs}",
                data=b"",
                headers={"User-Agent": "okhttp/4.9.2"},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                body = await resp.json(content_type=None)
        except aiohttp.ClientError:
            return []
        data = body.get("data", [])
        return data if isinstance(data, list) else []

    async def accept_share(self, home_id: int | str) -> bool:
        """Chấp nhận lời mời chia sẻ một nhà.

        `POST home/acceptShare` dạng body (như login): tất cả field trong multipart
        body gồm `signature`. Ký {token_id, home_id, app_role}.
        """
        fields = {
            "token_id": self.token_id,
            "home_id": str(home_id),
            "app_role": "1",
        }
        body = dict(fields)
        body["signature"] = hunonic_sign(fields)
        form = aiohttp.FormData()
        for key, value in body.items():
            form.add_field(key, str(value))
        try:
            async with self._session.post(
                MOBILE_API_URL + "home/acceptShare",
                data=form,
                headers={"User-Agent": "okhttp/4.9.2"},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                payload = await resp.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise HunonicConnectionError(f"Lỗi chấp nhận share: {exc}") from exc
        return bool(payload.get("status"))

    async def accept_pending_shares(self) -> list[str]:
        """Chấp nhận tất cả nhà được share đang chờ (active=0). Trả về tên nhà đã nhận."""
        accepted: list[str] = []
        for home in await self._list_received_homes():
            if str(home.get("active")) == "0" and home.get("id"):
                try:
                    if await self.accept_share(home["id"]):
                        accepted.append(str(home.get("name", home["id"])))
                except HunonicError:
                    continue
        return accepted

    # ── Homes ─────────────────────────────────────────────────────────────────

    async def get_homes(self) -> list[dict[str, Any]]:
        """Lấy tất cả nhà (sở hữu + được chia sẻ) của tài khoản hiện tại."""
        homes: list[dict[str, Any]] = []
        seen: set[str] = set()
        for path in ("hun-api/home/list-home", "hun-api/home/list-home-share"):
            try:
                resp = await self._request("GET", BASE_URL + path)
                items = resp.get("data", [])
                if isinstance(items, list):
                    for item in items:
                        hid = str(item.get("id", item.get("home_id", "")))
                        if hid and hid not in seen:
                            seen.add(hid)
                            homes.append(item)
            except HunonicError:
                pass
        return homes

    # ── Devices ───────────────────────────────────────────────────────────────

    async def get_devices(self, home_id: int | str) -> list[dict[str, Any]]:
        """Lấy danh sách thiết bị trong nhà *home_id*.

        API trả về cấu trúc: home → rooms[] → devices[]
        Hàm này flatten thành danh sách phẳng với room_id/room_name bổ sung.
        """
        resp = await self._request(
            "GET",
            BASE_URL + "hun-api/device/listDeviceByHome",
            params={"home_id": str(home_id)},
        )
        data = resp.get("data", [])
        devices: list[dict[str, Any]] = []
        # data có thể là list[home] hoặc một home object
        homes = data if isinstance(data, list) else [data]
        for home in homes:
            for room in home.get("rooms", []):
                room_id = room.get("id", "")
                room_name = room.get("name", "")
                for dev in room.get("devices", []):
                    dev.setdefault("room_id", room_id)
                    dev.setdefault("room_name", room_name)
                    devices.append(dev)
        return devices

    async def get_homes_mobile(self) -> list[dict[str, Any]]:
        """Lấy danh sách nhà qua API mobile (`POST home/list`, params ở query)."""
        query = signed_query({"token_id": self.token_id, "app_role": "1"})
        qs = "&".join(f"{k}={v}" for k, v in query.items())
        try:
            async with self._session.post(
                f"{MOBILE_API_URL}home/list?{qs}",
                data=b"",
                headers={"User-Agent": "okhttp/4.9.2"},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                resp.raise_for_status()
                body = await resp.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise HunonicConnectionError(f"Lỗi mobile API: {exc}") from exc
        if not body.get("status"):
            raise HunonicAuthError(
                f"Mobile API lỗi {body.get('error_code')}: {body.get('message')}"
            )
        data = body.get("data", [])
        return data if isinstance(data, list) else []

    async def get_devices_mobile(self, home_id: int | str = "") -> list[dict[str, Any]]:
        """Lấy thiết bị qua API mobile (api.hunonicpro.com) — topic PLAINTEXT.

        Dùng `device/listDeviceByHome` (KHÔNG phải listDeviceOfHomeSelect): với
        home_id RỖNG trả thiết bị của **TẤT CẢ nhà** (gồm nhà được share) trong 1
        call — kèm `topicsub`/`topicpub` plaintext + `key`/`iv`. (listDeviceOfHomeSelect
        chỉ trả thiết bị của ĐÚNG home_id truyền vào → bỏ sót nhà share khi để rỗng.)

        Mọi tham số nằm trong query và được ký bằng `hunonic_sign`; body rỗng.
        """
        query = signed_query(
            {
                "token_id": self.token_id,
                "home_id": str(home_id),
                "app_role": "1",
            }
        )
        qs = "&".join(f"{k}={v}" for k, v in query.items())
        url = f"{MOBILE_API_URL}device/listDeviceByHome?{qs}"
        try:
            async with self._session.post(
                url,
                data=b"",
                headers={"User-Agent": "okhttp/4.9.2"},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                resp.raise_for_status()
                body = await resp.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise HunonicConnectionError(f"Lỗi mobile API: {exc}") from exc

        if not body.get("status"):
            raise HunonicAuthError(
                f"Mobile API lỗi {body.get('error_code')}: {body.get('message')}"
            )

        # Cấu trúc: data[] → home.rooms[] → room.devices[]
        # Mỗi device đã kèm sẵn topicsub/topicpub/key/iv/root_type/root_id.
        data = body.get("data", {})
        devices: list[dict[str, Any]] = []
        homes = data if isinstance(data, list) else [data]
        for home in homes:
            home_id = str(home.get("id", ""))
            home_name = str(home.get("name", "")) or f"Nhà {home_id}"
            for room in home.get("rooms", []) or []:
                room_id = room.get("id", "")
                room_name = room.get("name", "")
                for dev in room.get("devices", []) or []:
                    if isinstance(dev, dict) and dev.get("root_id"):
                        dev.setdefault("home_id", home_id)
                        dev.setdefault("home_name", home_name)
                        dev.setdefault("room_id", room_id)
                        dev.setdefault("room_name", room_name)
                        devices.append(dev)
        return devices

    async def get_scenes(self, home_id: int | str) -> list[dict[str, Any]]:
        """Lấy danh sách kịch bản (scene) của nhà. Tùy chọn — lỗi trả [] để không chặn."""
        try:
            query = signed_query(
                {"token_id": self.token_id, "home_id": str(home_id), "app_role": "1"}
            )
            qs = "&".join(f"{k}={v}" for k, v in query.items())
            async with self._session.post(
                f"{MOBILE_API_URL}collection/listCollection?{qs}",
                data=b"",
                headers={"User-Agent": "okhttp/4.9.2"},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                body = await resp.json(content_type=None)
            data = body.get("data", [])
            return data if isinstance(data, list) else []
        except (aiohttp.ClientError, ValueError):
            return []

    async def get_mqtt_info(
        self, root_id: str = "", root_type: str = ""
    ) -> dict[str, Any]:
        """Broker MQTT THẬT của thiết bị (mỗi nhà broker khác nhau).

        Gọi getInfoMqtt (HardwareAPI) bằng root_id → giải mã → lấy danh sách broker
        được gán cho thiết bị. Trả broker đầu (primary) trên cổng WS 8080, kèm danh
        sách `brokers` để coordinator failover. Lỗi/không có → fallback broker tĩnh.
        """
        from .const import MQTT_BROKER, MQTT_PASSWORD, MQTT_USERNAME, MQTT_WS_PORT

        brokers = await self._fetch_mqtt_brokers(root_id, root_type) if root_id else []
        if brokers:
            primary = brokers[0]
            return {
                "host": primary["host"],
                "port": MQTT_WS_PORT,  # dùng WebSocket 8080 (getInfoMqtt trả 1883 TCP)
                "username": primary.get("user") or MQTT_USERNAME,
                "password": primary.get("pass") or MQTT_PASSWORD,
                "brokers": [bk["host"] for bk in brokers],
            }
        return {
            "host": MQTT_BROKER,
            "port": MQTT_WS_PORT,
            "username": MQTT_USERNAME,
            "password": MQTT_PASSWORD,
            "brokers": [],
        }

    async def _fetch_mqtt_brokers(
        self, root_id: str, root_type: str
    ) -> list[dict[str, Any]]:
        """Lấy + giải mã danh sách broker từ getInfoMqtt cho 1 thiết bị.

        Response `data` là base64 của AES-CBC: key = derive_key(root_id), iv = enc[12:28]
        (16 byte đầu plaintext là rác, phần sau là JSON các broker).
        """
        from .const import MQTT_INFO_URL

        url = f"{MQTT_INFO_URL}?device_id={root_id}&type={root_type}&dev=0"
        try:
            async with self._session.get(
                url,
                headers={"User-Agent": "okhttp/4.9.2"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                body = await resp.json(content_type=None)
        except (aiohttp.ClientError, ValueError):
            return []

        data = body.get("data")
        if not isinstance(data, str):
            return []
        try:
            enc = base64.b64decode(data)
            key = derive_key(root_id)[0]
            text = _aes_cbc(enc, key, enc[12:28], encrypt=False).decode("latin1")
        except Exception:  # noqa: BLE001
            return []

        # Bắt từng broker: "<ip>","port":"<p>","user":"<u>","pass":"<p>"
        # (khớp cả broker đầu dù key "server" có thể nằm trong block rác).
        matches = re.findall(
            r'"(\d{1,3}(?:\.\d{1,3}){3})"\s*,\s*"port"\s*:\s*"(\d+)"\s*,'
            r'\s*"user"\s*:\s*"([^"]*)"\s*,\s*"pass"\s*:\s*"([^"]*)"',
            text,
        )
        return [
            {"host": m[0], "tcp_port": int(m[1]), "user": m[2], "pass": m[3]}
            for m in matches
        ]

    async def get_profile(self) -> dict[str, Any]:
        """Lấy thông tin profile người dùng hiện tại."""
        resp = await self._request("GET", BASE_URL + "user/profile")
        return resp.get("data", resp)
