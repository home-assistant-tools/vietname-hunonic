# Hunonic MQTT Control Protocol

> [!CAUTION]
> **CHỈ DÙNG CHO MỤC ĐÍCH CÁ NHÂN — KHÔNG THƯƠNG MẠI.**
>
> - Repo/tài liệu này được tạo qua reverse-engineering nhằm mục đích nghiên cứu và liên thông cá nhân (interoperability) với thiết bị **bạn sở hữu**.
> - **KHÔNG** dùng cho mục đích thương mại dưới bất kỳ hình thức nào.
> - **Tự kiểm tra kỹ các quy định về sở hữu trí tuệ, điều khoản dịch vụ và pháp luật hiện hành** tại nơi bạn sinh sống **trước khi** sử dụng. Bạn tự chịu hoàn toàn trách nhiệm.
> - **KHÔNG** chia sẻ, phát tán, hay sử dụng để tấn công/chống phá/làm gián đoạn hệ thống Hunonic hoặc bất kỳ hệ thống nào.
> - Tác giả không chịu trách nhiệm cho bất kỳ thiệt hại hay hậu quả pháp lý nào phát sinh từ việc sử dụng repo này.

> Reverse-engineered từ APK `com.iot.hunonic` (React Native/Hermes) + mitmproxy SOCKS5 capture.
> **Đã kiểm chứng thực tế**: bật/tắt + nhận realtime "Đèn ban thờ 1" từ Python.

Đây là kênh điều khiển thiết bị thật mà **app mobile** dùng — KHÁC với web (web dùng `/gateway/ws` mã hóa WASM + bị khóa sau reCAPTCHA, không dùng được cho Home Assistant).

## 1. Broker (MQTT-over-WebSocket)

| | |
|---|---|
| URL | `ws://103.109.43.24:8080/ws` (dự phòng `123.30.48.196:8080`) |
| Subprotocol | `mqtt` |
| Username / Password | `bestbug` / `bigbugdmm` (tĩnh, dùng chung mọi thiết bị/tài khoản) |
| paho-mqtt | `transport="websockets"`, `ws_set_options(path="/ws")`, port `8080` |

```python
cl = paho.Client(transport="websockets", protocol=paho.MQTTv311)
cl.ws_set_options(path="/ws")
cl.username_pw_set("bestbug", "bigbugdmm")
cl.connect("103.109.43.24", 8080)
```

### Lấy broker động (getInfoMqtt)
```
GET http://infoserver.hunonicpro.com/HardwareAPI/getInfoMqtt.php?device_id=<ROOT_ID>&type=<root_type>&dev=0
```
- `device_id` = chuỗi **root_id** (vd `Zml4ZWRfbm9uY2Ux:oMA...`), KHÔNG phải id số
- Trả `{data: "<base64 AES>"}`; giải mã bằng khóa derive từ root_id → `{"broker":[{server,port,user,pass}],...}`

## 2. Topic (plaintext)

```
Điều khiển:  u/<ownerId>/<SERIAL><root_type>N<numChannels>/<ts>
Realtime:    u/<ownerId>/<SERIAL><root_type>N<numChannels>/<ts>/ok
```

Ví dụ "Đèn ban thờ" (2 kênh): `u/123456/HUN176484768232wsdatic3vN2/1769258755`

- `ownerId` = user id chủ nhà
- `SERIAL`, `ts` lấy từ field `topicpub`/`topicsub` (đang mã hóa — xem mục Hạn chế)
- App build topic: `getTopicSubV6(uid, part, ts) = "u/"+uid+"/"+part+"/"+ts`; state = topic + `/ok`

⚠️ Topic mã hóa `Zml4...` trong API KHÔNG phải topic trên dây — phải giải mã `topicpub`.

## 3. Mã hóa payload (per-device)

**AES-128-CBC**, `key = base64decode(device.key)`, `iv = base64decode(device.iv)` — lấy trực tiếp từ field `key`/`iv` của device trong `listDeviceByHome`.

```python
key = base64.b64decode(device["key"]); iv = base64.b64decode(device["iv"])
# encrypt(pkcs7(json)) → publish; decrypt(payload) → json
```

> ⚠️ **PHẢI publish CIPHERTEXT NHỊ PHÂN THÔ — KHÔNG base64.** Xác minh qua MITM app
> (SOCKS5 + patch NSC trust user-CA): app publish **64 byte thô** lên topicsub, giải mã
> ra `{"u":...,"<root_type>":0,"act_id":0,"action":N}` — **khớp từng byte** với hàm
> `encrypt_bytes_with_keyiv`. Gửi chuỗi base64 → **thiết bị BỎ QUA** (không `/ok`, không
> vào `historyByDay`). `/ok` trả về cũng là bytes thô. Đây là bug từng khiến integration
> "gửi lệnh không ăn" dù JSON đúng — đã sửa.

Fallback (device không có aesKey): derive key từ root_id — pad root_id, AES-CBC(zeros,zeros), `key=enc[4:20]`, `iv=enc[12:28]`.

## 4. Lệnh

| Mục đích | Payload (JSON, rồi AES-CBC, rồi publish) |
|---|---|
| BẬT kênh | `{"u":<uid>,"<root_type>":<ch_0based>,"act_id":0,"action":1}` |
| TẮT kênh | `{"u":<uid>,"<root_type>":<ch_0based>,"act_id":0,"action":2}` |
| Hỏi trạng thái | `{"<root_type>":105}` |

- `<root_type>` key chứa **chỉ số kênh 0-based** (index_in_root 1 → 0)
- `action`: 1 = bật, 2 = tắt
- `u` = id user đang điều khiển (bất kỳ user có quyền)

## 5. Realtime (state báo về trên topic `/ok`)

Mỗi khi BẤT KỲ AI (app, công tắc vật lý, integration) đổi trạng thái, thiết bị publish lên `<topic>/ok`:
```json
{"<root_type>":<ch>, "action":1|2, "u":<uid>, "act_id":0, "result":1}
```
Subscribe **topic cụ thể** của từng thiết bị (wildcard `u/<owner>/#` bị ACL chặn).

## Hạn chế còn lại

`SERIAL` + `ts` của topic nằm trong `topicpub`/`topicsub` được mã hóa bằng **stream cipher riêng** (nonce `fixed_nonce1`, chưa giải được — khác CBC của payload). Tạm thời cần lấy topic qua một lần capture MQTT, hoặc crack thêm cipher này.

---

> [!CAUTION]
> **CHỈ DÙNG CHO MỤC ĐÍCH CÁ NHÂN — KHÔNG THƯƠNG MẠI.**
>
> - Repo/tài liệu này được tạo qua reverse-engineering nhằm mục đích nghiên cứu và liên thông cá nhân (interoperability) với thiết bị **bạn sở hữu**.
> - **KHÔNG** dùng cho mục đích thương mại dưới bất kỳ hình thức nào.
> - **Tự kiểm tra kỹ các quy định về sở hữu trí tuệ, điều khoản dịch vụ và pháp luật hiện hành** tại nơi bạn sinh sống **trước khi** sử dụng. Bạn tự chịu hoàn toàn trách nhiệm.
> - **KHÔNG** chia sẻ, phát tán, hay sử dụng để tấn công/chống phá/làm gián đoạn hệ thống Hunonic hoặc bất kỳ hệ thống nào.
> - Tác giả không chịu trách nhiệm cho bất kỳ thiệt hại hay hậu quả pháp lý nào phát sinh từ việc sử dụng repo này.
