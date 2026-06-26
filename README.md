# Hunonic Smart Home - Home Assistant Integration

<div align="center">

### ☕ Ủng hộ tác giả

<b><span style="color:#16a34a">🇻🇳 Em chào các bác ạ, thật ra cái này em làm vì cộng đồng là chính, nhưng cũng tốn nhiều token và thời gian, nếu được rất mong nhận được chút tấm lòng từ các bác để em có thêm động lực đóng góp và mua thêm token AI ạ. Em xin cúi đầu cảm tạ và chúc các bác nhiều sức khỏe 🇻🇳</span></b>

<img src="https://raw.githubusercontent.com/home-assistant-tools/vietnam-hunonic/main/assets/donate-qr.png" alt="QR ủng hộ — MoMo / VietQR / napas247" width="280">

*Quét bằng MoMo / VietQR / napas247*

</div>

---

> [!CAUTION]
> **CHỈ DÙNG CHO MỤC ĐÍCH CÁ NHÂN — KHÔNG THƯƠNG MẠI.**
>
> - Repo này được tạo qua reverse-engineering nhằm mục đích nghiên cứu và liên thông cá nhân (interoperability) với thiết bị **bạn sở hữu**.
> - **KHÔNG** dùng cho mục đích thương mại dưới bất kỳ hình thức nào.
> - **Tự kiểm tra kỹ các quy định về sở hữu trí tuệ, điều khoản dịch vụ và pháp luật hiện hành** tại nơi bạn sinh sống **trước khi** sử dụng. Bạn tự chịu hoàn toàn trách nhiệm.
> - **KHÔNG** chia sẻ, phát tán, hay sử dụng để tấn công/chống phá/làm gián đoạn hệ thống Hunonic hoặc bất kỳ hệ thống nào.
> - Tác giả không chịu trách nhiệm cho bất kỳ thiệt hại hay hậu quả pháp lý nào phát sinh từ việc sử dụng repo này.

> [!WARNING]
> **Đăng nhập tích hợp này có thể khiến tài khoản bị đăng xuất khỏi app trên điện thoại** (Hunonic giới hạn số phiên đăng nhập của mỗi tài khoản).
>
> **Khuyến nghị:** tạo một **tài khoản Hunonic riêng** dành cho Home Assistant, rồi từ tài khoản chính **share cả nhà** sang tài khoản đó. Như vậy điện thoại vẫn dùng tài khoản chính bình thường, còn Home Assistant dùng tài khoản phụ — không bị đá nhau.

## Giới thiệu

[Hunonic](https://hunoicpro.com) là thương hiệu nhà thông minh Việt Nam, cung cấp các thiết bị điều khiển thông minh cho hộ gia đình và doanh nghiệp.

Integration này cho phép kết nối và điều khiển thiết bị Hunonic trực tiếp từ Home Assistant thông qua MQTT cloud, mang lại trải nghiệm nhà thông minh toàn diện.

Các loại thiết bị được hỗ trợ (**56 root_type**):

| Nhóm | Số loại | Ví dụ root_type |
|---|---|---|
| Công tắc thông minh | 31 | wsdatic3v, wswitch, swminiv2, swshockv2... |
| Cửa cuốn | 10 | sdoor2 → sdoor12 |
| Đèn LED | 6 | swled, dled, duhalled... |
| Cổng tự động / Gate hub | 5 | gatehun, gate, wsgate... |
| Quạt thông minh | 4 | fanwifi, fanac, fandc, fanacir (on/off + 3 mức tốc độ) |

> **Công tơ điện (`elmeter`) & công tơ tổng / aptomat wifi (`atmwifi`, `atmwifiv2`):** đóng/cắt (on/off) + sensor **điện năng & tiền điện** tháng này / tháng trước (kWh, VND) + **công suất tức thời** (W). ⚠️ `atmwifi*` là **aptomat tổng — TẮT là mất điện cả nhà**, đừng đưa vào automation vô ý.
>
> Chưa hỗ trợ: IR (irwifiv2, irchildv2 — điều hòa/TV), thiết bị RF (hsrf, rfdb...). Sẽ bổ sung sau.

## Tính năng

- **Đăng nhập 1 lần** bằng số điện thoại + mật khẩu — không cần đăng nhập lại cho từng nhà (Hunonic giới hạn phiên, login 2 lần bị đá).
- **Nạp tất cả nhà của tài khoản** (gồm nhà được chia sẻ): sau khi đăng nhập **tick chọn nhà** muốn nạp (checkbox, mặc định tất cả). Đổi danh sách nhà sau qua nút **Cấu hình** — không cần đăng nhập lại.
- **Mỗi nhà là một "trạm trung chuyển" riêng** — thiết bị gom theo nhà.
- Tự động phát hiện và thêm thiết bị; **thiết bị mới tự xuất hiện** không cần cấu hình lại.
- Điều khiển realtime qua MQTT cloud (lệnh mã hóa AES nhị phân); **tự đăng nhập lại** khi token hết hạn, **tự kết nối lại** + **tự bám broker mới** khi Hunonic đổi server.
- **Trạng thái online/offline chính xác** (dùng field `state` như app, không phụ thuộc `last_online` cũ).

## Cài đặt qua HACS

### Yêu cầu

- Home Assistant phiên bản 2024.1 trở lên
- HACS đã được cài đặt

> [!IMPORTANT]
> **Khuyến nghị: tạo một TÀI KHOẢN HUNONIC MỚI riêng cho Home Assistant.**
> Hunonic giới hạn số phiên đăng nhập — nếu dùng tài khoản chính (đang đăng nhập trên điện thoại) cho Home Assistant, **điện thoại của bạn có thể bị đăng xuất**.
> Cách làm: đăng ký 1 tài khoản Hunonic mới (số điện thoại khác) → từ app trên tài khoản chính, **chia sẻ nhà** sang tài khoản mới → dùng tài khoản mới này cho Home Assistant. Integration sẽ **tự động chấp nhận** nhà được share khi đăng nhập.

### Các bước cài đặt

1. (Khuyến nghị) Tạo **tài khoản Hunonic mới** và **share nhà** từ tài khoản chính sang (xem cảnh báo trên)
2. Mở HACS trong Home Assistant
3. Vào mục **Integrations**
4. Nhấn vào biểu tượng ba chấm ở góc trên bên phải, chọn **Custom repositories**
5. Thêm địa chỉ repository: `home-assistant-tools/vietnam-hunonic`
6. Chọn loại: **Integration**
7. Tìm kiếm **Hunonic** trong HACS và nhấn **Install**
8. Khởi động lại Home Assistant
9. Vào **Settings > Devices & Services > Add Integration**
10. Tìm và chọn **Hunonic**
11. Đăng nhập bằng **số điện thoại + mật khẩu** của **tài khoản mới** vừa tạo
12. Ở bước **"Chọn nhà"**, tick các nhà muốn nạp (mặc định tất cả) → Xong

> Đổi danh sách nhà sau: vào tích hợp Hunonic → **Cấu hình** → tick lại → lưu (tự tải lại, không cần đăng nhập lại).
>
> Lưu ý: nhà được chia sẻ phải share **kèm quyền thiết bị** sang tài khoản HA thì thiết bị mới hiện (chỉ share "nhà" mà không share thiết bị thì nhà đó sẽ trống).

## Cấu trúc dự án

```
hunoic/
├── custom_components/hunonic/   # HACS integration cho Home Assistant
├── hunonic/                     # Python client library
└── docs/                        # Tài liệu chi tiết
```

## Tài liệu

- [Mobile API](docs/mobile-api.md) — **API đã verify đầy đủ**: login phone+password, danh sách nhà/thiết bị (topic plaintext + key/iv), **thuật toán chữ ký `hunonicEncodeSign`**, toàn bộ endpoint
- [MQTT Control](docs/mqtt-control.md) — **protocol điều khiển thật (đã kiểm chứng)**: broker 8080/ws, lệnh, realtime, mã hóa key/iv
- [Reverse Engineering](docs/reverse-engineering.md) — toàn bộ quá trình reverse: MITM, patch APK minimal-change, mobile API plaintext, crack chữ ký từ Hermes bytecode
- [API Reference](docs/api.md) — tổng quan endpoint, đối chiếu web vs mobile
- [Web API](docs/web-api.md) — QR login (web), topic mã hóa
- [Local Control](docs/local-control.md) — phân tích chip, OTA, ESPHome

## Giấy phép

MIT License

---

> [!CAUTION]
> **CHỈ DÙNG CHO MỤC ĐÍCH CÁ NHÂN — KHÔNG THƯƠNG MẠI.**
>
> - Repo này được tạo qua reverse-engineering nhằm mục đích nghiên cứu và liên thông cá nhân (interoperability) với thiết bị **bạn sở hữu**.
> - **KHÔNG** dùng cho mục đích thương mại dưới bất kỳ hình thức nào.
> - **Tự kiểm tra kỹ các quy định về sở hữu trí tuệ, điều khoản dịch vụ và pháp luật hiện hành** tại nơi bạn sinh sống **trước khi** sử dụng. Bạn tự chịu hoàn toàn trách nhiệm.
> - **KHÔNG** chia sẻ, phát tán, hay sử dụng để tấn công/chống phá/làm gián đoạn hệ thống Hunonic hoặc bất kỳ hệ thống nào.
> - Tác giả không chịu trách nhiệm cho bất kỳ thiệt hại hay hậu quả pháp lý nào phát sinh từ việc sử dụng repo này.
