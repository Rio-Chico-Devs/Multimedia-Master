"""
Generates assets/icon.ico — a placeholder app icon (rounded square in the
app's existing blue/dark palette, white play-mark) built with pure-Python
pixel math, no Pillow/network required. Swap this file out for a real
logo whenever one is designed; nothing else needs to change as long as
the replacement is also named icon.ico with the same sizes.

Run:  python3 assets/generate_icon.py
"""
import math
import struct
from pathlib import Path

OUT = Path(__file__).parent / "icon.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)

_TOP    = (0x14, 0x28, 0x3c)   # dark navy — matches the launcher's dark bg
_BOTTOM = (0x1f, 0x6a, 0xa5)   # CTk default blue accent, used throughout the app
_MARK   = (255, 255, 255)

_SS = 4  # supersample factor per axis (16 samples/pixel) for anti-aliasing


def _point_in_triangle(px, py, p1, p2, p3) -> bool:
    def sign(ax, ay, bx, by, cx, cy):
        return (ax - cx) * (by - cy) - (bx - cx) * (ay - cy)
    d1 = sign(px, py, *p1, *p2)
    d2 = sign(px, py, *p2, *p3)
    d3 = sign(px, py, *p3, *p1)
    has_neg = d1 < 0 or d2 < 0 or d3 < 0
    has_pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (has_neg and has_pos)


def _render(size: int) -> bytes:
    """Return BGRA bytes, top-to-bottom rows, for a `size`x`size` icon."""
    cx = cy = size / 2
    half = size / 2 - size * 0.04
    radius = half * 0.30

    tri = half * 0.78
    p1 = (cx - tri * 0.42, cy - tri * 0.62)
    p2 = (cx - tri * 0.42, cy + tri * 0.62)
    p3 = (cx + tri * 0.66, cy)

    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            r_sum = g_sum = b_sum = a_sum = 0.0
            for sy in range(_SS):
                py = y + (sy + 0.5) / _SS
                dy = abs(py - cy) - (half - radius)
                dy = max(dy, 0.0)
                for sx in range(_SS):
                    px = x + (sx + 0.5) / _SS
                    dx = abs(px - cx) - (half - radius)
                    dx = max(dx, 0.0)
                    in_bg = math.hypot(dx, dy) <= radius
                    if not in_bg:
                        continue
                    if _point_in_triangle(px, py, p1, p2, p3):
                        r, g, b = _MARK
                    else:
                        t = max(0.0, min(1.0, py / size))
                        r = _TOP[0] + (_BOTTOM[0] - _TOP[0]) * t
                        g = _TOP[1] + (_BOTTOM[1] - _TOP[1]) * t
                        b = _TOP[2] + (_BOTTOM[2] - _TOP[2]) * t
                    r_sum += r
                    g_sum += g
                    b_sum += b
                    a_sum += 255.0
            n = _SS * _SS
            a = a_sum / n
            if a > 0:
                r_avg = r_sum / (a_sum / 255.0)
                g_avg = g_sum / (a_sum / 255.0)
                b_avg = b_sum / (a_sum / 255.0)
            else:
                r_avg = g_avg = b_avg = 0.0
            row.append((int(b_avg), int(g_avg), int(r_avg), int(a)))
        rows.append(row)

    # BMP DIB rows are stored bottom-up.
    out = bytearray()
    for row in reversed(rows):
        for b, g, r, a in row:
            out += bytes((b, g, r, a))
    return bytes(out)


def _bmp_dib(size: int, pixels: bytes) -> bytes:
    header = struct.pack(
        "<IiiHHIIiiII",
        40,        # biSize
        size,      # biWidth
        size,      # biHeight (positive => bottom-up, matches our row order)
        1,         # biPlanes
        32,        # biBitCount
        0,         # biCompression (BI_RGB)
        len(pixels),
        0, 0,      # biXPelsPerMeter, biYPelsPerMeter
        0,         # biClrUsed
        0,         # biClrImportant
    )
    return header + pixels


def main() -> None:
    images = [(s, _bmp_dib(s, _render(s))) for s in SIZES]

    out = bytearray()
    out += struct.pack("<HHH", 0, 1, len(images))  # ICONDIR

    offset = 6 + 16 * len(images)
    entries = bytearray()
    data = bytearray()
    for size, dib in images:
        entries += struct.pack(
            "<BBBBHHII",
            size if size < 256 else 0,
            size if size < 256 else 0,
            0, 0,       # color count, reserved
            1, 32,      # planes, bit count
            len(dib),
            offset,
        )
        data += dib
        offset += len(dib)

    OUT.write_bytes(bytes(out) + bytes(entries) + bytes(data))
    print(f"Wrote {OUT} ({OUT.stat().st_size} bytes, sizes={SIZES})")


if __name__ == "__main__":
    main()
