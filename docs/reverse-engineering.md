# Quá trình Reverse-Engineering Hunonic

> [!CAUTION]
> **CHỈ DÙNG CHO MỤC ĐÍCH CÁ NHÂN — KHÔNG THƯƠNG MẠI.**
>
> - Repo/tài liệu này được tạo qua reverse-engineering nhằm mục đích nghiên cứu và liên thông cá nhân (interoperability) với thiết bị **bạn sở hữu**.
> - **KHÔNG** dùng cho mục đích thương mại dưới bất kỳ hình thức nào.
> - **Tự kiểm tra kỹ các quy định về sở hữu trí tuệ, điều khoản dịch vụ và pháp luật hiện hành** tại nơi bạn sinh sống **trước khi** sử dụng. Bạn tự chịu hoàn toàn trách nhiệm.
> - **KHÔNG** chia sẻ, phát tán, hay sử dụng để tấn công/chống phá/làm gián đoạn hệ thống Hunonic hoặc bất kỳ hệ thống nào.
> - Tác giả không chịu trách nhiệm cho bất kỳ thiệt hại hay hậu quả pháp lý nào phát sinh từ việc sử dụng repo này.

Tài liệu ghi lại toàn bộ hành trình reverse-engineer protocol điều khiển Hunonic, **để người sau không phải dò lại từ đầu**.

---

## 0. Kết quả cuối

Điều khiển + nhận realtime thiết bị Hunonic qua **MQTT-over-WebSocket** (đường app mobile dùng). Đã **verify thực tế**: bật/tắt "Đèn ban thờ 1" vật lý từ Python. Xem [mqtt-control.md](mqtt-control.md) cho protocol đầy đủ.

Chữ ký API mobile `hunonicEncodeSign` đã **crack hoàn toàn** (§7) — dịch nguyên văn từ Hermes bytecode, verify 45/45 request thật. Login mobile (SĐT+mật khẩu) cũng **đã replicate** (§7) → token_id → device plaintext (topic/key/iv) → MQTT control. **Toàn bộ pipeline chạy 100% bằng Python thuần**, không phụ thuộc app. Code: [`sign.py`](../custom_components/hunonic/sign.py), [`api.py`](../custom_components/hunonic/api.py).

---

## 1. Hai đường điều khiển — chọn đường mobile

| | Web (`web.hunonic.com`) | Mobile (`api.hunonicpro.com`) |
|---|---|---|
| Transport điều khiển | `/gateway/ws` — JSON mã hóa bằng **WASM** | MQTT-over-WS `:8080/ws` |
| Chống bot | **reCAPTCHA** (`sendTrustWs`) | Không |
| Topic trong device API | **mã hóa** (`Zml4...`) | **plaintext** (`u/123456/HUN.../ts`) |
| Dùng cho HA? | ❌ (reCAPTCHA + WASM) | ✅ |

→ Web không khả thi cho HA headless. Dùng **đường mobile MQTT**.

---

## 2. Broker MQTT — phát hiện qua MITM

- App KHÔNG dùng MQTT TCP 1883 mà **MQTT-over-WebSocket `ws://103.109.43.24:8080/ws`** (subprotocol `mqtt`).
- Lúc đầu tưởng dùng `/ws` (mqtt broker), thực ra app JSON-service ở `/gateway/ws` (web) còn mobile MQTT ở `:8080/ws`.
- User/pass tĩnh `bestbug` / `bigbugdmm` — lấy từ `getInfoMqtt.php?device_id=<root_id>&type=<root_type>&dev=0` (giải mã AES bằng key derive từ root_id, **iv = enc[12:28] chứ không phải zeros** — đây là bug hay gặp).

## 3. Mã hóa payload — AES-CBC key/iv trực tiếp
Lệnh điều khiển mã hóa **AES-128-CBC**, `key = base64decode(device.key)`, `iv = base64decode(device.iv)` (lấy thẳng từ field `key`/`iv` của device). Verify bằng cách giải mã chính các get-info publish bắt được.

## 4. Format lệnh — bắt MITM MQTT thật
Sai lầm ban đầu: đoán format từ web bundle (`{turn,index_in_root}`) → sai. Bắt MQTT thật (websocket_message hook của mitmproxy, KHÔNG phải tcp_message vì là WS) thấy lệnh toggle thật:
```json
{"u":123456,"wsdatic3v":0,"act_id":0,"action":2}
```
`<root_type>` = chỉ số kênh 0-based, `action` 1=bật/2=tắt. State báo về topic `<topic>/ok`: `{...,"action":1,"result":1}`.

## 5. Lấy topic — Web mã hóa, Mobile plaintext
- Web `listDeviceByHome` trả `topicpub/topicsub` mã hóa (`Zml4ZWRfbm9uY2Ux:...`, nonce `fixed_nonce1`). Thử CBC/CTR/GCM + WASM Pn → **không giải được** (key server-side).
- **Mobile `listDeviceOfHomeSelect` trả PLAINTEXT**: `topicsub="u/<owner>/<root_id>/<ts>"`, `topicpub=".../ok"`, `root_id="HUN<serial><type>N<num>"`, kèm `key`/`iv`. → Chỉ cần gọi mobile API.

## 6. Patch APK để MITM mobile API (kỹ thuật minimal-change)
App = React Native + Hermes, targetSdk 35 → **không tin user CA** trừ khi khai báo `network_security_config`.

**apktool rebuild làm CRASH app** (`NinePatch.hasAlpha() null` ở EditText) — aapt2 re-encode ảnh 9-patch bị hỏng. apk-mitm cũng dính.

**Cách đúng (từ repo `~/dev/mmo/spe/re-apk`): KHÔNG rebuild resources.arsc.**
1. Recompile RIÊNG manifest bằng `aapt2 link -I android.jar -I base.apk` (resolve ref từ base.apk gốc → giữ nguyên resource id). **Nhớ thêm `versionCode` + `<uses-sdk>`** vì apktool strip chúng vào apktool.yml.
2. NSC trỏ `src="user"` (CA đã cài user cert). Compile NSC binary, ghi đè 1 res/xml có sẵn (repurpose `automotive_app_desc`, Android Auto không dùng).
3. Tráo đúng 2 entry ZIP (`AndroidManifest.xml` + `res/xml/automotive_app_desc.xml`) vào **bản sao base.apk GỐC** (nhớ `chmod 644` vì pull về read-only), xóa chữ ký cũ, ký lại.
4. `install-multiple` cả base + 3 split (cùng key).

→ App chạy (9-patch/arsc/dex nguyên byte) + tin CA mitm → MITM HTTPS được.

## 7. Chữ ký API mobile `hunonicEncodeSign` — ĐÃ CRACK

Mọi request tới `api.hunonicpro.com/v3` cần `?...&signature=<md5>`. Hàm sinh chữ ký là `hunonicEncodeSign` (JS obfuscated, biên dịch thành Hermes bytecode).

### Cách lấy chính xác thuật toán (không đoán)
Sample-fitting tuyến tính **thất bại** (đoán `acc` ≈ hàm theo độ dài/charcode của value gốc → không hội tụ vì transform phi tuyến). Nước đi dứt điểm:
1. `adb pull` `base.apk` → `unzip assets/index.android.bundle` (Hermes bytecode v96).
2. Disassemble bằng `hbc-disassembler` (gói `hermes-dec`) → `disasm.hasm` (~200MB).
3. `grep "sha256fake"` → định vị Function #7172 `hunonicEncodeSign`, đọc bytecode.
4. Các hằng `env[5..7]` nằm ở parent closure (Function #7167): `StoreToEnvironment slot 5/6/7`.

### Thuật toán (dịch nguyên văn bytecode)
```python
acc = 0
for key, value in params.items():          # params = QUERY của URL + app_role (KHÔNG gồm body)
    if key == "signature": continue
    if value == "" or float(value) == 0:    # nhánh falsy / equalVal(value, 0)
        acc += ord(str(key)[0]) + 58         # env[7] = 58
    else:
        b = base64(str(value))               # env[10] = encode111 = CryptoJS enc.Base64
        acc += ord(b[0]) + ord(b[len(b)//2]) + ord(b[len(b)-1])
signature = md5("sha256fake" + "accessKey=" + SLOT6 + md5(str(acc)) + SLOT5)
```
- `SLOT6` (env[6]) = `accessKey98ccdcbbe7b5528bec0ca31bbe8d93b4e76590dd`
- `SLOT5` (env[5]) = `HUNONICBIGBUG94d3c445e72ae7805fca3489edac9608c893e66b`
- **Mấu chốt từng bỏ sót**: `charCodeAt` chạy trên **chuỗi base64 của value** (`charCodeAt(0)`, `charCodeAt(floor(len/2))`, `charCodeAt(len-1)`), không phải value gốc → vì vậy phone 10 ký tự (term 215) lại nhỏ hơn device_id 7 ký tự (term 245).
- **Chỉ ký query params**: `getURLWithSignHunonic` (Function #7173) parse query từ URL, thêm `app_role`, ký bộ đó. Field trong multipart body KHÔNG được ký (vì vậy `initHomeV2` có token/home ở body chỉ ký `{app_role}` → acc=199).

### Kiểm chứng
- Sinh signature từ params khớp **45/45** request thật bắt qua MITM.
- Gọi live `device/listDeviceOfHomeSelect?token_id=..&home_id=..&app_role=1&signature=..` (POST body rỗng) → trả `status:true` + plaintext `topicsub`/`topicpub`/`key`/`iv`/`root_type` từng thiết bị.

Code production: [`sign.py`](../custom_components/hunonic/sign.py) → `hunonic_sign()`, `signed_query()`. Dùng trong `api.py::get_devices_mobile()`.

### Login mobile — ĐÃ replicate (capture MITM thật)
`POST /v3/user/login`, **multipart/form-data**. Mấu chốt từng làm sai: **TẤT CẢ field nằm trong BODY** (gồm cả `app_role` và `signature`), **query rỗng** — trước đó để `app_role`+`signature` ở query string nên server trả `1026` (1026 ở đây không phải lỗi chữ ký: sig sai/đúng/thiếu đều ra 1026 vì server parse field từ body).

Body (thứ tự app gửi): `password=md5(pw)`, `app_name=hunonic`, `lang=vi`, `is_pro_app=0`, `phone`, `app_role=1`, `signature`. Field ký = 6 field đầu (không gồm `signature`). Response trả `data.token_id` (token mobile mới) + profile.

Đã verify: login bằng SĐT+mật khẩu → token_id → `home/list` (2 nhà) → `listDeviceOfHomeSelect` (plaintext topic/key/iv) → MQTT control. Chạy 100% bằng Python thuần. Code: `api.py::login_mobile()`, `get_homes_mobile()`, `get_devices_mobile()`.

Samples lưu ở `.sig_samples.jsonl` (gitignored).

---

> [!CAUTION]
> **CHỈ DÙNG CHO MỤC ĐÍCH CÁ NHÂN — KHÔNG THƯƠNG MẠI.**
>
> - Repo/tài liệu này được tạo qua reverse-engineering nhằm mục đích nghiên cứu và liên thông cá nhân (interoperability) với thiết bị **bạn sở hữu**.
> - **KHÔNG** dùng cho mục đích thương mại dưới bất kỳ hình thức nào.
> - **Tự kiểm tra kỹ các quy định về sở hữu trí tuệ, điều khoản dịch vụ và pháp luật hiện hành** tại nơi bạn sinh sống **trước khi** sử dụng. Bạn tự chịu hoàn toàn trách nhiệm.
> - **KHÔNG** chia sẻ, phát tán, hay sử dụng để tấn công/chống phá/làm gián đoạn hệ thống Hunonic hoặc bất kỳ hệ thống nào.
> - Tác giả không chịu trách nhiệm cho bất kỳ thiệt hại hay hậu quả pháp lý nào phát sinh từ việc sử dụng repo này.
