"""Configuração tipada e centralizada.

Espelha as variáveis de ambiente `MELIGPT_*` reconhecidas pelos scripts Bash
originais (ver ``legacy/chat-api.sh``, ``legacy/local-tools.sh`` e
``legacy/local-file-discovery.sh``), mantendo os mesmos nomes e defaults.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração da aplicação, lida de variáveis de ambiente / .env."""

    model_config = SettingsConfigDict(
        env_prefix="MELIGPT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Diretórios -----------------------------------------------------
    config_dir: Path = Field(default_factory=lambda: Path.home() / ".config" / "meligpt-cli")
    files_dir: Path | None = None
    """Raiz sandbox para as ferramentas de arquivo. Default: config_dir/files."""

    secrets_path: Path | None = None
    """Caminho do secrets.env. Default: config_dir/secrets.env."""

    # --- Limites (mesmos nomes e defaults do Bash) -----------------------
    max_file_size: int = 1_048_576
    max_ls_results: int = 1000
    max_discovery_results: int = 20
    max_context_size: int = 4_194_304
    max_context_files: int = 200
    max_grep_results: int = 500
    max_grep_bytes_per_file: int = 1_048_576
    max_glob_results: int = 1000
    parallel_max_concurrency: int = 4
    parallel_max_recursion_depth: int = 1
    task_max_depth: int = 2
    task_default_timeout_seconds: float = 120.0

    # --- API upstream (MeliGPT) ------------------------------------------
    base_url: str = "https://public-meligpt.adminml.com"
    endpoint: str | None = None
    """Default: base_url + /api/ask/openAI."""

    model: str = "gpt-5.6-sol"
    user_agent: str = "Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0"
    accept_language: str = "en-US,en;q=0.9"
    referer: str | None = None
    """Default: base_url + /c/new."""

    connect_timeout_seconds: float = 20.0
    read_timeout_seconds: float = 600.0
    write_timeout_seconds: float = 20.0
    pool_timeout_seconds: float = 20.0

    enable_browsing: bool = False
    """Liga o campo nativo "browsing" do payload do MeliGPT (visto no HAR
    como parte do payload padrão, sempre `false` no client original). Se
    o backend do MeliGPT suportar esse plugin (aparenta ser LibreChat),
    isso dá busca na web feita pelo próprio modelo remoto, sem precisar
    de nenhum provedor local. Não verificado ao vivo — teste com cuidado.
    """

    # --- Busca web local (fallback, usada quando o modelo chama a
    # ferramenta local `WebSearch` explicitamente) --------------------------
    web_search_provider: str = "brave"
    brave_api_key: str | None = None
    web_search_max_results: int = 5

    # --- Refresh automático de token (POST /api/auth/refresh) -------------
    refresh_endpoint: str | None = None
    """Default: base_url + /api/auth/refresh."""

    auto_refresh_enabled: bool = True
    """Liga/desliga o loop de refresh em background no `meligpt serve`."""

    token_refresh_margin_seconds: float = 120.0
    """Renova o token esse tanto de segundos ANTES do exp do JWT."""

    token_refresh_interval_seconds: float = 600.0
    """Usado apenas como fallback quando o JWT não pôde ser decodificado."""

    token_refresh_retry_seconds: float = 30.0
    """Intervalo entre tentativas após uma falha de refresh."""

    # --- Servidor HTTP/SSE opcional ---------------------------------------
    server_host: str = "0.0.0.0"
    server_port: int = 8080
    log_level: str = "INFO"

    def resolved_files_dir(self) -> Path:
        return self.files_dir or (self.config_dir / "files")

    def resolved_secrets_path(self) -> Path:
        return self.secrets_path or (self.config_dir / "secrets.env")

    def resolved_endpoint(self) -> str:
        return self.endpoint or f"{self.base_url}/api/ask/openAI"

    def resolved_referer(self) -> str:
        return self.referer or f"{self.base_url}/c/new"

    def resolved_refresh_endpoint(self) -> str:
        return self.refresh_endpoint or f"{self.base_url}/api/auth/refresh"


def get_settings() -> Settings:
    """Ponto único de construção de :class:`Settings` (facilita mocks em teste)."""

    return Settings()
