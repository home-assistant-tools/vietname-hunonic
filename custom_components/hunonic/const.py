"""Hằng số cho integration Hunonic."""

DOMAIN = "hunonic"

# Web API (login phone+password, lấy device list — topic MÃ HÓA)
WEB_API_URL = "https://web.hunonic.com/api"
BASE_URL = WEB_API_URL + "/api/"  # double /api/

# Mobile API (api.hunonicpro.com) — device list trả topic PLAINTEXT + key/iv.
# listDeviceOfHomeSelect cần token_id từ mobile login (login cần signature
# hunonicEncodeSign — xem docs/reverse-engineering.md §7, CHƯA replicate xong).
MOBILE_API_URL = "https://api.hunonicpro.com/v3/"

# Discovery broker MQTT theo từng thiết bị (mỗi nhà broker khác nhau).
# getInfoMqtt trả danh sách broker (mã hóa AES key=derive_key(root_id), iv=enc[12:28]).
MQTT_INFO_URL = "http://infoserver.hunonicpro.com/HardwareAPI/getInfoMqtt.php"

# MQTT broker TĨNH — chỉ dùng làm fallback nếu getInfoMqtt lỗi.
MQTT_BROKER = "103.109.43.24"      # dự phòng: 123.30.48.196
MQTT_WS_PORT = 8080
MQTT_WS_PATH = "/ws"               # MQTT-over-WebSocket, subprotocol "mqtt"
MQTT_USERNAME = "bestbug"
MQTT_PASSWORD = "bigbugdmm"

# Action điều khiển (đã verify): payload = {"u":uid, "<root_type>":channel0based,
#   "act_id":0, "action":ACTION_ON|ACTION_OFF}, mã hóa AES-CBC key/iv của device,
#   publish tới topicsub (plaintext). State báo về topicpub (=topicsub+"/ok").
ACTION_ON = 1
ACTION_OFF = 2

CONF_PHONE = "phone"
CONF_PASSWORD = "password"
CONF_HOME_ID = "home_id"
CONF_HOME_NAME = "home_name"
CONF_TOKEN_ID = "token_id"
CONF_USER_ID = "user_id"
CONF_HOME_IDS = "home_ids"  # danh sách nhà được chọn (rỗng/không có = tất cả)

PLATFORMS = ["switch", "cover", "fan", "light", "sensor", "select"]

SCAN_INTERVAL = 30  # giây
MQTT_RECONNECT_DELAY = 5

SWITCH_TYPES = [
    "wswitch", "wswitch2v", "wswitch3v", "wsdatic", "wsdatic3v", "wswc",
    "lhswitch", "lhswitch2v", "lhswitch3v", "lhrtcsw", "nswitch",
    "swsim", "swsimv2", "swsimv3", "swmini", "swminiv2",
    "swinput", "swinputv2", "sswitch", "sswitch2v", "swstair",
    "daticbs", "daticbsv2", "swshock", "swshockv2", "swshock_hun", "swshohuv2", "wsm",
    "elmeter",  # công tơ điện có điều khiển — đóng/cắt như công tắc
    # Aptomat/công tơ TỔNG wifi — đóng/cắt CẢ NHÀ. Có on/off như công tắc 1 kênh.
    # ⚠️ TẮT là mất điện toàn nhà — không đưa vào automation vô ý.
    "atmwifi", "atmwifiv2",
]
# Công tơ điện (aptomat đo điện): ngoài on/off còn có sensor điện năng/tiền điện
# + công suất tức thời (data_extra.power_current). atmwifi* = công tơ tổng cả nhà.
METER_TYPES = ["elmeter", "atmwifi", "atmwifiv2"]
GATE_HUB_TYPES = ["gatehun", "gatehuwf"]
GATE_TYPES = ["gate", "gatev2", "wsgate"]
DOOR_TYPES = [
    "sdoor2", "sdoor3", "sdoor4", "sdoor5", "sdoor6",
    "sdoor7", "sdoor8", "sdoor9", "sdoor10", "sdoor12",
]
FAN_TYPES = ["fanwifi", "fanac", "fandc", "fanacir"]
LED_TYPES = ["swled", "swledv2", "dled", "duhalled", "radav1", "duhal"]

def channel_of(index_in_root: int) -> int:
    """index_in_root (1-based) -> chỉ số kênh 0-based dùng trong payload."""
    return max(0, int(index_in_root) - 1)
