"""Chữ ký request API mobile Hunonic — `hunonicEncodeSign`.

Reverse-engineer trực tiếp từ Hermes bytecode (Function #7172 trong
index.android.bundle, app com.iot.hunonic). Đã kiểm chứng end-to-end:
sinh signature từ params khớp 100% với 45/45 request thật bắt được qua MITM,
và gọi live `device/listDeviceOfHomeSelect` trả về plaintext topic/key/iv.

Thuật toán (nguyên văn từ bytecode):

    acc = 0
    for key, value in Object.entries(params):     # params = QUERY của URL + app_role
        if key == "signature": continue
        if not value or Number(value) == 0:        # value falsy hoặc bằng 0
            acc += key.charCodeAt(0) + 58           # env[7] = 58
        else:
            b = base64(String(value))               # CryptoJS enc.Base64 (hàm encode111)
            acc += b.charCodeAt(0)
                 + b.charCodeAt(floor(len(b)/2))
                 + b.charCodeAt(len(b) - 1)
    signature = md5("sha256fake" + "accessKey=" + SLOT6 + md5(str(acc)) + SLOT5)

Mấu chốt từng làm sai khi đoán bằng linear-fit: charCodeAt chạy trên **chuỗi
base64 của value**, không phải value gốc — nên độ dài/ký tự không tỉ lệ tuyến tính.

CHỈ ký các tham số nằm trong QUERY STRING của URL (cộng `app_role`); field gửi
trong multipart body KHÔNG được ký (xác nhận qua initHomeV2: token/home ở body →
chỉ ký {app_role} → acc=199).
"""

from __future__ import annotations

import base64
import hashlib

# Hằng số nhúng trong bytecode (env slots).
_SLOT5 = "HUNONICBIGBUG94d3c445e72ae7805fca3489edac9608c893e66b"   # env[5]
_SLOT6 = "accessKey98ccdcbbe7b5528bec0ca31bbe8d93b4e76590dd"        # env[6]
_ENV7 = 58                                                          # env[7]


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _is_zero(value: str) -> bool:
    """True nếu value rỗng hoặc bằng 0 (giống nhánh falsy/equalVal(v,0) trong JS)."""
    if value == "":
        return True
    try:
        return float(value) == 0
    except ValueError:
        return False


def _accumulate(params: dict[str, object]) -> int:
    acc = 0
    for key, raw in params.items():
        if key == "signature":
            continue
        value = "" if raw is None else str(raw)
        if _is_zero(value):
            k = str(key)
            acc += (ord(k[0]) if k else ord("a")) + _ENV7
        else:
            b = _b64(value)
            n = len(b)
            acc += ord(b[0]) + ord(b[n // 2]) + ord(b[n - 1])
    return acc


def hunonic_sign(params: dict[str, object]) -> str:
    """Tính `signature` cho bộ tham số *params* (các key trong query + app_role)."""
    acc = _accumulate(params)
    return _md5("sha256fake" + "accessKey=" + _SLOT6 + _md5(str(acc)) + _SLOT5)


def signed_query(params: dict[str, object]) -> dict[str, str]:
    """Trả về dict query gồm *params* + `signature` đã tính (giữ nguyên thứ tự)."""
    out = {str(k): str(v) for k, v in params.items() if k != "signature"}
    out["signature"] = hunonic_sign(out)
    return out
