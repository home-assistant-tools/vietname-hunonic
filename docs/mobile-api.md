# Hunonic Mobile API — Tài liệu đầy đủ (đã verify)

> [!CAUTION]
> **CHỈ DÙNG CHO MỤC ĐÍCH CÁ NHÂN — KHÔNG THƯƠNG MẠI.**
>
> - Repo/tài liệu này được tạo qua reverse-engineering nhằm mục đích nghiên cứu và liên thông cá nhân (interoperability) với thiết bị **bạn sở hữu**.
> - **KHÔNG** dùng cho mục đích thương mại dưới bất kỳ hình thức nào.
> - **Tự kiểm tra kỹ các quy định về sở hữu trí tuệ, điều khoản dịch vụ và pháp luật hiện hành** tại nơi bạn sinh sống **trước khi** sử dụng. Bạn tự chịu hoàn toàn trách nhiệm.
> - **KHÔNG** chia sẻ, phát tán, hay sử dụng để tấn công/chống phá/làm gián đoạn hệ thống Hunonic hoặc bất kỳ hệ thống nào.
> - Tác giả không chịu trách nhiệm cho bất kỳ thiệt hại hay hậu quả pháp lý nào phát sinh từ việc sử dụng repo này.

Đây là API mà **app mobile Hunonic** (`com.iot.hunonic`) dùng. Khác với web API (`web.hunonic.com`, trả topic **mã hóa** + cần reCAPTCHA), mobile API trả **topic plaintext + key/iv** và chỉ cần một chữ ký tĩnh — nên là đường dùng cho Home Assistant.

Toàn bộ tài liệu này đã **verify thực tế**: login bằng SĐT+mật khẩu → lấy danh sách nhà/thiết bị plaintext → điều khiển MQTT, chạy 100% bằng Python thuần. Quá trình reverse: [reverse-engineering.md](reverse-engineering.md).

- **Base URL**: `https://api.hunonicpro.com/v3/`
- **Header**: `User-Agent: okhttp/4.9.2`
- **Method**: tất cả là `POST`

---

## 1. Chữ ký `signature` — bắt buộc cho mọi request

Mọi request phải kèm tham số `signature` (MD5 hex). Hàm sinh là `hunonicEncodeSign`, reverse từ Hermes bytecode (Function #7172). Code production: [`custom_components/hunonic/sign.py`](../custom_components/hunonic/sign.py).

```python
import base64, hashlib

SLOT5 = "HUNONICBIGBUG94d3c445e72ae7805fca3489edac9608c893e66b"
SLOT6 = "accessKey98ccdcbbe7b5528bec0ca31bbe8d93b4e76590dd"
ENV7  = 58

def md5(s):  return hashlib.md5(s.encode()).hexdigest()
def b64(s):  return base64.b64encode(str(s).encode()).decode()

def hunonic_sign(params: dict) -> str:
    acc = 0
    for key, value in params.items():          # params = các field ĐƯỢC KÝ
        if key == "signature":
            continue
        s = "" if value is None else str(value)
        if s == "" or float_is_zero(s):         # value rỗng hoặc bằng 0
            acc += ord(str(key)[0]) + ENV7      # = charCodeAt(0) của KEY + 58
        else:
            b = b64(s); n = len(b)              # ← base64 của VALUE
            acc += ord(b[0]) + ord(b[n // 2]) + ord(b[n - 1])
    return md5("sha256fake" + "accessKey=" + SLOT6 + md5(str(acc)) + SLOT5)
```

Điểm mấu chốt (từng làm sai khi đoán):
- `charCodeAt` chạy trên **chuỗi base64 của value**, lấy 3 vị trí: `[0]`, `[floor(len/2)]`, `[len-1]`. Vì vậy không thể fit tuyến tính theo độ dài/ký tự value gốc.
- Field có value rỗng hoặc `== 0` đi nhánh khác: cộng `charCodeAt(0)` của **tên field** + `58`.
- `acc` là **tổng cộng** (giao hoán) → **thứ tự field không ảnh hưởng**.

Verify: sinh signature khớp **45/45** request thật bắt qua MITM.

---

## 2. Hai dạng request (quyết định field nào được ký)

| Dạng | Field ký | Field gửi | Ví dụ |
|---|---|---|---|
| **A. Query-signed** | Các param trên **query string** | query string, body rỗng | `home/list`, `device/listDeviceOfHomeSelect`, hầu hết GET-style |
| **B. Login (body)** | Các field trong **multipart body** (trừ `signature`) | tất cả trong **multipart body** (gồm cả `app_role`+`signature`), query rỗng | `user/login` |

> Lý do: hàm `getURLWithSignHunonic` parse query của URL + thêm `app_role` rồi ký bộ đó. Field trong body **không** được ký (trừ login dùng đường `authPost` ký nguyên data object). Bằng chứng: `app/initHomeV2` để token/home trong body → chỉ ký `{app_role}` → `acc=199`.

Mọi request đều có `app_role=1`.

---

## 3. Đăng nhập — `user/login`

**Dạng B (login body).** Tất cả field nằm trong multipart/form-data, query rỗng.

```
POST https://api.hunonicpro.com/v3/user/login
Content-Type: multipart/form-data

password   = md5(<mật khẩu>)        # MD5 hex của mật khẩu thô
app_name   = hunonic
lang       = vi
is_pro_app = 0
phone      = <số điện thoại>         # vd 0868123456
app_role   = 1
signature  = hunonic_sign({password, app_name, lang, is_pro_app, phone, app_role})
```

- Field ký = 6 field đầu (không gồm `signature`).
- Response: `{"status": true, "data": { "token_id": "...", "id": <user_id>, "name": "...", ... }}`.
- `token_id` là token mobile dùng cho mọi request sau. Hết hạn → đăng nhập lại.
- Sai SĐT/mật khẩu/chữ ký → `{"status": false, "error_code": 1026, "message": "Lỗi xác thực!"}`.

> ⚠️ Lỗi hay gặp: để `app_role`/`signature` ở **query** thay vì body → server trả `1026` (server đọc field từ body).

Code: [`api.py::login_mobile()`](../custom_components/hunonic/api.py).

---

## 4. Danh sách nhà — `home/list`

**Dạng A (query-signed).**

```
POST https://api.hunonicpro.com/v3/home/list?token_id=<token>&app_role=1&signature=<sig>
(body rỗng)

signature = hunonic_sign({token_id, app_role})
```

Response `data`: mảng nhà, mỗi nhà `{id, name, user_id, home_ref, active, ...}`. `id` chính là `home_id`.

Các endpoint nhà liên quan (cùng dạng A, ký `{token_id, app_role}`): `home/listHomeReceived`, `home/listHomeShare`.

---

## 5. Danh sách thiết bị — `device/listDeviceOfHomeSelect`

**Dạng A (query-signed).** Trả về **topic plaintext + key/iv** — đủ để điều khiển MQTT.

```
POST https://api.hunonicpro.com/v3/device/listDeviceOfHomeSelect?token_id=<token>&home_id=<home>&app_role=1&signature=<sig>
(body rỗng)

signature = hunonic_sign({token_id, home_id, app_role})
```

Cấu trúc `data`: `[ home ]` → `home.rooms[]` → `room.devices[]`. Mỗi device gồm các field quan trọng:

| Field | Ý nghĩa |
|---|---|
| `root_id` | ID phần cứng, vd `HUN174632861499wsdatic3vN3` |
| `root_type` | Loại thiết bị, vd `wsdatic3v` (dùng trong payload lệnh) |
| `index_in_root` | Kênh (1-based) trong thiết bị nhiều kênh |
| `name` | Tên hiển thị |
| `topicsub` | Topic **publish lệnh** tới, vd `u/123456/HUN...wsdatic3vN3/1746958418` |
| `topicpub` | Topic **nhận trạng thái** = `topicsub` + `/ok` |
| `key`, `iv` | Khóa AES-128-CBC (base64) để mã hóa/giải mã payload |
| `value` | Trạng thái hiện tại (REST), vd `{"turn": 1}` |
| `state` | **Online (`1`) / offline (`2`)** — chỉ báo CHÍNH XÁC (giống app). |
| `DeviceStatus` | Thường `null` — KHÔNG đáng tin, dùng `state` thay. |

> ⚠️ **`listDeviceOfHomeSelect` chỉ trả thiết bị của ĐÚNG `home_id` truyền vào** (home_id rỗng = chỉ nhà chính) → **bỏ sót thiết bị nhà được share**. Để lấy **TẤT CẢ nhà** (gồm nhà share) trong 1 call, dùng **`device/listDeviceByHome`** với `home_id` rỗng — cùng cấu trúc, cũng trả topic/key/iv plaintext. (Xác minh qua MITM app + đối chiếu live.)
>
> ⚠️ **Online/offline:** dùng field **`state`** (1/2), KHÔNG dùng `last_online` (thường cũ/`null` → báo offline sai). Endpoint `device/getMultiDeviceInfo` (body multipart `device_ids=[...]`) cũng trả `state` y vậy.

Code: [`api.py::get_devices_mobile()`](../custom_components/hunonic/api.py).

---

## 6. Điều khiển thiết bị qua MQTT

Sau khi có `topicsub`/`topicpub`/`key`/`iv`, điều khiển qua **MQTT-over-WebSocket** — xem [mqtt-control.md](mqtt-control.md) cho chi tiết đầy đủ. Tóm tắt:

- **Broker**: `ws://103.109.43.24:8080/ws` (subprotocol `mqtt`), user/pass tĩnh `bestbug`/`bigbugdmm`. Pool 6 broker bridged (publish broker nào cũng tới).
- **Mã hóa**: AES-128-CBC, `key=base64decode(device.key)`, `iv=base64decode(device.iv)` (lấy thẳng, **không** derive từ root_id).
- ⚠️ **Publish CIPHERTEXT NHỊ PHÂN THÔ — KHÔNG base64.** Gửi chuỗi base64 → thiết bị BỎ QUA (không `/ok`, không vào history). Xác minh qua MITM app (app publish 64 byte thô).
- **Lệnh** (publish tới `topicsub`): `{"u": <user_id>, "<root_type>": 0, "act_id": 0, "action": <N>}`. Công tắc nhiều kênh: kênh N → **BẬT = 2N−1, TẮT = 2N** (`<root_type>` là HẰNG SỐ 0, KÊNH nằm trong `action`).
- **Trạng thái** (nhận trên `topicpub` = `.../ok`, cũng bytes thô): `{..., "action": <N>, "result": 1}`.

Code: [`coordinator.py`](../custom_components/hunonic/coordinator.py) (`encrypt_bytes_with_keyiv`, `async_control_device`).

---

## 7. Các endpoint khác (cùng Dạng A)

Đã quan sát qua MITM, tất cả ký theo query params + `app_role`:

| Endpoint | Field ký thêm | Mục đích |
|---|---|---|
| `app/initHomeV2` | (chỉ `app_role`) | Dữ liệu khởi tạo app (mqtt, version, popup...) |
| `device/listDeviceByHome` | `token_id, home_id` | **Thiết bị TẤT CẢ nhà** (home_id rỗng) — plaintext topic/key/iv. **Nên dùng cái này** thay `listDeviceOfHomeSelect`. |
| `device/getMultiDeviceInfo` | (multipart body: `token_id, device_ids=[...], app_role`) | Trạng thái online (`state` 1/2) nhiều thiết bị. **KHÔNG phải query** — field ở body, ký theo body. |
| `collection/listCollection`, `collection/listCollectionV2` | `token_id, home_id` | Kịch bản / nhóm |
| `device/listDeviceReceived` | `token_id, device_invite` | Thiết bị được chia sẻ |
| `user/getFullProfile`, `user/getTeam` | `token_id` | Hồ sơ người dùng |
| `notify/listNotifyApp` | `phone` | Thông báo |
| `device/listAlarmByDevice`, `device/listAlarmCycle` | `token_id, device_id` | Lịch/báo thức thiết bị |

> `signature` mismatch hoặc thiếu → response `error_code` (vd `1026`). Server **luôn** tính lại signature từ field nó nhận, nên phải ký đúng bộ field gửi đi.

---

## 8. Tham chiếu nhanh (pseudo-flow)

```
data   = login_mobile(phone, password)        # → token_id
homes  = POST home/list  ⟨token_id⟩           # → chọn home_id
devs   = POST device/listDeviceOfHomeSelect ⟨token_id, home_id⟩   # → topic/key/iv
                                              # → MQTT-over-WS điều khiển
```

Toàn bộ logic này nằm trong integration HA: [`api.py`](../custom_components/hunonic/api.py), [`sign.py`](../custom_components/hunonic/sign.py), [`coordinator.py`](../custom_components/hunonic/coordinator.py).

---

> [!CAUTION]
> **CHỈ DÙNG CHO MỤC ĐÍCH CÁ NHÂN — KHÔNG THƯƠNG MẠI.**
>
> - Repo/tài liệu này được tạo qua reverse-engineering nhằm mục đích nghiên cứu và liên thông cá nhân (interoperability) với thiết bị **bạn sở hữu**.
> - **KHÔNG** dùng cho mục đích thương mại dưới bất kỳ hình thức nào.
> - **Tự kiểm tra kỹ các quy định về sở hữu trí tuệ, điều khoản dịch vụ và pháp luật hiện hành** tại nơi bạn sinh sống **trước khi** sử dụng. Bạn tự chịu hoàn toàn trách nhiệm.
> - **KHÔNG** chia sẻ, phát tán, hay sử dụng để tấn công/chống phá/làm gián đoạn hệ thống Hunonic hoặc bất kỳ hệ thống nào.
> - Tác giả không chịu trách nhiệm cho bất kỳ thiệt hại hay hậu quả pháp lý nào phát sinh từ việc sử dụng repo này.
