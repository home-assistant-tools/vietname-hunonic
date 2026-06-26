# Tài liệu API Hunonic

> [!CAUTION]
> **CHỈ DÙNG CHO MỤC ĐÍCH CÁ NHÂN — KHÔNG THƯƠNG MẠI.**
>
> - Repo/tài liệu này được tạo qua reverse-engineering nhằm mục đích nghiên cứu và liên thông cá nhân (interoperability) với thiết bị **bạn sở hữu**.
> - **KHÔNG** dùng cho mục đích thương mại dưới bất kỳ hình thức nào.
> - **Tự kiểm tra kỹ các quy định về sở hữu trí tuệ, điều khoản dịch vụ và pháp luật hiện hành** tại nơi bạn sinh sống **trước khi** sử dụng. Bạn tự chịu hoàn toàn trách nhiệm.
> - **KHÔNG** chia sẻ, phát tán, hay sử dụng để tấn công/chống phá/làm gián đoạn hệ thống Hunonic hoặc bất kỳ hệ thống nào.
> - Tác giả không chịu trách nhiệm cho bất kỳ thiệt hại hay hậu quả pháp lý nào phát sinh từ việc sử dụng repo này.

> **Đường dùng cho Home Assistant là API mobile** (`api.hunonicpro.com`) — đã verify đầy đủ. Xem **[mobile-api.md](mobile-api.md)** cho login, danh sách nhà/thiết bị (topic plaintext + key/iv) và **thuật toán chữ ký** `hunonicEncodeSign`. File này giữ tham chiếu để đối chiếu.

## Tổng quan kiến trúc

Hệ thống Hunonic có nhiều lớp endpoint:

| Dịch vụ | URL | Tài liệu |
|---|---|---|
| **Đăng nhập mobile (phone + password)** ✅ | `https://api.hunonicpro.com/v3/user/login` | [mobile-api.md](mobile-api.md) §3 |
| **REST mobile (home/device list, topic plaintext)** ✅ | `https://api.hunonicpro.com/v3/` | [mobile-api.md](mobile-api.md) |
| Web API (device list — topic **mã hóa**) | `https://web.hunonic.com/api/api/` | [web-api.md](web-api.md) |
| MQTT Broker (điều khiển thật) | `ws://103.109.43.24:8080/ws` | [mqtt-control.md](mqtt-control.md) |

Kiến trúc giao tiếp gồm hai lớp:
- **REST API**: Quản lý tài khoản, nhà, phòng, thiết bị, kịch bản. Mọi request mobile cần `signature` (xem [mobile-api.md](mobile-api.md) §1).
- **MQTT**: Điều khiển thiết bị thời gian thực qua cloud broker, payload mã hóa AES-128-CBC bằng `key`/`iv` của device.

---

## Xác thực (Authentication)

### Đăng nhập mobile bằng số điện thoại + mật khẩu (phương thức chính — đã verify) ✅

```
POST https://api.hunonicpro.com/v3/user/login
Content-Type: multipart/form-data

password=md5(<mật khẩu>), app_name=hunonic, lang=vi, is_pro_app=0,
phone=<số điện thoại>, app_role=1, signature=<hunonic_sign(...)>
```

- TẤT CẢ field nằm trong **body** (gồm cả `app_role`, `signature`), query **rỗng**.
- `password` là **MD5 hex** của mật khẩu thô.
- Phản hồi: `{"status": true, "data": {"token_id": "...", "id": <user_id>, ...}}`.

Chi tiết đầy đủ + thuật toán ký: **[mobile-api.md](mobile-api.md)**.

> Phỏng đoán cũ `POST web.hunonic.com/.../auth/login` (JSON) **không phải** đường đã verify — giữ ở [web-api.md](web-api.md) để tham khảo.

### QR Login (🚧 đang phát triển)

Phía web/integration **tạo và hiển thị** mã QR, phía app mobile **quét** để xác nhận. Tính năng đang được phát triển, chưa khả dụng.

Xem chi tiết toàn bộ flow (tạo phiên → poll → xác nhận) tại **[docs/web-api.md](web-api.md)**.

Tóm tắt các endpoint:

| Bước | Endpoint | Ghi chú |
|---|---|---|
| Tạo phiên QR | `POST https://web.hunonic.com/api/api/auth/get-qr-login` | Trả về `session_id`, `qr_image` |
| Poll trạng thái | `POST https://web.hunonic.com/api/auth/polling-check-qr-scanred` | Trả về `access_token` khi quét xong |
| Xác nhận (dự phòng) | `POST https://web.hunonic.com/api/api/auth/confirm-qr-login` | Fallback nếu polling chưa trả token |

`access_token` nhận được từ QR login có thể dùng thay `token_id` trong các request REST API thông thường.

---

## Tham số chung

Các tham số sau xuất hiện ở hầu hết các request:

| Tham số | Kiểu | Vị trí | Mô tả |
|---|---|---|---|
| `token_id` | string | query / body | Token phiên làm việc, lấy từ bước đăng nhập |
| `signature` | string | query | Chữ ký xác thực request (HMAC hoặc hash tùy endpoint) |
| `Authorization` | string | header | `Bearer <token_id>` — dùng cho các request POST yêu cầu header |

---

## API Endpoints

### Người dùng (User)

Base path: `https://api.hunonicpro.com/v3/user/`

| Phương thức | Path | Mô tả |
|---|---|---|
| POST | `user/addInfoLogin` | Đăng nhập bằng số điện thoại và OTP, trả về `token_id` |
| POST | `user/checkPassword` | Kiểm tra mật khẩu hiện tại của người dùng |
| POST | `user/changePasswordByPhoneNumber` | Đổi mật khẩu thông qua xác minh số điện thoại |
| GET | `user/getFullProfile` | Lấy toàn bộ thông tin hồ sơ người dùng |
| GET | `user/getProfileByPhone` | Tìm kiếm người dùng theo số điện thoại |
| POST | `user/updateProfile` | Cập nhật thông tin hồ sơ (tên, avatar, …) |
| GET | `user/getHistoryLoginUser` | Xem lịch sử đăng nhập của tài khoản |
| POST | `user/loginAnother` | Chuyển sang hoạt động trên tài khoản khác |

---

### Nhà (Home)

Base path: `https://api.hunonicpro.com/v3/home/`

| Phương thức | Path | Mô tả |
|---|---|---|
| POST | `home/add` | Tạo một ngôi nhà mới |
| POST | `home/shareHome` | Chia sẻ nhà với người dùng khác theo số điện thoại |
| POST | `home/acceptShare` | Chấp nhận lời mời chia sẻ nhà |
| POST | `home/denyShare` | Từ chối lời mời chia sẻ nhà |
| GET | `home/listHomeReceived` | Lấy danh sách các nhà được chia sẻ tới tài khoản |
| POST | `home/initTransferscale` | Khởi tạo yêu cầu chuyển quyền sở hữu nhà |
| POST | `home/acceptTransferscale` | Xác nhận nhận quyền sở hữu nhà từ người chuyển |

---

### Phòng (Room)

Base path: `https://api.hunonicpro.com/v3/room/`

| Phương thức | Path | Mô tả |
|---|---|---|
| POST | `room/addRoom` | Thêm phòng mới vào một ngôi nhà |
| POST | `room/updateRoom` | Cập nhật tên hoặc thông tin phòng |
| POST | `room/sortRoom` | Sắp xếp lại thứ tự hiển thị các phòng |
| POST | `room/changeMultiDeviceRoom` | Di chuyển một hoặc nhiều thiết bị sang phòng khác |

---

### Thiết bị (Device)

Base path: `https://api.hunonicpro.com/v3/device/`

| Phương thức | Path | Mô tả |
|---|---|---|
| GET | `device/listDeviceByHome` | Lấy danh sách tất cả thiết bị trong một ngôi nhà |
| GET | `device/getDeviceRoot` | Lấy thông tin chi tiết của thiết bị gốc (gateway/hub) |
| GET | `device/getHistoryDevice` | Xem lịch sử hoạt động của thiết bị |
| GET | `device/historyByDay` | Lọc lịch sử thiết bị theo ngày cụ thể |
| GET | `device/historyByType` | Lọc lịch sử thiết bị theo loại sự kiện |
| POST | `device/shareDevice` | Chia sẻ quyền điều khiển thiết bị với người dùng khác |
| POST | `device/acceptShareDevice` | Chấp nhận lời mời chia sẻ thiết bị |
| POST | `device/setHiddenDevice` | Ẩn hoặc hiện thiết bị trong giao diện |
| GET | `device/listDeviceSupportPowerMeasure` | Lấy danh sách thiết bị hỗ trợ đo điện năng tiêu thụ |

---

### Scene Collection (Kịch bản)

Base path: `https://api.hunonicpro.com/v3/`

| Phương thức | Path | Mô tả |
|---|---|---|
| GET | `collection/listCollectionButton` | Lấy danh sách tất cả kịch bản (scene) trong nhà |
| POST | `collection/changeActiveCollection` | Kích hoạt hoặc tắt một kịch bản |
| GET | `groupAction/list` | Lấy danh sách các nhóm hành động đã tạo |
| POST | `groupAction/add` | Tạo nhóm hành động mới |
| POST | `groupAction/update` | Cập nhật nhóm hành động hiện có |
| POST | `groupAction/delete` | Xóa nhóm hành động |
| POST | `MqttControl/executeCollection` | Thực thi một kịch bản thông qua MQTT |

---

### MQTT Broker Info

Lấy thông tin kết nối MQTT cho một thiết bị cụ thể:

```
GET http://infoserver.hunonicpro.com/HardwareAPI/getInfoMqtt.php?device_id=<id>
```

**Phản hồi mẫu:**

```json
{
  "uri": "mqtt://broker.hunonicpro.com",
  "tcp": 1883,
  "username": "device_user",
  "password": "device_pass"
}
```

| Trường | Mô tả |
|---|---|
| `uri` | Địa chỉ MQTT broker |
| `tcp` | Cổng TCP của broker |
| `username` | Tên đăng nhập MQTT |
| `password` | Mật khẩu MQTT |

---

## Giao thức MQTT

### Mô hình dữ liệu thiết bị

| Trường | Kiểu | Mô tả |
|---|---|---|
| `device_id` | string | Mã định danh duy nhất của thiết bị |
| `root_id` | string | Mã định danh của thiết bị gốc (dùng để tính khóa mã hóa) |
| `root_type` | string | Loại thiết bị gốc (xem bảng loại thiết bị bên dưới) |
| `channel` | int | Số kênh điều khiển (bắt đầu từ 1) |
| `status` | int | Trạng thái hiện tại của thiết bị (0 = tắt, 1 = bật) |
| `action` | int | Mã hành động gửi qua MQTT |
| `u` | int | ID người dùng thực hiện lệnh |
| `src` | int | Nguồn lệnh (1 = ứng dụng di động) |
| `act_id` | int | ID của hành động trong kịch bản (0 nếu điều khiển trực tiếp) |

---

### Loại thiết bị (root_type)

| Nhóm | Giá trị root_type | Mô tả |
|---|---|---|
| Switch / Relay | `switch`, `relay`, `dimmer` | Công tắc, rơ-le, bộ điều chỉnh độ sáng |
| Quạt | `fan`, `fanv2` | Quạt điều khiển tốc độ |
| Cổng / Garage | `gatehun`, `gatehuwf` | Bộ điều khiển cổng kiểu Hunonic |
| Cổng v2 | `gate`, `gatev2`, `wsgate` | Bộ điều khiển cổng thế hệ mới |
| Cửa cuốn | `sdoor`, `sdoorv2`, `sdoorpro` | Bộ điều khiển cửa cuốn |

---

### Format lệnh MQTT

Topic MQTT thường có dạng: `hunonic/<root_id>/cmd`

Payload là chuỗi JSON sau khi mã hóa AES-128-CBC và base64 encode (xem phần Mã hóa MQTT).

#### Công tắc bật/tắt (switch, relay, dimmer, fan)

```json
{
  "<root_type>": 0,
  "u": <userId>,
  "act_id": 0,
  "action": <action_code>
}
```

Quy tắc tính `action_code` theo kênh (channel N):

| Trạng thái | Công thức | Ví dụ kênh 1 | Ví dụ kênh 2 | Ví dụ kênh 3 |
|---|---|---|---|---|
| Bật | `2N - 1` | 1 | 3 | 5 |
| Tắt | `2N` | 2 | 4 | 6 |

> Số lẻ = bật, số chẵn = tắt. Kênh N bật bằng action = `2N-1`, tắt bằng action = `2N`.

**Ví dụ bật kênh 2 của công tắc:**

```json
{
  "switch": 0,
  "u": 12345,
  "act_id": 0,
  "action": 3
}
```

#### Điều khiển cổng kiểu gatehun / gatehuwf

```json
{
  "u": <userId>,
  "<root_type>": 200,
  "gate_address": <action>,
  "value": 1,
  "src": 1
}
```

| Trường | Mô tả |
|---|---|
| `gate_address` | Mã hành động gửi tới cổng (do cấu hình phần cứng quy định) |
| `value` | Giá trị lệnh (thường là 1) |
| `src` | Nguồn lệnh (1 = app) |

#### Điều khiển cổng kiểu gate / gatev2 / wsgate

```json
{
  "u": <userId>,
  "<root_type>": 1,
  "src": 1,
  "action": <action_code>
}
```

#### Điều khiển cửa cuốn (sdoor, sdoorv2, sdoorpro)

```json
{
  "sdr": <action>,
  "u": <userId>,
  "src": 1
}
```

| Giá trị `action` | Mô tả |
|---|---|
| 1 | Mở cửa |
| 2 | Đóng cửa |
| 3 | Dừng lại |
| 4 | Khóa cửa |
| 5 | Mở khóa cửa |

---

### Mã hóa MQTT

Toàn bộ payload MQTT được mã hóa bằng AES-128-CBC trước khi gửi đi.

**Thuật toán:** AES-128-CBC với padding PKCS7

**Khóa gốc (key0) và IV gốc (iv0):**

```
key0 = b"0000000000000000"   # 16 ký tự '0'
iv0  = b"0000000000000000"   # 16 ký tự '0'
```

**Quy trình tính khóa dẫn xuất từ `root_id`:**

1. Lấy `root_id` dưới dạng bytes (UTF-8)
2. Áp dụng padding PKCS7 cho đủ bội số 16 byte
3. Mã hóa bằng AES-CBC với `(key0, iv0)`: `cipher_bytes = AES_CBC_encrypt(PKCS7(root_id), key0, iv0)`
4. Lấy bytes từ vị trí 4 đến 19 (16 byte): `derived_key = cipher_bytes[4:20]`
5. `derived_iv = derived_key` (IV dẫn xuất bằng với key dẫn xuất)

**Mã hóa payload:**

```
encrypted = AES_CBC_encrypt(PKCS7(payload_json_bytes), derived_key, derived_iv)
result = base64_encode(encrypted)
```

**Ví dụ Python:**

```python
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import base64

KEY0 = b"0000000000000000"
IV0  = b"0000000000000000"

def derive_key(root_id: str) -> bytes:
    padded = pad(root_id.encode(), 16)
    cipher = AES.new(KEY0, AES.MODE_CBC, IV0)
    encrypted = cipher.encrypt(padded)
    return encrypted[4:20]

def encrypt_payload(payload: str, root_id: str) -> str:
    key = derive_key(root_id)
    cipher = AES.new(key, AES.MODE_CBC, key)   # IV = key
    encrypted = cipher.encrypt(pad(payload.encode(), 16))
    return base64.b64encode(encrypted).decode()
```

---

## Dịch vụ phụ trợ

| URL | Mô tả |
|---|---|
| `https://img.hunonicpro.com/upload.php` | Upload ảnh (avatar, ảnh nhà, …) |
| `https://store.hunonicpro.com/api/v1/` | API cửa hàng sản phẩm Hunonic |
| `https://aichat.hunonicpro.com/api/` | API trợ lý AI chat tích hợp |
| `https://qlsx.hunonicpro.com/api/v1/QR/` | Tra cứu thông tin sản phẩm qua mã QR |

---

## Ghi chú bổ sung

- Tất cả các request REST nên dùng HTTPS để bảo mật dữ liệu truyền tải.
- `token_id` có thời hạn; khi hết hạn cần đăng nhập lại để lấy token mới.
- Payload MQTT phải được mã hóa đúng thuật toán AES-128-CBC trước khi publish, nếu không thiết bị sẽ bỏ qua lệnh.
- `root_id` khác với `device_id`: `root_id` là định danh phần cứng của gateway/hub, dùng để tính khóa mã hóa MQTT.
- Khi điều khiển thiết bị đa kênh (multi-channel switch), mỗi kênh tương ứng một `action_code` riêng theo công thức `2N-1` (bật) / `2N` (tắt).

---

> [!CAUTION]
> **CHỈ DÙNG CHO MỤC ĐÍCH CÁ NHÂN — KHÔNG THƯƠNG MẠI.**
>
> - Repo/tài liệu này được tạo qua reverse-engineering nhằm mục đích nghiên cứu và liên thông cá nhân (interoperability) với thiết bị **bạn sở hữu**.
> - **KHÔNG** dùng cho mục đích thương mại dưới bất kỳ hình thức nào.
> - **Tự kiểm tra kỹ các quy định về sở hữu trí tuệ, điều khoản dịch vụ và pháp luật hiện hành** tại nơi bạn sinh sống **trước khi** sử dụng. Bạn tự chịu hoàn toàn trách nhiệm.
> - **KHÔNG** chia sẻ, phát tán, hay sử dụng để tấn công/chống phá/làm gián đoạn hệ thống Hunonic hoặc bất kỳ hệ thống nào.
> - Tác giả không chịu trách nhiệm cho bất kỳ thiệt hại hay hậu quả pháp lý nào phát sinh từ việc sử dụng repo này.
