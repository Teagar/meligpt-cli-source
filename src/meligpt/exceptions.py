"""Exceções estruturadas e serializáveis do MeliGPT CLI.

Todas herdam de :class:`MeliGPTError` para permitir captura genérica em um
único ponto (camada de CLI / API), preservando o tipo específico para quem
precisar tratar cada caso separadamente.
"""

from __future__ import annotations


class MeliGPTError(Exception):
    """Erro base de domínio do MeliGPT CLI."""

    #: Código estável, usado em respostas JSON/SSE. Subclasses devem
    #: sobrescrever.
    code: str = "internal_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, object]:
        return {"success": False, "error": self.message, "code": self.code}


# --- Segurança de filesystem -----------------------------------------------


class FilesystemSecurityError(MeliGPTError):
    """Classe base para violações de segurança de caminho."""

    code = "filesystem_security_error"


class InvalidPathError(FilesystemSecurityError):
    """O caminho virtual é malformado (vazio, contém NUL/CR/LF etc.)."""

    code = "invalid_path"


class PathTraversalError(FilesystemSecurityError):
    """O caminho tenta escapar da raiz autorizada via ``..`` ou similar."""

    code = "path_traversal"


class SymlinkNotAllowedError(FilesystemSecurityError):
    """Um componente intermediário ou final é (ou passa por) um symlink."""

    code = "symlink_not_allowed"


# --- Erros de operação em arquivo -------------------------------------------


class FileNotFoundToolError(MeliGPTError):
    code = "file_not_found"


class NotADirectoryToolError(MeliGPTError):
    code = "not_a_directory"


class NotAFileToolError(MeliGPTError):
    code = "not_a_file"


class PermissionDeniedToolError(MeliGPTError):
    code = "permission_denied"


class BinaryFileError(MeliGPTError):
    code = "binary_file"


class FileTooLargeError(MeliGPTError):
    code = "file_too_large"


class AmbiguousMatchError(MeliGPTError):
    """Mais de um resultado quando apenas um era esperado (edit, discovery)."""

    code = "ambiguous_match"


class TextNotFoundError(MeliGPTError):
    """``edit_file``: o texto a ser substituído não foi encontrado."""

    code = "text_not_found"


# --- Ferramentas genéricas ---------------------------------------------------


class ToolNotFoundError(MeliGPTError):
    code = "tool_not_found"


class ToolValidationError(MeliGPTError):
    code = "tool_validation_error"


class ToolExecutionError(MeliGPTError):
    code = "tool_execution_error"


class ToolTimeoutError(MeliGPTError):
    code = "tool_timeout"


class ToolNotImplementedError(MeliGPTError):
    """Ferramenta reconhecida pelo catálogo, mas sem provedor real.

    Usada pelas ferramentas "stub" da Fase B (WebSearch, ImageGeneration,
    task, edit_file, glob, grep, write_todos, parallel) que não existiam
    na implementação Bash original.
    """

    code = "tool_not_implemented"


class RecursionLimitError(MeliGPTError):
    """Profundidade máxima de subagentes/paralelismo excedida."""

    code = "recursion_limit"


# --- Autenticação -------------------------------------------------------------


class AuthenticationError(MeliGPTError):
    code = "authentication_error"


class SecretsNotFoundError(AuthenticationError):
    code = "secrets_not_found"


class TokenExpiredError(AuthenticationError):
    code = "token_expired"


class RecoveryFailedError(AuthenticationError):
    code = "recovery_failed"


class TokenRefreshError(AuthenticationError):
    """Falha ao renovar o access token via POST /api/auth/refresh."""

    code = "token_refresh_failed"


class HarImportError(MeliGPTError):
    code = "har_import_error"


# --- Rede / API upstream -------------------------------------------------------


class UpstreamError(MeliGPTError):
    code = "upstream_error"


class UpstreamHTTPError(UpstreamError):
    """A API upstream respondeu com um status HTTP inesperado."""

    code = "upstream_http_error"

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = super().to_dict()
        payload["status_code"] = self.status_code
        return payload


class UpstreamForbiddenError(UpstreamHTTPError):
    code = "upstream_forbidden"


class UpstreamTimeoutError(UpstreamError):
    code = "upstream_timeout"
