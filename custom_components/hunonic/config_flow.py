"""Config flow cho Hunonic — đăng nhập 1 lần, CHỌN nhà cần nạp (checkbox)."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import HunonicAPIClient, HunonicAuthError, HunonicConnectionError, HunonicError
from .const import (
    CONF_HOME_IDS,
    CONF_PASSWORD,
    CONF_PHONE,
    CONF_TOKEN_ID,
    CONF_USER_ID,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _homes_schema(homes: list[dict[str, Any]], selected: list[str]) -> vol.Schema:
    """Schema multi-select (checkbox) danh sách nhà; mặc định = *selected*."""
    options = [
        SelectOptionDict(
            value=str(h.get("id", "")),
            label=str(h.get("name", f"Nhà {h.get('id', '')}")),
        )
        for h in homes
        if h.get("id")
    ]
    valid = [str(h.get("id")) for h in homes if h.get("id")]
    default = [s for s in selected if s in valid] or valid
    return vol.Schema({
        vol.Required(CONF_HOME_IDS, default=default): SelectSelector(
            SelectSelectorConfig(
                options=options, multiple=True, mode=SelectSelectorMode.LIST
            )
        ),
    })


async def _fetch_homes(token_id: str) -> list[dict[str, Any]]:
    async with aiohttp.ClientSession() as session:
        client = HunonicAPIClient(session, token_id=token_id)
        return await client.get_homes_mobile()


class HunonicConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Cấu hình Hunonic: đăng nhập → chọn nhà (checkbox).

    Một config entry = một TÀI KHOẢN, nạp thiết bị các nhà ĐƯỢC CHỌN (gồm nhà được
    chia sẻ). Một lần đăng nhập là đủ (Hunonic giới hạn phiên → login lại bị đá).
    Đổi danh sách nhà sau qua nút "Cấu hình" — KHÔNG cần đăng nhập lại.
    """

    VERSION = 2

    def __init__(self) -> None:
        self._phone: str = ""
        self._password: str = ""
        self._token_id: str = ""
        self._user_id: str = ""
        self._homes: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Bước 1: đăng nhập SĐT + mật khẩu."""
        errors: dict[str, str] = {}

        if user_input is not None:
            phone: str = user_input[CONF_PHONE].strip()
            password: str = user_input[CONF_PASSWORD]
            if not phone or not password:
                errors["base"] = "invalid_auth"
            else:
                async with aiohttp.ClientSession() as session:
                    try:
                        client = HunonicAPIClient(session)
                        data = await client.login_mobile(phone, password)
                        self._phone = phone
                        self._password = password
                        self._token_id = str(data.get("token_id", ""))
                        self._user_id = str(data.get("id", data.get("user_id", "")))
                        self._homes = await client.get_homes_mobile()
                    except HunonicAuthError:
                        errors["base"] = "invalid_auth"
                    except HunonicConnectionError:
                        errors["base"] = "cannot_connect"
                    except HunonicError as exc:
                        _LOGGER.error("Lỗi đăng nhập: %s", exc)
                        errors["base"] = "unknown"
                    except Exception:  # noqa: BLE001
                        _LOGGER.exception("Lỗi không xác định khi đăng nhập")
                        errors["base"] = "unknown"

            if not errors:
                await self.async_set_unique_id(
                    f"hunonic_account_{self._user_id or self._phone}"
                )
                self._abort_if_unique_id_configured()
                return await self.async_step_homes()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_PHONE): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.TEL)
                ),
                vol.Required(CONF_PASSWORD): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
            }),
            errors=errors,
        )

    async def async_step_homes(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Bước 2: chọn nhà cần nạp (checkbox, mặc định tất cả)."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"Hunonic — {self._phone}",
                data={
                    CONF_PHONE: self._phone,
                    CONF_PASSWORD: self._password,
                    CONF_TOKEN_ID: self._token_id,
                    CONF_USER_ID: self._user_id,
                    CONF_HOME_IDS: [str(x) for x in user_input.get(CONF_HOME_IDS, [])],
                },
            )

        if not self._homes:  # phòng khi chưa có (vd vào lại bước)
            try:
                self._homes = await _fetch_homes(self._token_id)
            except HunonicError:
                pass
        return self.async_show_form(
            step_id="homes",
            data_schema=_homes_schema(self._homes, []),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "HunonicOptionsFlow":
        return HunonicOptionsFlow()


class HunonicOptionsFlow(config_entries.OptionsFlow):
    """Đổi danh sách nhà sau khi đã cấu hình — KHÔNG cần đăng nhập lại.

    KHÔNG gán self.config_entry (ở HA mới đó là property read-only, gán sẽ 500);
    base class tự cấp self.config_entry.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            new_data = {
                **self.config_entry.data,
                CONF_HOME_IDS: [str(x) for x in user_input.get(CONF_HOME_IDS, [])],
            }
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(self.config_entry.entry_id)
            )
            return self.async_create_entry(title="", data={})

        try:
            homes = await _fetch_homes(str(self.config_entry.data.get(CONF_TOKEN_ID, "")))
        except HunonicError:
            homes = []
        current = [str(x) for x in (self.config_entry.data.get(CONF_HOME_IDS) or [])]
        return self.async_show_form(
            step_id="init",
            data_schema=_homes_schema(homes, current),
        )
