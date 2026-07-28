#!/usr/bin/env bash
set -Eeuo pipefail

die() {
    printf 'Erro: %s\n' "$*" >&2
    exit 1
}

command -v jq >/dev/null 2>&1 || die 'jq não está instalado.'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
SECRETS="${MELIGPT_SECRETS:-$SCRIPT_DIR/secrets.env}"
EXPECTED_URL='https://public-meligpt.adminml.com/api/ask/openAI'
HAR_FILE="${1:-}"

if [[ -z "$HAR_FILE" ]]; then
    [[ -t 0 ]] || die 'informe o caminho do HAR como argumento.'
    printf 'Caminho do arquivo HAR: ' >&2
    IFS= read -r HAR_FILE
fi

if [[ "$HAR_FILE" == \"*\" && "$HAR_FILE" == *\" ]]; then
    HAR_FILE="${HAR_FILE:1:${#HAR_FILE}-2}"
elif [[ "$HAR_FILE" == \'*\' && "$HAR_FILE" == *\' ]]; then
    HAR_FILE="${HAR_FILE:1:${#HAR_FILE}-2}"
fi

[[ -f "$HAR_FILE" ]] || die "arquivo HAR não encontrado: $HAR_FILE"
[[ -r "$HAR_FILE" ]] || die "arquivo HAR não pode ser lido: $HAR_FILE"

jq -e '.log.entries | type == "array"' "$HAR_FILE" >/dev/null 2>&1 ||
    die 'o arquivo informado não parece ser um HAR válido.'

ENTRY="$(
    jq -cer --arg url "$EXPECTED_URL" '
        [
            .log.entries[]
            | select(.request.method == "POST")
            | select((.request.url | split("?")[0]) == $url)
            | select(.response.status == 200)
            | .request.headers as $headers
            | {
                authorization: ([
                    $headers[]
                    | select((.name | ascii_downcase) == "authorization")
                    | .value
                ] | last),
                cookie: ([
                    $headers[]
                    | select((.name | ascii_downcase) == "cookie")
                    | .value
                ] | last)
            }
            | select(
                (.authorization | type == "string") and
                (.authorization | length > 0) and
                (.cookie | type == "string") and
                (.cookie | length > 0)
            )
        ]
        | last
        | select(. != null)
    ' "$HAR_FILE" 2>/dev/null
)" || die 'não encontrei uma requisição válida com Authorization e Cookie.'

ACCESS_TOKEN="$(jq -er '.authorization' <<<"$ENTRY")" ||
    die 'não foi possível extrair Authorization do HAR.'
COOKIE_HEADER="$(jq -er '.cookie' <<<"$ENTRY")" ||
    die 'não foi possível extrair Cookie do HAR.'

SECRETS_DIR="$(dirname -- "$SECRETS")"
umask 077
mkdir -p -- "$SECRETS_DIR" || die "não foi possível criar: $SECRETS_DIR"
chmod 700 "$SECRETS_DIR" 2>/dev/null || true

TEMP_FILE="$(mktemp "$SECRETS_DIR/.secrets.env.XXXXXX")" ||
    die 'não foi possível criar o arquivo temporário.'

cleanup() {
    [[ -z "${TEMP_FILE:-}" ]] || rm -f -- "$TEMP_FILE"
    unset ENTRY ACCESS_TOKEN COOKIE_HEADER
}
trap cleanup EXIT HUP INT TERM

{
    printf 'ACCESS_TOKEN=%q\n' "$ACCESS_TOKEN"
    printf 'COOKIE_HEADER=%q\n' "$COOKIE_HEADER"
} >"$TEMP_FILE" || die 'não foi possível escrever as credenciais.'

chmod 600 "$TEMP_FILE" || die 'não foi possível proteger as credenciais.'
mv -f -- "$TEMP_FILE" "$SECRETS" || die "não foi possível atualizar: $SECRETS"
TEMP_FILE=''
chmod 600 "$SECRETS" || die 'não foi possível aplicar permissão 600.'

printf 'Credenciais importadas com segurança em: %s\n' "$SECRETS"
printf '%s\n' 'O HAR contém segredos; apague-o quando não for mais necessário.'
