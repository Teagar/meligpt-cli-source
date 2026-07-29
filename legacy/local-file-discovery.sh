#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/meligpt-cli"
FILES_DIR="${MELIGPT_FILES_DIR:-$CONFIG_DIR/files}"
MAX_RESULTS="${MELIGPT_MAX_DISCOVERY_RESULTS:-20}"

die() {
    printf 'Erro: %s\n' "$*" >&2
    exit 1
}

command -v find >/dev/null 2>&1 ||
    die 'find não está instalado'

command -v realpath >/dev/null 2>&1 ||
    die 'realpath não está instalado'

[[ "$MAX_RESULTS" =~ ^[1-9][0-9]*$ ]] ||
    die 'MELIGPT_MAX_DISCOVERY_RESULTS deve ser um inteiro positivo'

mkdir -p -- "$FILES_DIR"
chmod 700 -- "$FILES_DIR"

FILES_DIR="$(realpath -e -- "$FILES_DIR")"

normalize_hint() {
    local value="$1"

    value="${value#\`}"
    value="${value%\`}"
    value="${value#\"}"
    value="${value%\"}"
    value="${value#\'}"
    value="${value%\'}"

    # Converte referências à raiz virtual em caminhos relativos.
    case "$value" in
        /files/*)
            value="${value#/files/}"
            ;;
        /files)
            value=""
            ;;
        ./*)
            value="${value#./}"
            ;;
        /*)
            value="${value#/}"
            ;;
    esac

    # --name e --directory recebem componentes, não caminhos.
    value="${value%/}"

    printf '%s\n' "$value"
}

is_safe_component() {
    local value="$1"

    [[ -n "$value" ]] || return 1
    [[ "$value" != "." ]] || return 1
    [[ "$value" != ".." ]] || return 1
    [[ "$value" != *"/"* ]] || return 1
    [[ "$value" != *$'\n'* ]] || return 1
    [[ "$value" != *$'\r'* ]] || return 1
}

emit_candidate() {
    local candidate="$1"
    local resolved
    local relative

    [[ ! -L "$candidate" ]] || return 1

    resolved="$(realpath -e -- "$candidate")" ||
        return 1

    case "$resolved" in
        "$FILES_DIR"/*)
            ;;
        *)
            return 1
            ;;
    esac

    relative="${resolved#"$FILES_DIR"}"
    printf '%s\0' "$relative"
}

MODE="file"
FILE_NAME=""
DIRECTORY_HINT=""
DIRECTORY_NAME=""

while (($# > 0)); do
    case "$1" in
        --name)
            (($# >= 2)) || die '--name exige um valor'
            FILE_NAME="$(normalize_hint "$2")"
            shift 2
            ;;

        --directory)
            (($# >= 2)) || die '--directory exige um valor'
            DIRECTORY_HINT="$(normalize_hint "$2")"
            shift 2
            ;;

        --directory-name|--find-directory)
            (($# >= 2)) || die "$1 exige um valor"
            MODE="directory"
            DIRECTORY_NAME="$(normalize_hint "$2")"
            shift 2
            ;;

        *)
            die "opção desconhecida: $1"
            ;;
    esac
done

find_by_name() {
    local type="$1"
    local name="$2"

    # Correspondência exata tem prioridade.
    find -P "$FILES_DIR" \
        -type "$type" \
        -name "$name" \
        -print0

    # Só o chamador pode decidir se precisa do fallback.
}

count=0

if [[ "$MODE" == "directory" ]]; then
    is_safe_component "$DIRECTORY_NAME" ||
        die 'nome de diretório inválido'

    results_file="$(mktemp)"
    trap 'rm -f -- "${results_file:-}"' EXIT

    find -P "$FILES_DIR" \
        -type d \
        -name "$DIRECTORY_NAME" \
        -print0 >"$results_file"

    if [[ ! -s "$results_file" ]]; then
        find -P "$FILES_DIR" \
            -type d \
            -iname "$DIRECTORY_NAME" \
            -print0 >"$results_file"
    fi

    while IFS= read -r -d '' candidate; do
        if emit_candidate "$candidate"; then
            count=$((count + 1))
            ((count < MAX_RESULTS)) || break
        fi
    done <"$results_file"

    exit 0
fi

is_safe_component "$FILE_NAME" ||
    die 'nome de arquivo inválido'

if [[ -n "$DIRECTORY_HINT" ]]; then
    is_safe_component "$DIRECTORY_HINT" ||
        die 'nome de diretório inválido'
fi

results_file="$(mktemp)"
trap 'rm -f -- "${results_file:-}"' EXIT

find -P "$FILES_DIR" \
    -type f \
    -name "$FILE_NAME" \
    -print0 >"$results_file"

if [[ ! -s "$results_file" ]]; then
    find -P "$FILES_DIR" \
        -type f \
        -iname "$FILE_NAME" \
        -print0 >"$results_file"
fi

while IFS= read -r -d '' candidate; do
    [[ ! -L "$candidate" ]] || continue

    resolved="$(realpath -e -- "$candidate")" || continue

    case "$resolved" in
        "$FILES_DIR"/*)
            ;;
        *)
            continue
            ;;
    esac

    relative="${resolved#"$FILES_DIR"}"

    if [[ -n "$DIRECTORY_HINT" ]]; then
        directory_matches=false

        case "$relative" in
            */"$DIRECTORY_HINT"/"$FILE_NAME")
                directory_matches=true
                ;;
        esac

        if [[ "$directory_matches" != true ]]; then
            relative_folded="$(
                printf '%s' "$relative" |
                    LC_ALL=C tr '[:upper:]' '[:lower:]'
            )"
            directory_folded="$(
                printf '%s' "$DIRECTORY_HINT" |
                    LC_ALL=C tr '[:upper:]' '[:lower:]'
            )"
            file_folded="$(
                printf '%s' "$FILE_NAME" |
                    LC_ALL=C tr '[:upper:]' '[:lower:]'
            )"

            case "$relative_folded" in
                */"$directory_folded"/"$file_folded")
                    directory_matches=true
                    ;;
            esac
        fi

        [[ "$directory_matches" == true ]] || continue
    fi

    printf '%s\0' "$relative"

    count=$((count + 1))
    ((count < MAX_RESULTS)) || break
done <"$results_file"
