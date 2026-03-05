"""
Tạo VAPID keys cho push notifications.
Chạy: python generate_vapid.py
Sau đó thêm 2 giá trị vào Railway Variables.
"""

try:
    from py_vapid import Vapid
except ImportError:
    print("Cài pywebpush trước: pip install pywebpush")
    raise SystemExit(1)

vapid = Vapid()
vapid.generate_keys()

public_key  = vapid.public_key_urlsafe
private_key = vapid.private_key_urlsafe

print("\n=== VAPID KEYS ===")
print(f"\nVAPID_PUBLIC_KEY={public_key}")
print(f"\nVAPID_PRIVATE_KEY={private_key}")
print("\n=== Thêm 2 biến trên vào Railway Variables ===\n")
