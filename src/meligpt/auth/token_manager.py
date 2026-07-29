"""Recuperação de 401 (token/sessão expirados).

Equivalente ao bloco ``HTTP_STATUS == 401`` de ``legacy/chat-api.sh``:

- Se já houve uma tentativa de recuperação nesta execução, não tenta de
  novo (evita loop infinito) e propaga o erro final.
- Em modo não interativo (sem terminal / sem callback), apenas informa
  como importar o HAR manualmente.
- Em modo interativo, pergunta se o usuário quer importar um HAR novo e,
  se sim, tenta novamente exatamente uma vez.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from meligpt.auth.har_importer import import_har
from meligpt.auth.secrets import Credentials, load_credentials
from meligpt.config import Settings
from meligpt.exceptions import RecoveryFailedError, UpstreamHTTPError

#: Callback que pergunta ao usuário se deseja importar um HAR e, em caso
#: afirmativo, retorna o caminho do arquivo; retorna ``None`` para recusar.
HarPromptCallback = Callable[[], Awaitable[Path | None]]


class TokenManager:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._already_retried = False

    def load_credentials(self) -> Credentials:
        return load_credentials(self._settings.resolved_secrets_path())

    async def recover_from_401(
        self,
        error: UpstreamHTTPError,
        *,
        interactive: bool,
        prompt_for_har: HarPromptCallback | None,
    ) -> Credentials:
        """Tenta recuperar de um 401. Levanta :class:`RecoveryFailedError`
        se a recuperação não for possível ou já tiver sido tentada.
        """

        if self._already_retried:
            raise RecoveryFailedError(
                "as credenciais atualizadas também foram recusadas."
            ) from error

        if not interactive or prompt_for_har is None:
            raise RecoveryFailedError(
                "a recuperação automática exige um terminal interativo. "
                "Importe manualmente o HAR e tente novamente."
            ) from error

        har_path = await prompt_for_har()
        if har_path is None:
            raise RecoveryFailedError("credenciais não foram alteradas.") from error

        import_har(
            har_path,
            self._settings.resolved_secrets_path(),
            expected_endpoint=self._settings.resolved_endpoint(),
        )
        self._already_retried = True
        return self.load_credentials()
