"""Detecção e download de mídia gerada pelo MeliGPT (ex.: ``ImageGeneration``).

Confirmado por HAR real (fornecido pelo usuário em 2026-08-09): o MeliGPT
serve arquivos de mídia gerados via
``GET {base_url}/api/media/{userId}/{filename}``, autenticado com os
mesmos headers ``Authorization``/``Cookie`` usados no chat. Essa rota pode
redirecionar para uma URL presignada da S3 (``*.s3.amazonaws.com/...``) —
visto no mesmo HAR — que já carrega sua própria autenticação via query
string, então não reenviamos ``Authorization``/``Cookie`` para esse host
de terceiros ao seguir o redirect.

**Não confirmado por HAR**: o payload exato do evento SSE que acompanha
uma geração de imagem (se o link vem embutido como markdown na resposta
de texto, num campo dedicado do tool_call ``ImageGeneration``, ou nos
dois). Por isso a extração aqui varre apenas o TEXTO final acumulado da
resposta em busca do padrão de rota confirmado — não tenta interpretar um
schema de tool_call não confirmado (ver ``tools/stubs/image_generation.py``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from meligpt.auth.secrets import Credentials
from meligpt.config import GENERATED_MEDIA_DIR_NAME, Settings
from meligpt.exceptions import UpstreamError

#: Confirmado por HAR: `/api/media/<userId hex>/<filename>`.
MEDIA_PATH_RE = re.compile(r"/api/media/[A-Za-z0-9]+/[A-Za-z0-9_\-.]+")

#: Nome da subpasta onde mídia baixada é salva (dentro de
#: `Settings.resolved_media_dir()` — ver docstring lá para o motivo dela
#: ser independente de `files_dir`).
GENERATED_MEDIA_DIR = GENERATED_MEDIA_DIR_NAME


@dataclass(frozen=True)
class MediaReference:
    path: str
    """Caminho relativo confirmado, ex.: ``/api/media/<id>/image_x.png``."""

    filename: str
    """Só o nome do arquivo, ex.: ``image_x.png`` — usado para salvar localmente."""


def extract_media_references(text: str, *, base_url: str) -> list[MediaReference]:
    """Extrai referências únicas a ``/api/media/...`` em ``text``.

    Casa tanto o caminho relativo quanto a URL absoluta com o mesmo
    ``base_url`` (ex.: markdown ``![](https://.../api/media/...)``).
    Preserva a ordem de primeira ocorrência; sem duplicatas.
    """

    if not text:
        return []

    absolute_prefix = base_url.rstrip("/")
    absolute_re = re.compile(
        re.escape(absolute_prefix) + r"(/api/media/[A-Za-z0-9]+/[A-Za-z0-9_\-.]+)"
    )

    ordered_paths: list[str] = []

    def _add(path: str) -> None:
        if path not in ordered_paths:
            ordered_paths.append(path)

    # Varre o texto uma vez, alternando entre as duas formas na ordem em
    # que aparecem — mais simples: junta todas as ocorrências de cada
    # regex e depois ordena pela posição de início no texto original.
    matches: list[tuple[int, str]] = []
    for m in MEDIA_PATH_RE.finditer(text):
        matches.append((m.start(), m.group(0)))
    for m in absolute_re.finditer(text):
        matches.append((m.start(), m.group(1)))
    matches.sort(key=lambda item: item[0])

    for _, path in matches:
        _add(path)

    return [MediaReference(path=p, filename=p.rsplit("/", 1)[-1]) for p in ordered_paths]


def _build_media_headers(settings: Settings, credentials: Credentials) -> dict[str, str]:
    return {
        "Authorization": credentials.authorization_header(),
        "Cookie": credentials.cookie_header,
        "Accept": "image/avif,image/webp,image/png,image/svg+xml,image/*;q=0.8,*/*;q=0.5",
        "Accept-Language": settings.accept_language,
        "User-Agent": settings.user_agent,
    }


async def download_media(
    settings: Settings,
    credentials: Credentials,
    path: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bytes:
    """Baixa um arquivo de mídia autenticado em ``{base_url}{path}``.

    Segue manualmente um único redirect (comportamento confirmado por
    HAR: a rota de mídia pode redirecionar para uma URL presignada da
    S3) sem repassar ``Authorization``/``Cookie`` ao host de destino do
    redirect, já que a autenticação da S3 vem embutida na própria URL
    presignada.
    """

    url = f"{settings.base_url}{path}"
    headers = _build_media_headers(settings, credentials)
    try:
        async with httpx.AsyncClient(transport=transport, timeout=30.0) as client:
            response = await client.get(url, headers=headers, follow_redirects=False)
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location:
                    raise UpstreamError(f"redirect sem Location ao baixar mídia {path!r}")
                response = await client.get(location)
            response.raise_for_status()
            return response.content
    except httpx.HTTPError as exc:
        raise UpstreamError(f"falha ao baixar mídia {path!r}: {exc}") from exc
