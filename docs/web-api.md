# Web API Hunonic (web.hunonic.com)

> [!CAUTION]
> **CHỈ DÙNG CHO MỤC ĐÍCH CÁ NHÂN — KHÔNG THƯƠNG MẠI.**
>
> - Repo/tài liệu này được tạo qua reverse-engineering nhằm mục đích nghiên cứu và liên thông cá nhân (interoperability) với thiết bị **bạn sở hữu**.
> - **KHÔNG** dùng cho mục đích thương mại dưới bất kỳ hình thức nào.
> - **Tự kiểm tra kỹ các quy định về sở hữu trí tuệ, điều khoản dịch vụ và pháp luật hiện hành** tại nơi bạn sinh sống **trước khi** sử dụng. Bạn tự chịu hoàn toàn trách nhiệm.
> - **KHÔNG** chia sẻ, phát tán, hay sử dụng để tấn công/chống phá/làm gián đoạn hệ thống Hunonic hoặc bất kỳ hệ thống nào.
> - Tác giả không chịu trách nhiệm cho bất kỳ thiệt hại hay hậu quả pháp lý nào phát sinh từ việc sử dụng repo này.

Web API phục vụ giao diện web và Smart TV của Hunonic.  
Khác với REST API chính (`api.hunonicpro.com`), Web API dùng riêng cho **đăng nhập QR** và **MQTT qua WebSocket**.

---

## Base URL

```
https://web.hunonic.com/api
```

**Lưu ý về cấu trúc path:** một số endpoint có prefix `/api/api/` (double slash) do cách JS bundle cấu hình axios:

```
Base:     https://web.hunonic.com/api
instance: ds = axios.create({ baseURL: "https://web.hunonic.com/api" })
ds.post("/api/auth/xxx")   →  POST https://web.hunonic.com/api/api/auth/xxx
ds.post("/auth/xxx")       →  POST https://web.hunonic.com/api/auth/xxx
```

Các endpoint dưới đây ghi rõ URL đầy đủ để tránh nhầm lẫn.

---

## Đăng nhập (số điện thoại + mật khẩu)

> Đây là **phương thức đăng nhập chính** dùng cho integration. (QR login bên dưới chỉ còn để tham khảo.)

```
POST https://web.hunonic.com/api/api/auth/login
Content-Type: application/json

{
  "phone": "0975xxxxxx",
  "password": "<md5(mật khẩu) — hex thường>"
}
```

- `password` là **MD5 hex của mật khẩu** (app: `encodeMd5(password)`), KHÔNG gửi mật khẩu thô.
- Có thể thay `phone` bằng `email` nếu đăng nhập bằng email.

**Phản hồi thành công:**

```json
{ "data": "<access_token>" }
```

`access_token` dùng làm `Authorization: Bearer <token>` cho các request sau (xem `api.md`).

---

## Đăng nhập QR Code (🚧 đang phát triển)

> Tính năng QR login **đang được phát triển**, chưa khả dụng trong integration. Phần dưới là kết quả phân tích để tham khảo.

QR login dành cho web và Smart TV. Phía app mobile đóng vai trò **máy quét**, phía web/integration đóng vai trò **hiển thị mã**.

### Flow tổng quan

```
Integration                     Hunonic Server                App Mobile
    │                                  │                           │
    │  POST /api/api/auth/get-qr-login │                           │
    │─────────────────────────────────▶│                           │
    │  ← {session_id, qr_image, ...}   │                           │
    │                                  │                           │
    │  [hiển thị QR cho người dùng]    │                           │
    │                                  │   quét QR + xác nhận      │
    │                                  │◀──────────────────────────│
    │                                  │                           │
    │  POST /api/auth/polling-check-qr │                           │
    │─────────────────────────────────▶│                           │
    │  ← {access_token, ...}           │                           │
    │                                  │
    │  [dùng access_token để gọi API]  │
```

---

### 1. Tạo phiên QR

```
POST https://web.hunonic.com/api/api/auth/get-qr-login
Content-Type: application/json

{}
```

**Phản hồi thành công:**

```json
{
  "session_id": "abc123xyz",
  "qr_image": "https://...",
  "qr_text": "hunonic://qr/abc123xyz",
  "expires_at": "2025-01-01T00:05:00Z"
}
```

| Trường | Mô tả |
|---|---|
| `session_id` | ID phiên QR, dùng cho các bước tiếp theo |
| `qr_image` | URL ảnh PNG của mã QR (có thể nhúng vào `<img>`) |
| `qr_text` | Nội dung text của mã QR (deep link vào app) |
| `expires_at` | Thời điểm mã QR hết hạn (ISO 8601) |

Alias field response có thể gặp: `qrImage`, `qrUrl`, `qrText`.

---

### 2. Poll trạng thái QR

Gọi liên tục sau khi người dùng quét mã để biết khi nào đăng nhập thành công.

```
POST https://web.hunonic.com/api/auth/polling-check-qr-scanred
Content-Type: application/json

{
  "session_id": "abc123xyz"
}
```

**Phản hồi khi chưa quét:**

```json
{
  "status": "pending"
}
```

**Phản hồi khi đã quét thành công:**

```json
{
  "access_token": "eyJ...",
  "access_token_exp": "2025-01-02T00:00:00Z"
}
```

URL thay thế nếu endpoint trên không hoạt động:

```
POST https://web.hunonic.com/api/api/auth/polling-check-qr-scanred
```

---

### 3. Xác nhận đăng nhập QR

Endpoint dự phòng khi polling không trả về token. Thử theo thứ tự:

```
POST https://web.hunonic.com/api/api/auth/confirm-qr-login
POST https://web.hunonic.com/api/api/auth/qr-login-confirm
POST https://web.hunonic.com/api/api/auth/confirm-login-qr
Content-Type: application/json

{
  "session_id": "abc123xyz",
  "sessionId": "abc123xyz",
  "id": "abc123xyz"
}
```

**Phản hồi thành công:**

```json
{
  "accessToken": "eyJ...",
  "access_token": "eyJ...",
  "token": "eyJ..."
}
```

Alias field trả về có thể khác nhau giữa các endpoint — lấy cái đầu tiên có giá trị.

---

### 4. Lấy thông tin người dùng (Web Token)

Sau khi có `access_token` từ QR login, lấy profile để biết `user_id`:

```
GET https://api.hunonicpro.com/v3/user/getProfile
Authorization: Bearer <access_token>
```

hoặc:

```
GET https://api.hunonicpro.com/v3/user/getFullProfile
token_id: <access_token>
```

Token QR (`access_token`) có thể được dùng thay thế `token_id` trong các request REST API thông thường — cần kiểm tra thực tế.

---

## MQTT qua WebSocket

Web và Smart TV kết nối MQTT qua WebSocket thay vì TCP trực tiếp, phù hợp với môi trường firewall nghiêm ngặt.

| Endpoint | Mô tả |
|---|---|
| `wss://web.hunonic.com/ws` | WebSocket MQTT chính |
| `wss://web.hunonic.com/gateway/ws` | WebSocket qua gateway |

Protocol: MQTT over WebSocket (port 443).  
Có thể dùng thay cho TCP MQTT (`mqtt://broker:1883`) trong môi trường không cho phép port 1883.

---

## Nguồn phân tích

Các endpoint trên được reverse-engineer từ JS bundle của web app Hunonic:

```
https://web.hunonic.com/entry/index-CaMJHLjG.js
```

Xem thêm source JS tại file này nếu cần xác minh lại cấu trúc request.

---

> [!CAUTION]
> **CHỈ DÙNG CHO MỤC ĐÍCH CÁ NHÂN — KHÔNG THƯƠNG MẠI.**
>
> - Repo/tài liệu này được tạo qua reverse-engineering nhằm mục đích nghiên cứu và liên thông cá nhân (interoperability) với thiết bị **bạn sở hữu**.
> - **KHÔNG** dùng cho mục đích thương mại dưới bất kỳ hình thức nào.
> - **Tự kiểm tra kỹ các quy định về sở hữu trí tuệ, điều khoản dịch vụ và pháp luật hiện hành** tại nơi bạn sinh sống **trước khi** sử dụng. Bạn tự chịu hoàn toàn trách nhiệm.
> - **KHÔNG** chia sẻ, phát tán, hay sử dụng để tấn công/chống phá/làm gián đoạn hệ thống Hunonic hoặc bất kỳ hệ thống nào.
> - Tác giả không chịu trách nhiệm cho bất kỳ thiệt hại hay hậu quả pháp lý nào phát sinh từ việc sử dụng repo này.
