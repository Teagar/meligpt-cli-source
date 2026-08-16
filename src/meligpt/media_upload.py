"""Detecção de largura/altura de uma imagem a partir dos bytes crus —
suficiente pro upload de anexos (``POST /api/files/images``, ver
:mod:`meligpt.clients.meligpt_http`), sem precisar de Pillow como
dependência.

Confirmado por HAR real (``import.har``, 2026-08-15): o valor de
``width``/``height`` mandado no upload NÃO precisa ser exato — o servidor
recalcula e devolve as dimensões reais na resposta (`width`/`height` do
JSON), que são o que efetivamente vai no payload do chat depois. Por
isso os parsers abaixo são propositalmente simples (só os formatos mais
comuns) — quando não reconhecem o formato, ``sniff_dimensions`` retorna
``None`` e o chamador manda ``0, 0`` como placeholder, sem quebrar nada.
"""

from __future__ import annotations

import struct


def sniff_dimensions(data: bytes) -> tuple[int, int] | None:
    """Retorna ``(largura, altura)`` para PNG/JPEG/GIF/WEBP, ou ``None``
    se o formato não for reconhecido ou os bytes forem curtos demais.
    """

    if len(data) < 10:
        return None

    # PNG: assinatura de 8 bytes, depois chunk IHDR (4 bytes de tamanho +
    # "IHDR" + 4 bytes largura + 4 bytes altura, big-endian).
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        if len(data) < 24:
            return None
        width, height = struct.unpack(">II", data[16:24])
        return width, height

    # GIF: "GIF87a"/"GIF89a" + largura/altura little-endian (2 bytes cada).
    if data[:6] in (b"GIF87a", b"GIF89a"):
        width, height = struct.unpack("<HH", data[6:10])
        return width, height

    # WEBP: container RIFF. VP8X carrega dimensões diretamente; VP8/VP8L
    # (formato simples, sem extensão) têm parsing mais específico —
    # cobrimos só VP8X aqui (caso mais comum vindo de export/edição).
    if len(data) >= 16 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk_type = data[12:16]
        if chunk_type == b"VP8X" and len(data) >= 30:
            width = 1 + (data[24] | (data[25] << 8) | (data[26] << 16))
            height = 1 + (data[27] | (data[28] << 8) | (data[29] << 16))
            return width, height
        return None

    # JPEG: percorre os marcadores até achar um SOF (Start Of Frame).
    if data[:2] == b"\xff\xd8":
        return _sniff_jpeg_dimensions(data)

    return None


def _sniff_jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    offset = 2
    length = len(data)
    # Marcadores SOF0-SOF15, exceto DHT(0xC4)/JPG(0xC8)/DAC(0xCC), que não
    # carregam dimensões apesar de estarem na mesma faixa de bytes.
    sof_markers = {
        b"\xc0",
        b"\xc1",
        b"\xc2",
        b"\xc3",
        b"\xc5",
        b"\xc6",
        b"\xc7",
        b"\xc9",
        b"\xca",
        b"\xcb",
        b"\xcd",
        b"\xce",
        b"\xcf",
    }
    while offset + 4 <= length:
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1 : offset + 2]
        if marker in sof_markers:
            if offset + 9 > length:
                return None
            height, width = struct.unpack(">HH", data[offset + 5 : offset + 9])
            return width, height
        segment_length = struct.unpack(">H", data[offset + 2 : offset + 4])[0]
        offset += 2 + segment_length
    return None


def sniff_content_type(data: bytes, *, fallback: str = "application/octet-stream") -> str:
    """Content-Type provável a partir da assinatura dos bytes — usado
    quando quem chama não informa um (ex.: upload pela CLI a partir de um
    caminho local sem extensão confiável)."""

    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return fallback
