#!/usr/bin/env bash
# Verificação rápida (2 minutos) de que bash + filesystem real +
# catálogo de modelos estão configurados corretamente.
#
# Uso:
#   cp .env.full-access.example .env
#   set -a; source .env; set +a
#   ./scripts/verify_full_access.sh
#
# Isso NÃO chama o MeliGPT remoto (precisaria de credenciais via
# `meligpt import-har`) — valida só a config local do servidor, que é a
# parte que dá pra checar sem depender de rede/HAR.

set -euo pipefail

pass() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$1"; }

echo "== 1. Variáveis de ambiente relevantes =="
for var in MELIGPT_FILES_DIR MELIGPT_ALLOW_FULL_FILESYSTEM_ACCESS MELIGPT_ENABLE_BASH_TOOL; do
    value="${!var:-<não definida>}"
    echo "  $var=$value"
done

echo
echo "== 2. Config local (sem precisar de credenciais) =="
if [ "${MELIGPT_FILES_DIR:-}" = "/" ] && [ "${MELIGPT_ALLOW_FULL_FILESYSTEM_ACCESS:-}" = "true" ]; then
    pass "modo passagem direta (filesystem real) configurado"
else
    fail "MELIGPT_FILES_DIR=/ e MELIGPT_ALLOW_FULL_FILESYSTEM_ACCESS=true não estão ambos setados"
fi

if [ "${MELIGPT_ENABLE_BASH_TOOL:-}" = "true" ]; then
    pass "ferramenta bash habilitada"
else
    fail "MELIGPT_ENABLE_BASH_TOOL não é 'true'"
fi

echo
echo "== 3. CLI local (models/providers, não precisa de credenciais) =="
if meligpt models >/tmp/meligpt_verify_models.txt 2>&1; then
    pass "meligpt models ok ($(wc -l < /tmp/meligpt_verify_models.txt) linhas)"
else
    fail "meligpt models falhou — veja /tmp/meligpt_verify_models.txt"
fi

if meligpt providers >/tmp/meligpt_verify_providers.txt 2>&1; then
    pass "meligpt providers ok"
else
    fail "meligpt providers falhou — veja /tmp/meligpt_verify_providers.txt"
fi

echo
echo "== 4. Servidor HTTP (só roda se 'meligpt serve' já estiver ativo) =="
host="${MELIGPT_SERVER_HOST:-127.0.0.1}"
[ "$host" = "0.0.0.0" ] && host="127.0.0.1"
port="${MELIGPT_SERVER_PORT:-8080}"
base="http://$host:$port"

if curl -fsS "$base/health" >/dev/null 2>&1; then
    pass "GET $base/health respondeu"
    if curl -fsS "$base/v1/models" | grep -q '"data"'; then
        pass "GET $base/v1/models respondeu com catálogo"
    else
        fail "GET $base/v1/models não retornou o formato esperado"
    fi
else
    echo "  (servidor não está rodando em $base — rode 'meligpt serve' e execute de novo pra checar esta parte)"
fi

echo
echo "== Próximo passo =="
echo "  1. meligpt import-har <arquivo.har>   # credenciais reais (uma vez)"
echo "  2. meligpt serve                       # sobe o servidor"
echo "  3. openclaude --permission-mode acceptEdits   # aponte o provider para $base/v1"
echo "  4. Peça pro modelo criar um arquivo de teste e rodar um comando — deve funcionar sem sandbox."
