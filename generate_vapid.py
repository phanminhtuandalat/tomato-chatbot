"""
Tạo VAPID keys cho push notifications.
Chạy: python generate_vapid.py
Sau đó thêm 2 giá trị vào Railway Variables.
"""

try:
    from py_vapid import Vapid02
    from cryptography.hazmat.primitives import serialization
    import base64
except ImportError:
    print("Cài pywebpush trước: pip install pywebpush")
    raise SystemExit(1)

v = Vapid02()
v.generate_keys()

pub_bytes = v.public_key.public_bytes(
    serialization.Encoding.X962,
    serialization.PublicFormat.UncompressedPoint,
)
public_key = base64.urlsafe_b64encode(pub_bytes).rstrip(b"=").decode()
private_key = base64.b64encode(v.private_pem()).rstrip(b"=").decode()

print("\n=== VAPID KEYS — copy 2 dòng dưới vào Railway Variables ===\n")
print(f"VAPID_PUBLIC_KEY={public_key}")
print(f"VAPID_PRIVATE_KEY={private_key}")
print("\n" + "="*55 + "\n")
