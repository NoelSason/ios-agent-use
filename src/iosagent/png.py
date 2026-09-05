"""Minimal PNG read/write on the standard library alone.

`sips` (shipped with macOS) does the resampling; this module only needs to read
what it produces and write the annotated diff back out. Supported on read:
8-bit greyscale, greyscale+alpha, RGB, RGBA, and palette. Interlaced PNGs are
rejected rather than silently mangled -- nothing in this pipeline produces one.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import zlib
from pathlib import Path

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# color type -> channels in the raw scanline
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


class PNGError(Exception):
    pass


class Image:
    """An 8-bit RGB image held as one flat bytearray, row-major."""

    __slots__ = ("width", "height", "pixels")

    def __init__(self, width: int, height: int, pixels: bytearray):
        if len(pixels) != width * height * 3:
            raise PNGError(f"expected {width * height * 3} bytes, got {len(pixels)}")
        self.width = width
        self.height = height
        self.pixels = pixels

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        i = (y * self.width + x) * 3
        return self.pixels[i], self.pixels[i + 1], self.pixels[i + 2]

    def set_pixel(self, x: int, y: int, rgb: tuple[int, int, int]) -> None:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        i = (y * self.width + x) * 3
        self.pixels[i], self.pixels[i + 1], self.pixels[i + 2] = rgb


def _unfilter(raw: bytes, width: int, height: int, channels: int) -> bytearray:
    """Reverse the per-scanline PNG filters (spec section 9.2)."""
    stride = width * channels
    out = bytearray(stride * height)
    prev = bytearray(stride)
    pos = 0
    for y in range(height):
        ftype = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        if ftype == 0:
            pass
        elif ftype == 1:  # Sub
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif ftype == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:  # Average
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:  # Paeth
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                if pa <= pb and pa <= pc:
                    pr = a
                elif pb <= pc:
                    pr = b
                else:
                    pr = c
                line[i] = (line[i] + pr) & 0xFF
        else:
            raise PNGError(f"unknown filter type {ftype} on row {y}")
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return out


def dimensions(path: str | Path) -> tuple[int, int]:
    """Width and height from the IHDR alone, without decoding the image."""
    with Path(path).open("rb") as handle:
        header = handle.read(24)
    if header[:8] != PNG_MAGIC:
        raise PNGError(f"{path} is not a PNG")
    return struct.unpack(">II", header[16:24])


def read_png(path: str | Path) -> Image:
    data = Path(path).read_bytes()
    if data[:8] != PNG_MAGIC:
        raise PNGError(f"{path} is not a PNG")

    pos = 8
    width = height = depth = ctype = interlace = 0
    idat = bytearray()
    palette = b""
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length  # length + tag + body + crc
        if ctag == b"IHDR":
            width, height, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif ctag == b"PLTE":
            palette = body
        elif ctag == b"IDAT":
            idat += body
        elif ctag == b"IEND":
            break

    if depth != 8:
        raise PNGError(f"only 8-bit PNGs are supported (got {depth}-bit)")
    if interlace:
        raise PNGError("interlaced PNGs are not supported")
    if ctype not in _CHANNELS:
        raise PNGError(f"unsupported color type {ctype}")

    channels = _CHANNELS[ctype]
    raw = _unfilter(zlib.decompress(bytes(idat)), width, height, channels)

    n = width * height
    rgb = bytearray(n * 3)
    if ctype == 2:
        return Image(width, height, raw)
    if ctype == 6:
        for i in range(n):
            rgb[i * 3:i * 3 + 3] = raw[i * 4:i * 4 + 3]
    elif ctype == 0:
        for i in range(n):
            v = raw[i]
            rgb[i * 3] = rgb[i * 3 + 1] = rgb[i * 3 + 2] = v
    elif ctype == 4:
        for i in range(n):
            v = raw[i * 2]
            rgb[i * 3] = rgb[i * 3 + 1] = rgb[i * 3 + 2] = v
    elif ctype == 3:
        if not palette:
            raise PNGError("palette image with no PLTE chunk")
        for i in range(n):
            j = raw[i] * 3
            rgb[i * 3:i * 3 + 3] = palette[j:j + 3]
    return Image(width, height, rgb)


def write_png(path: str | Path, image: Image) -> None:
    stride = image.width * 3
    raw = bytearray()
    for y in range(image.height):
        raw.append(0)  # filter type None; these are small annotated images
        raw += image.pixels[y * stride:(y + 1) * stride]

    def chunk(tag: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", image.width, image.height, 8, 2, 0, 0, 0)
    Path(path).write_bytes(
        PNG_MAGIC
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + chunk(b"IEND", b"")
    )


def downscale(src: str | Path, dst: str | Path, max_dim: int) -> Path:
    """Resample with `sips`, which is present on every macOS install.

    Only ever shrinks: `sips -Z` will happily enlarge an image whose longest
    side is under the limit, which wastes work and moves every coordinate.
    """
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if max(dimensions(src)) <= max_dim:
        if Path(src) != dst:
            shutil.copyfile(src, dst)
        return dst
    subprocess.run(
        ["sips", "-Z", str(max_dim), "-s", "format", "png", str(src), "--out", str(dst)],
        check=True, capture_output=True,
    )
    return dst


def rotate_file(path: str | Path, degrees_clockwise: int) -> None:
    """Rotate in place with `sips`. The pure-Python `rotate` below is correct but
    far too slow for a 5.7-megapixel screenshot."""
    if degrees_clockwise % 360 == 0:
        return
    subprocess.run(["sips", "-r", str(degrees_clockwise % 360), str(path)],
                   check=True, capture_output=True)


def draw_rect(image: Image, x: int, y: int, w: int, h: int,
              rgb: tuple[int, int, int] = (255, 48, 48), thickness: int = 2) -> None:
    for t in range(thickness):
        for px in range(x, x + w):
            image.set_pixel(px, y + t, rgb)
            image.set_pixel(px, y + h - 1 - t, rgb)
        for py in range(y, y + h):
            image.set_pixel(x + t, py, rgb)
            image.set_pixel(x + w - 1 - t, py, rgb)


def side_by_side(a: Image, b: Image, gap: int = 8) -> Image:
    """Compose two images left-to-right on a dark ground for a single glance."""
    height = max(a.height, b.height)
    width = a.width + gap + b.width
    canvas = Image(width, height, bytearray(b"\x18" * (width * height * 3)))
    for src, x0 in ((a, 0), (b, a.width + gap)):
        for y in range(src.height):
            row = src.pixels[y * src.width * 3:(y + 1) * src.width * 3]
            start = (y * width + x0) * 3
            canvas.pixels[start:start + len(row)] = row
    return canvas


def rotate(image: Image, clockwise: bool) -> Image:
    """Quarter turn. Screen captures come out of the device in its native
    portrait framebuffer regardless of interface rotation, so a landscape UI
    arrives sideways and has to be turned back before its pixels line up with
    the accessibility frames."""
    w, h = image.width, image.height
    out = bytearray(w * h * 3)
    src = image.pixels
    for y in range(h):
        row = y * w * 3
        for x in range(w):
            si = row + x * 3
            if clockwise:
                dx, dy = h - 1 - y, x
            else:
                dx, dy = y, w - 1 - x
            di = (dy * h + dx) * 3
            out[di:di + 3] = src[si:si + 3]
    return Image(h, w, out)
