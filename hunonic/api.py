"""
Async REST API client for the Hunonic smart home platform.

Requires:
    pip install aiohttp
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Optional
from urllib.parse import urljoin

import aiohttp

from .exceptions import HunonicAuthError, HunonicConnectionError, HunonicError
from .models import Device, Home, Room, SceneCollection, User


class HunonicAPI:
    """Asynchronous Hunonic REST API client.

    Usage::

        async with aiohttp.ClientSession() as session:
            api = HunonicAPI(session=session)
            await api.request_otp("+84xxxxxxxxx")
            user = await api.login("+84xxxxxxxxx", "123456")
            homes = await api.get_homes()
    """

    BASE_URL = "https://api.hunonicpro.com/v3/"
    SMS_URL = "https://apisms.hunonicpro.com/v3/"
    MQTT_INFO_URL = "http://infoserver.hunonicpro.com/HardwareAPI/getInfoMqtt.php"

    def __init__(self, session: Optional[aiohttp.ClientSession] = None) -> None:
        self._session = session
        self._owns_session = session is None
        self.token_id: Optional[str] = None
        self.user: Optional[User] = None

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        """Close the underlying aiohttp session if it was created internally."""
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    async def __aenter__(self) -> "HunonicAPI":
        await self._ensure_session()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _sign(self, params: dict[str, Any]) -> str:
        """Compute a request signature.

        The signature is the MD5 hex digest of the alphabetically sorted
        ``key=value`` pairs joined with ``&``.  This mirrors a common
        Hunonic signing pattern; adjust if the server uses a different algo.
        """
        sorted_pairs = "&".join(
            f"{k}={v}" for k, v in sorted(params.items()) if v is not None
        )
        return hashlib.md5(sorted_pairs.encode("utf-8")).hexdigest()

    def _auth_headers(self) -> dict[str, str]:
        """Build HTTP headers that include the auth token when available."""
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.token_id:
            headers["Authorization"] = f"Bearer {self.token_id}"
            headers["token_id"] = self.token_id
        return headers

    def _timestamp(self) -> int:
        return int(time.time())

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[dict[str, Any]] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        session = await self._ensure_session()
        try:
            async with session.request(
                method,
                url,
                params=params,
                json=data,
                headers=self._auth_headers(),
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 401:
                    raise HunonicAuthError(
                        f"Unauthorized (HTTP 401) for {url}. "
                        "Check your token or re-authenticate."
                    )
                if resp.status >= 400:
                    body = await resp.text()
                    raise HunonicError(
                        f"HTTP {resp.status} from {url}: {body[:200]}"
                    )
                return await resp.json(content_type=None)
        except aiohttp.ClientConnectionError as exc:
            raise HunonicConnectionError(f"Connection error: {exc}") from exc
        except aiohttp.ClientError as exc:
            raise HunonicError(f"HTTP client error: {exc}") from exc

    async def _get(
        self,
        path: str,
        params: Optional[dict[str, Any]] = None,
        base_url: str = BASE_URL,
    ) -> dict[str, Any]:
        url = urljoin(base_url, path)
        return await self._request("GET", url, params=params)

    async def _post(
        self,
        path: str,
        data: Optional[dict[str, Any]] = None,
        base_url: str = BASE_URL,
    ) -> dict[str, Any]:
        url = urljoin(base_url, path)
        return await self._request("POST", url, data=data or {})

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def request_otp(self, phone: str) -> bool:
        """Request a one-time password SMS for *phone*.

        Args:
            phone: E.164 phone number (e.g. ``"+84912345678"``).

        Returns:
            ``True`` if the OTP was dispatched successfully.

        Raises:
            HunonicError: If the server returns an unexpected response.
        """
        payload = {
            "phone": phone,
            "timestamp": self._timestamp(),
        }
        payload["sign"] = self._sign(payload)
        resp = await self._post("user/sendSMS", data=payload, base_url=self.SMS_URL)
        # The API typically returns {"status": 1} on success.
        return bool(resp.get("status") == 1 or resp.get("success"))

    async def login(self, phone: str, otp: str) -> User:
        """Authenticate with phone + OTP and store the resulting token.

        Args:
            phone: E.164 phone number.
            otp: The one-time password received via SMS.

        Returns:
            The authenticated :class:`~hunonic.models.User`.

        Raises:
            HunonicAuthError: If the credentials are rejected.
        """
        payload = {
            "phone": phone,
            "otp": otp,
            "timestamp": self._timestamp(),
        }
        payload["sign"] = self._sign(payload)
        resp = await self._post("user/addInfoLogin", data=payload)

        if resp.get("status") not in (1, "1", True) and not resp.get("success"):
            msg = resp.get("message", resp.get("msg", "Login failed"))
            raise HunonicAuthError(str(msg))

        user_data: dict[str, Any] = resp.get("data", resp)
        self.token_id = str(
            user_data.get("token_id", user_data.get("tokenId", ""))
        )
        if not self.token_id:
            raise HunonicAuthError("Login succeeded but no token_id was returned.")

        self.user = User.from_dict(user_data)
        return self.user

    # ------------------------------------------------------------------
    # User
    # ------------------------------------------------------------------

    async def get_profile(self) -> User:
        """Fetch the current user's profile.

        Returns:
            Updated :class:`~hunonic.models.User` instance.
        """
        resp = await self._get("user/getProfile")
        data: dict[str, Any] = resp.get("data", resp)
        self.user = User.from_dict(data)
        return self.user

    # ------------------------------------------------------------------
    # Homes
    # ------------------------------------------------------------------

    async def get_homes(self) -> list[Home]:
        """Return all homes the authenticated user can access (owned + received).

        Returns:
            List of :class:`~hunonic.models.Home` objects.
        """
        owned_resp = await self._get("home/listHome")
        received_resp = await self._get("home/listHomeReceived")

        homes: list[Home] = []
        seen: set[str] = set()

        for resp in (owned_resp, received_resp):
            items: list[dict[str, Any]] = resp.get("data", resp) if isinstance(
                resp.get("data"), list
            ) else []
            if not items and isinstance(resp, list):
                items = resp
            for item in items:
                home = Home.from_dict(item)
                if home.id not in seen:
                    seen.add(home.id)
                    homes.append(home)

        return homes

    # ------------------------------------------------------------------
    # Rooms
    # ------------------------------------------------------------------

    async def get_rooms(self, home_id: int) -> list[Room]:
        """Return all rooms for *home_id*.

        Args:
            home_id: Numeric home identifier.

        Returns:
            List of :class:`~hunonic.models.Room` objects.
        """
        resp = await self._get(
            "room/listRoomByHome", params={"home_id": home_id}
        )
        items: list[dict[str, Any]] = resp.get("data", [])
        return [Room.from_dict(item, home_id=str(home_id)) for item in items]

    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------

    async def get_devices(self, home_id: int) -> list[Device]:
        """Return all devices that belong to *home_id*.

        Args:
            home_id: Numeric home identifier.

        Returns:
            List of :class:`~hunonic.models.Device` objects.
        """
        resp = await self._get(
            "device/listDeviceByHome", params={"home_id": home_id}
        )
        items: list[dict[str, Any]] = resp.get("data", [])
        return [Device.from_dict(item) for item in items]

    async def get_device_state(self, device_id: str) -> dict[str, Any]:
        """Fetch the current state of a single device.

        Args:
            device_id: The device's string identifier.

        Returns:
            Raw state dictionary from the API.
        """
        resp = await self._get(
            "device/getDeviceState", params={"device_id": device_id}
        )
        return resp.get("data", resp)

    # ------------------------------------------------------------------
    # Scenes / Collections
    # ------------------------------------------------------------------

    async def get_scenes(self, home_id: int) -> list[SceneCollection]:
        """Return all scene collections for *home_id*.

        Args:
            home_id: Numeric home identifier.

        Returns:
            List of :class:`~hunonic.models.SceneCollection` objects.
        """
        resp = await self._get(
            "collection/listCollectionButton", params={"home_id": home_id}
        )
        items: list[dict[str, Any]] = resp.get("data", [])
        return [SceneCollection.from_dict(item) for item in items]

    async def execute_scene(self, group_id: str) -> bool:
        """Trigger a scene / collection by *group_id*.

        Args:
            group_id: The scene's group identifier.

        Returns:
            ``True`` if the server confirmed successful execution.
        """
        payload = {
            "group_id": group_id,
            "timestamp": self._timestamp(),
        }
        payload["sign"] = self._sign(payload)
        resp = await self._post("MqttControl/executeCollection", data=payload)
        return bool(resp.get("status") == 1 or resp.get("success"))

    # ------------------------------------------------------------------
    # MQTT broker info
    # ------------------------------------------------------------------

    async def get_mqtt_info(self, device_id: str) -> dict[str, Any]:
        """Fetch MQTT broker connection parameters for *device_id*.

        Args:
            device_id: The device's string identifier.

        Returns:
            Dictionary containing host, port, username, password, etc.
        """
        resp = await self._get(
            "",
            params={"device_id": device_id},
            base_url=self.MQTT_INFO_URL,
        )
        return resp.get("data", resp)
