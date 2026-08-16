from __future__ import annotations

import struct
import zlib

from meligpt.media_upload import sniff_content_type, sniff_dimensions


def _make_png(width: int, height: int) -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + iend


def _make_gif(width: int, height: int) -> bytes:
    header = b"GIF89a" + struct.pack("<HH", width, height)
    return header + b"\x00" * 10


def _make_jpeg(width: int, height: int) -> bytes:
    # SOI + minimal APP0 + SOF0 carregando width/height + resto irrelevante.
    soi = b"\xff\xd8"
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
    sof0_payload = struct.pack(">BHHB", 8, height, width, 0)
    sof0 = b"\xff\xc0" + struct.pack(">H", len(sof0_payload) + 2) + sof0_payload
    return soi + app0 + sof0


def _make_webp_vp8x(width: int, height: int) -> bytes:
    w_minus_1 = width - 1
    h_minus_1 = height - 1
    vp8x_payload = (
        b"\x00"
        + b"\x00\x00\x00"
        + bytes([w_minus_1 & 0xFF, (w_minus_1 >> 8) & 0xFF, (w_minus_1 >> 16) & 0xFF])
        + bytes([h_minus_1 & 0xFF, (h_minus_1 >> 8) & 0xFF, (h_minus_1 >> 16) & 0xFF])
    )
    vp8x_chunk = b"VP8X" + struct.pack("<I", len(vp8x_payload)) + vp8x_payload
    riff_payload = b"WEBP" + vp8x_chunk
    return b"RIFF" + struct.pack("<I", len(riff_payload)) + riff_payload


def test_sniff_png_dimensions() -> None:
    data = _make_png(123, 456)
    assert sniff_dimensions(data) == (123, 456)
    assert sniff_content_type(data) == "image/png"


def test_sniff_gif_dimensions() -> None:
    data = _make_gif(64, 32)
    assert sniff_dimensions(data) == (64, 32)
    assert sniff_content_type(data) == "image/gif"


def test_sniff_jpeg_dimensions() -> None:
    data = _make_jpeg(800, 600)
    assert sniff_dimensions(data) == (800, 600)
    assert sniff_content_type(data) == "image/jpeg"


def test_sniff_webp_dimensions() -> None:
    data = _make_webp_vp8x(1024, 768)
    assert sniff_dimensions(data) == (1024, 768)
    assert sniff_content_type(data) == "image/webp"


def test_sniff_unknown_format_returns_none() -> None:
    assert sniff_dimensions(b"not an image, just text padded to be long enough") is None
    assert sniff_content_type(b"not an image") == "application/octet-stream"


def test_sniff_too_short_returns_none() -> None:
    assert sniff_dimensions(b"\x89PNG\r\n") is None
