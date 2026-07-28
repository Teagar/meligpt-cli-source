#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/meligpt-cli"
FILES_DIR="${MELIGPT_FILES_DIR:-$CONFIG_DIR/files}"
MAX_FILE_SIZE="${MELIGPT_MAX_FILE_SIZE:-1048576}"
MAX_LS_RESULTS="${MELIGPT_MAX_LS_RESULTS:-1000}"

die_json() {
    jq -cn --arg error "$1" '{success:false,error:$error}'
    exit 1
}

success_content_json() {
    jq -cn --arg content "$1" '{success:true,content:$content}'
}

is_positive_integer() {
    [[ "${1-}" =~ ^[1-9][0-9]*$ ]]
}

command -v jq >/dev/null 2>&1 ||
    die_json 'jq não está instalado'

command -v realpath >/dev/null 2>&1 ||
    die_json 'realpath não está instalado'

command -v find >/dev/null 2>&1 ||
    die_json 'find não está instalado'

is_positive_integer "$MAX_FILE_SIZE" ||
    die_json 'MELIGPT_MAX_FILE_SIZE deve ser um inteiro positivo'

is_positive_integer "$MAX_LS_RESULTS" ||
    die_json 'MELIGPT_MAX_LS_RESULTS deve ser um inteiro positivo'

mkdir -p -- "$FILES_DIR"
chmod 700 -- "$FILES_DIR"

FILES_DIR="$(realpath -e -- "$FILES_DIR")"

resolve_path() {
    local virtual="${1-}"
    local relative
    local candidate
    local current
    local component
    local -a components=()

    [[ -n "$virtual" ]] || return 1
    [[ "$virtual" != *$'\0'* ]] || return 1
    [[ "$virtual" != *$'\n'* ]] || return 1
    [[ "$virtual" != *$'\r'* ]] || return 1

    case "$virtual" in
        /|/files)
            relative=""
            ;;

        /files/*)
            relative="${virtual#/files/}"
            ;;

        /*)
            # "/" é a raiz virtual, não a raiz real do sistema.
            relative="${virtual#/}"
            ;;

        *)
            relative="$virtual"
            ;;
    esac

    if [[ -z "$relative" ]]; then
        printf '%s\n' "$FILES_DIR"
        return 0
    fi

    candidate="$(realpath -m -- "$FILES_DIR/$relative")" ||
        return 1

    case "$candidate" in
        "$FILES_DIR"|"$FILES_DIR"/*)
            ;;
        *)
            return 1
            ;;
    esac

    relative="${candidate#"$FILES_DIR"/}"
    IFS='/' read -r -a components <<<"$relative"

    current="$FILES_DIR"

    for component in "${components[@]}"; do
        [[ -n "$component" ]] || continue

        current="$current/$component"

        # Proíbe links simbólicos, inclusive links quebrados.
        [[ ! -L "$current" ]] || return 1

        if [[ "$current" != "$candidate" &&
              -e "$current" &&
              ! -d "$current" ]]; then
            return 1
        fi
    done

    printf '%s\n' "$candidate"
}

to_virtual_path() {
    local physical="$1"
    local relative="${physical#"$FILES_DIR"}"

    if [[ -z "$relative" ]]; then
        printf '/\n'
    else
        printf '%s\n' "$relative"
    fi
}

request="$(cat)"

jq -e 'type == "object"' >/dev/null 2>&1 <<<"$request" ||
    die_json 'requisição inválida'

name="$(
    jq -er '.name | select(type == "string" and length > 0)' <<<"$request"
)" || die_json 'nome da ferramenta ausente'

args="$(
    jq -cer '
        (.arguments // {})
        | if type == "string" then fromjson else . end
        | select(type == "object")
    ' <<<"$request"
)" || die_json 'argumentos inválidos'

case "$name" in
    write_file)
        virtual="$(
            jq -er '
                (.file_path // .path)
                | select(type == "string" and length > 0)
            ' <<<"$args"
        )" || die_json 'file_path inválido'

        content="$(
            jq -er '.content | select(type == "string")' <<<"$args"
        )" || die_json 'content inválido'

        content_size="$(
            printf '%s' "$content" |
                wc -c |
                tr -d '[:space:]'
        )"

        ((content_size <= MAX_FILE_SIZE)) ||
            die_json "conteúdo maior que o limite de $MAX_FILE_SIZE bytes"

        target="$(resolve_path "$virtual")" ||
            die_json 'caminho inseguro'

        [[ "$target" != "$FILES_DIR" ]] ||
            die_json 'não é possível gravar na raiz de arquivos'

        parent="$(dirname -- "$target")"
        mkdir -p -- "$parent"

        target="$(resolve_path "$virtual")" ||
            die_json 'diretório inseguro'

        parent="$(dirname -- "$target")"
        temporary="$(mktemp "$parent/.meligpt.XXXXXX")"
        trap 'rm -f -- "${temporary:-}"' EXIT

        printf '%s' "$content" >"$temporary"
        chmod 600 -- "$temporary"
        mv -fT -- "$temporary" "$target"
        temporary=""

        success_content_json "gravado localmente: $virtual"
        ;;

    read_file)
        virtual="$(
            jq -er '
                (.file_path // .path)
                | select(type == "string" and length > 0)
            ' <<<"$args"
        )" || die_json 'file_path inválido'

        target="$(resolve_path "$virtual")" ||
            die_json 'caminho inseguro'

        [[ "$target" != "$FILES_DIR" ]] ||
            die_json 'não é possível ler a raiz como arquivo'

        [[ -f "$target" && ! -L "$target" ]] ||
            die_json "arquivo local não encontrado: $virtual"

        target="$(realpath -e -- "$target")" ||
            die_json 'não foi possível resolver o arquivo'

        case "$target" in
            "$FILES_DIR"/*)
                ;;
            *)
                die_json 'arquivo fora da raiz permitida'
                ;;
        esac

        size="$(
            wc -c <"$target" |
                tr -d '[:space:]'
        )"

        ((size <= MAX_FILE_SIZE)) ||
            die_json "arquivo maior que o limite de $MAX_FILE_SIZE bytes"

        # Bash não consegue armazenar NUL em variável.
        if LC_ALL=C grep -q $'\0' "$target" 2>/dev/null; then
            die_json "arquivo binário não suportado: $virtual"
        fi

        content="$(cat -- "$target")"
        success_content_json "$content"
        ;;

    ls|list_files)
        virtual="$(
            jq -er '
                (
                    .path
                    // .directory
                    // .dir_path
                    // .file_path
                    // "/"
                )
                | select(type == "string" and length > 0)
            ' <<<"$args"
        )" || die_json 'caminho de diretório inválido'

        recursive="$(
            jq -r '
                (
                    .recursive
                    // .recurse
                    // false
                )
                | if type == "boolean" then . else false end
            ' <<<"$args"
        )"

        target="$(resolve_path "$virtual")" ||
            die_json 'caminho inseguro'

        [[ -d "$target" && ! -L "$target" ]] ||
            die_json "diretório local não encontrado: $virtual"

        entries_file="$(mktemp)"
        trap 'rm -f -- "${entries_file:-}" "${temporary:-}"' EXIT

        count=0

        if [[ "$recursive" == "true" ]]; then
            find_args=(-mindepth 1)
        else
            find_args=(-mindepth 1 -maxdepth 1)
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

            if [[ -d "$resolved" ]]; then
                entry_type="directory"
                entry_size=0
            elif [[ -f "$resolved" ]]; then
                entry_type="file"
                entry_size="$(
                    wc -c <"$resolved" |
                        tr -d '[:space:]'
                )"
            else
                continue
            fi

            entry_path="$(to_virtual_path "$resolved")"
            entry_name="$(basename -- "$resolved")"

            jq -cn \
                --arg name "$entry_name" \
                --arg path "$entry_path" \
                --arg type "$entry_type" \
                --argjson size "$entry_size" \
                '{
                    name: $name,
                    path: $path,
                    type: $type,
                    size: $size
                }' >>"$entries_file"

            count=$((count + 1))
            ((count < MAX_LS_RESULTS)) || break
        done < <(
            find -P "$target" \
                "${find_args[@]}" \
                -print0 |
                sort -z
        )

        jq -sc \
            --arg path "$virtual" \
            --argjson recursive "$recursive" \
            --argjson truncated "$((count >= MAX_LS_RESULTS))" \
            '{
                success: true,
                path: $path,
                recursive: $recursive,
                truncated: $truncated,
                entries: .
            }' "$entries_file"
        ;;

    *)
        die_json "ferramenta local não permitida: $name"
        ;;
esac
