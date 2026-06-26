# Phân tích Hardware & Local Control - Hunonic

> [!CAUTION]
> **CHỈ DÙNG CHO MỤC ĐÍCH CÁ NHÂN — KHÔNG THƯƠNG MẠI.**
>
> - Repo/tài liệu này được tạo qua reverse-engineering nhằm mục đích nghiên cứu và liên thông cá nhân (interoperability) với thiết bị **bạn sở hữu**.
> - **KHÔNG** dùng cho mục đích thương mại dưới bất kỳ hình thức nào.
> - **Tự kiểm tra kỹ các quy định về sở hữu trí tuệ, điều khoản dịch vụ và pháp luật hiện hành** tại nơi bạn sinh sống **trước khi** sử dụng. Bạn tự chịu hoàn toàn trách nhiệm.
> - **KHÔNG** chia sẻ, phát tán, hay sử dụng để tấn công/chống phá/làm gián đoạn hệ thống Hunonic hoặc bất kỳ hệ thống nào.
> - Tác giả không chịu trách nhiệm cho bất kỳ thiệt hại hay hậu quả pháp lý nào phát sinh từ việc sử dụng repo này.

## Kết luận chính

Hunonic KHÔNG hỗ trợ local control thực sự. Toàn bộ điều khiển đi qua cloud MQTT.  
Tuy nhiên, có thể flash ESPHome qua cơ chế OTA của chính thiết bị để thoát khỏi cloud.

---

## Chip phần cứng

Phân tích từ APK (`GateActions.java`, `GateHubActions.java`):

| Thiết bị | Chip | Ghi chú |
|---|---|---|
| Switch, Gate trực tiếp | **ESP8266 / ESP32** | `CODE_UPDATE_ESP = 129` |
| Gate Hub (`gatehun`, `gatehuwf`) | **STM32** + ESP (WiFi) | `CODE_UPDATE_CHIP_STM32 = 130` |
| Thiết bị BLE (một số) | **nRF (Nordic)** | Library `no.nordicsemi.android.dfu` có trong APK |

---

## BLE (Bluetooth Low Energy)

- BLE chỉ dùng để cung cấp WiFi credentials khi cài đặt thiết bị lần đầu
- Giao thức BLE: frame bắt đầu bằng `8B8B`, gồm function ID + WiFi SSID + password
- `DMS_BY_BLE = "0002"` — provisioning qua BLE
- `DMS_BY_AP = "0003"` — provisioning qua AP mode
- Không có kênh điều khiển BLE cho thiết bị đã cài đặt
- Module React Native: `com.bleplx.BlePlxModule`

---

## WiFi/LAN Local Control

- `DeviceTypes.lanTypes = ["quannehihi"]` — placeholder, không có thiết bị thực
- `TypeConnection.CONNECTION_LAN = "LAN"` tồn tại nhưng không được sử dụng
- Không có kênh TCP/UDP trực tiếp đến thiết bị

---

## OTA Firmware Update (qua MQTT)

### Cơ chế

- Thiết bị **tự tải** binary từ URL được app gửi qua MQTT (app không push binary)
- Command code: `CODE_UPDATE_ESP = 129` (từ `GateActions.java`)
- Payload field: `KEY_URL = "url"` — URL của firmware

### Payload OTA (suy luận từ DeviceCommandFactory)

```json
{
  "action": 129,
  "url": "http://your-server.com/firmware.bin"
}
```

Payload được **mã hóa AES-128-CBC** rồi publish lên topic `device.topicpub`.

### Ứng dụng: Flash ESPHome

Về lý thuyết, có thể flash ESPHome lên thiết bị ESP:

1. Biên dịch firmware ESPHome cho ESP8266/ESP32 phù hợp
2. Host file `.bin` trên server HTTP
3. Gửi MQTT command 129 với URL đó
4. Thiết bị tải và flash firmware mới

**Yêu cầu để thực hiện:**
- Biết MQTT broker host + credentials (username/password từ native lib)
- Biết `root_id` của thiết bị (lấy được qua REST API)
- Server HTTP phục vụ file bin (local hoặc public)

**Rủi ro:**
- Nếu flash sai firmware → brick thiết bị
- Gate Hub dùng STM32, không thể flash ESPHome trực tiếp
- Thiết bị nRF/BLE không áp dụng

### Các MQTT command hệ thống khác

```
CODE_CHANGER_WIFI      = 128  // Đổi WiFi: {"action":128,"ssid":"...","pass":"..."}
CODE_UPDATE_ESP        = 129  // OTA ESP:  {"action":129,"url":"http://..."}
CODE_PRESS_MODE        = 130  // Chế độ nhấn
CODE_STATIC_IP         = 132  // IP tĩnh
CODE_UPDATE_BLE_FROM_PHONE = 147  // DFU BLE từ điện thoại
CODE_UPDATE_BLE_FROM_ESP   = 148  // DFU BLE từ ESP
CODE_RESET_TO_AP           = 149  // Reset về AP mode
CODE_RESET_TO_SMART_CONFIG = 150  // Reset về SmartConfig
```

---

## MQTT Broker - Có thể đổi server không?

### Kết quả phân tích

**Không có lệnh MQTT nào để đổi broker server.**

- `MqttManager.DEFAULT_SERVER_URI = "url"` — chỉ là placeholder trong Java
- URI thực được lấy từ: `HunonicSecureNative.getMqttInfo()` — native function trong `libhunonicsecure.so`
- Hàm này trả về struct `MqttInfo { username, password, uri, tcp }`
- Broker được cấu hình cứng trong native lib, không qua lệnh MQTT

### Cách lấy MQTT broker credentials

**Cách 1: HTTP endpoint (dễ nhất)**

```
GET http://infoserver.hunonicpro.com/HardwareAPI/getInfoMqtt.php
```

Endpoint này được dùng trong `api.py` của integration. Nếu response trả về plaintext → có ngay credentials.

**Cách 2: Frida hook (trên Android rooted)**

```js
// Hook HunonicSecureNative.getMqttInfo()
Java.use("com.iot.secure.HunonicSecureNative").getMqttInfo.implementation = function() {
    let result = this.getMqttInfo();
    result.forEach(info => console.log(JSON.stringify({
        uri: info.uri.value,
        tcp: info.tcp.value,
        user: info.username.value,
        pass: info.password.value
    })));
    return result;
};
```

**Cách 3: Reverse `libhunonicsecure.so`**

Dùng Ghidra/IDA để decompile native lib, tìm string literals chứa MQTT URI.

### Hướng để "đổi MQTT server"

Không có cách nào gửi lệnh đổi broker qua MQTT. Các phương án thay thế:

| Phương án | Mức độ |
|---|---|
| Flash ESPHome qua OTA (code 129) | Triệt để, mất luôn cloud control |
| DNS spoofing hostname MQTT | Nếu broker dùng hostname (không phải IP) |
| MITM SSL (nếu không cert-pinning) | Capture traffic thực |

---

## Provisioning (Cài đặt ban đầu)

- **SmartConfig (EspTouch)**: gửi WiFi credentials qua UDP broadcast
- **AP Mode**: kết nối trực tiếp đến WiFi hotspot của thiết bị, dùng FunSDK HTTP API

---

## Mã hóa MQTT

- Key và IV ban đầu: `"0000000000000000"` (16 bytes ASCII `0x30`)
- Key thực: `AES_CBC(PKCS7(root_id_utf8), KEY_ZERO, IV_ZERO)[4:20]`
- `root_id` lấy được qua REST API sau khi đăng nhập

```python
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
import base64

KEY_ZERO = IV_ZERO = b"0000000000000000"

def derive_key(root_id: str) -> tuple[bytes, bytes]:
    data = root_id.encode()
    # PKCS7 pad đến bội số 16
    pad_len = 16 - (len(data) % 16)
    padded = data + bytes([pad_len] * pad_len)
    # AES-128-CBC encrypt
    cipher = Cipher(algorithms.AES(KEY_ZERO), modes.CBC(IV_ZERO))
    enc = cipher.encryptor()
    encrypted = enc.update(padded) + enc.finalize()
    return encrypted[4:20], IV_ZERO  # (key, iv)
```

---

## Hướng tiếp cận cho Home Assistant

1. **REST API polling**: `api.hunonicpro.com/v3/` để lấy trạng thái (30s interval)
2. **Cloud MQTT**: Kết nối đến broker Hunonic (credentials từ `getInfoMqtt.php`)
   - Nhận push từ thiết bị ngay lập tức qua `topicsub`
   - Gửi lệnh qua `topicpub` với AES-CBC encryption
3. **ESPHome OTA** (nâng cao): Flash ESPHome qua MQTT command 129 để thoát cloud

---

## Kết luận

Không có local control path khả dụng out-of-the-box.  
Integration phụ thuộc vào Hunonic cloud MQTT.  
Có thể flash ESPHome nếu lấy được MQTT credentials từ `getInfoMqtt.php`.

---

> [!CAUTION]
> **CHỈ DÙNG CHO MỤC ĐÍCH CÁ NHÂN — KHÔNG THƯƠNG MẠI.**
>
> - Repo/tài liệu này được tạo qua reverse-engineering nhằm mục đích nghiên cứu và liên thông cá nhân (interoperability) với thiết bị **bạn sở hữu**.
> - **KHÔNG** dùng cho mục đích thương mại dưới bất kỳ hình thức nào.
> - **Tự kiểm tra kỹ các quy định về sở hữu trí tuệ, điều khoản dịch vụ và pháp luật hiện hành** tại nơi bạn sinh sống **trước khi** sử dụng. Bạn tự chịu hoàn toàn trách nhiệm.
> - **KHÔNG** chia sẻ, phát tán, hay sử dụng để tấn công/chống phá/làm gián đoạn hệ thống Hunonic hoặc bất kỳ hệ thống nào.
> - Tác giả không chịu trách nhiệm cho bất kỳ thiệt hại hay hậu quả pháp lý nào phát sinh từ việc sử dụng repo này.
