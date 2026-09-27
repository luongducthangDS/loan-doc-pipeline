"""CI: repo chỉ được chứa ảnh/PDF synthetic trong data/synthetic/ (spec mục 10).

Chặn trường hợp ai đó lỡ commit ảnh CCCD/sao kê thật ở chỗ khác.
"""

import subprocess
import sys

EXT = (".jpg", ".jpeg", ".png", ".pdf", ".tif", ".tiff", ".bmp", ".webp", ".heic")
ALLOWED = ("data/synthetic/",)

files = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout.splitlines()
bad = [f for f in files if f.lower().endswith(EXT) and not f.startswith(ALLOWED)]
if bad:
    print("File ảnh/PDF ngoài data/synthetic/ (có thể là dữ liệu thật):", *bad, sep="\n  ")
    sys.exit(1)
print(f"OK: {len(files)} file, không có ảnh/PDF ngoài {ALLOWED[0]}")
