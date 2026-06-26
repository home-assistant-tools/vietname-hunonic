"""
Data models for the Hunonic smart home API.
Uses Python dataclasses for broad compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DeviceType(str, Enum):
    """Known root_type values reported by the Hunonic API."""
    WALL_SWITCH = "wswitch"
    WALL_SWITCH_V2 = "wswitch2v"
    WALL_SWITCH_3 = "wswitch3"
    WALL_SWITCH_4 = "wswitch4"
    WALL_SWITCH_DIMMER = "wswitchdimmer"
    WALL_SWITCH_FAN = "wswitchfan"
    CURTAIN = "curtain"
    CURTAIN_V2 = "curtain2v"
    GATE_HUB = "gatehub"
    GATE = "gate"
    DOOR = "door"
    DOOR_SENSOR = "doorsensor"
    FAN = "fan"
    LED = "led"
    LED_STRIP = "ledstrip"
    IR_REMOTE = "irremote"
    SOCKET = "socket"
    SENSOR_MOTION = "sensormotion"
    SENSOR_TEMP = "sensortemp"
    SENSOR_AIR = "sensorair"
    UNKNOWN = "unknown"


class DeviceCategory(str, Enum):
    """High-level functional category for a device."""
    SWITCH = "switch"
    GATE_HUB = "gate_hub"
    GATE = "gate"
    DOOR = "door"
    FAN = "fan"
    LED = "led"
    CURTAIN = "curtain"
    SENSOR = "sensor"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Category helpers
# ---------------------------------------------------------------------------

_SWITCH_TYPES: frozenset[str] = frozenset({
    # Wall switches
    "wswitch", "wswitch2v", "wswitch3v", "wsdatic", "wsdatic3v", "wswc",
    # LH switches
    "lhswitch", "lhswitch2v", "lhswitch3v", "lhrtcsw",
    # N-series
    "nswitch",
    # SIM-based switches
    "swsim", "swsimv2", "swsimv3",
    # Mini switches
    "swmini", "swminiv2",
    # Input switches
    "swinput", "swinputv2",
    # S-series
    "sswitch", "sswitch2v", "swstair",
    # DATIC
    "daticbs", "daticbsv2",
    # Shock sensors / smart switches
    "swshock", "swshockv2", "swshock_hun", "swshohuv2",
    # Other
    "wsm",
})

_GATE_HUB_TYPES: frozenset[str] = frozenset({
    "gatehun", "gatehuwf",
})

_GATE_TYPES: frozenset[str] = frozenset({
    "gate", "gatev2", "wsgate",
})

_DOOR_TYPES: frozenset[str] = frozenset({
    "sdoor2", "sdoor3", "sdoor4", "sdoor5", "sdoor6",
    "sdoor7", "sdoor8", "sdoor9", "sdoor10", "sdoor12",
})

_FAN_TYPES: frozenset[str] = frozenset({
    "fanwifi", "fanac", "fandc", "fanacir",
})

_LED_TYPES: frozenset[str] = frozenset({
    "swled", "swledv2", "dled", "duhalled", "radav1", "duhal",
})

_CURTAIN_TYPES: frozenset[str] = frozenset()

_SENSOR_TYPES: frozenset[str] = frozenset()


def get_category(root_type: str) -> DeviceCategory:
    """Return the :class:`DeviceCategory` for a given *root_type* string."""
    if root_type in _SWITCH_TYPES:
        return DeviceCategory.SWITCH
    if root_type in _GATE_HUB_TYPES:
        return DeviceCategory.GATE_HUB
    if root_type in _GATE_TYPES:
        return DeviceCategory.GATE
    if root_type in _DOOR_TYPES:
        return DeviceCategory.DOOR
    if root_type in _FAN_TYPES:
        return DeviceCategory.FAN
    if root_type in _LED_TYPES:
        return DeviceCategory.LED
    if root_type in _CURTAIN_TYPES:
        return DeviceCategory.CURTAIN
    if root_type in _SENSOR_TYPES:
        return DeviceCategory.SENSOR
    return DeviceCategory.OTHER


def is_switch(root_type: str) -> bool:
    """Return True if *root_type* belongs to the SWITCH category."""
    return root_type in _SWITCH_TYPES


def is_door(root_type: str) -> bool:
    """Return True if *root_type* belongs to the DOOR category."""
    return root_type in _DOOR_TYPES


def is_gate(root_type: str) -> bool:
    """Return True if *root_type* belongs to the GATE category."""
    return root_type in _GATE_TYPES


def is_gate_hub(root_type: str) -> bool:
    """Return True if *root_type* belongs to the GATE_HUB category."""
    return root_type in _GATE_HUB_TYPES


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class User:
    """Represents an authenticated Hunonic user."""
    id: str
    phone: str
    name: str
    token_id: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "User":
        return cls(
            id=str(data.get("id", "")),
            phone=str(data.get("phone", "")),
            name=str(data.get("name", "")),
            token_id=str(data.get("token_id", data.get("tokenId", ""))),
        )


@dataclass
class Home:
    """Represents a Hunonic home / location."""
    id: str
    name: str
    address: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Home":
        return cls(
            id=str(data.get("id", data.get("home_id", ""))),
            name=str(data.get("name", data.get("home_name", ""))),
            address=str(data.get("address", "")),
        )


@dataclass
class Room:
    """Represents a room inside a Hunonic home."""
    id: str
    name: str
    home_id: str

    @classmethod
    def from_dict(cls, data: dict[str, Any], home_id: str = "") -> "Room":
        return cls(
            id=str(data.get("id", data.get("room_id", ""))),
            name=str(data.get("name", data.get("room_name", ""))),
            home_id=str(data.get("home_id", home_id)),
        )


@dataclass
class Device:
    """Represents a Hunonic smart home device."""

    # Identity
    id: str
    name: str
    root_type: str
    root_id: str

    # MQTT topics
    topicsub: str = ""
    topicpub: str = ""
    topicPubGateway: str = ""

    # Device structure
    num_device: int = 1
    index_in_root: int = 0

    # State
    value: Any = None

    # Connection & type metadata
    typeConnection: str = ""
    type_user: str = ""
    DeviceStatus: str = ""

    # Identifiers
    pcn: str = ""
    pcn2: str = ""

    # Extra/arbitrary data from the API
    data_extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Device":
        return cls(
            id=str(data.get("id", data.get("device_id", ""))),
            name=str(data.get("name", data.get("device_name", ""))),
            root_type=str(data.get("root_type", "")),
            root_id=str(data.get("root_id", "")),
            topicsub=str(data.get("topicsub", data.get("topic_sub", ""))),
            topicpub=str(data.get("topicpub", data.get("topic_pub", ""))),
            topicPubGateway=str(data.get("topicPubGateway", data.get("topic_pub_gateway", ""))),
            num_device=int(data.get("num_device", 1)),
            index_in_root=int(data.get("index_in_root", 0)),
            value=data.get("value"),
            typeConnection=str(data.get("typeConnection", data.get("type_connection", ""))),
            type_user=str(data.get("type_user", "")),
            DeviceStatus=str(data.get("DeviceStatus", data.get("device_status", ""))),
            pcn=str(data.get("pcn", "")),
            pcn2=str(data.get("pcn2", "")),
            data_extra={
                k: v
                for k, v in data.items()
                if k
                not in {
                    "id",
                    "device_id",
                    "name",
                    "device_name",
                    "root_type",
                    "root_id",
                    "topicsub",
                    "topic_sub",
                    "topicpub",
                    "topic_pub",
                    "topicPubGateway",
                    "topic_pub_gateway",
                    "num_device",
                    "index_in_root",
                    "value",
                    "typeConnection",
                    "type_connection",
                    "type_user",
                    "DeviceStatus",
                    "device_status",
                    "pcn",
                    "pcn2",
                }
            },
        )

    @property
    def category(self) -> DeviceCategory:
        """Functional category derived from *root_type*."""
        return get_category(self.root_type)


@dataclass
class SceneCollection:
    """Represents a Hunonic scene / collection button."""
    id: str
    name: str
    icon: str
    color: str
    active: bool

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SceneCollection":
        return cls(
            id=str(data.get("id", data.get("group_id", ""))),
            name=str(data.get("name", "")),
            icon=str(data.get("icon", "")),
            color=str(data.get("color", "")),
            active=bool(data.get("active", False)),
        )
