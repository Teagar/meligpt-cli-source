# MeliGPT CLI (Python)

Cliente de linha de comando — e servidor HTTP/SSE opcional — para o
"MeliGPT", reescrito em Python a partir da implementação original em Bash
(preservada em [`legacy/`](legacy/)). Usa **suas próprias** credenciais de
sessão (importadas de um HAR do navegador) para conversar com o endpoint,
com streaming em tempo real e execução local de `ls`/`read_file`/`write_file`
quando o modelo pede.

> Este é um cliente pessoal para um serviço interno. Use-o somente com uma
> conta e um serviço aos quais você tenha acesso autorizado.

## Visão geral

- **CLI** (`meligpt "sua mensagem"`): comportamento padrão, equivalente ao
  script Bash original, com saída visual aprimorada (via `rich`).
- **Servidor HTTP/SSE opcional** (`meligpt serve`): expõe a mesma
  orquestração via `POST /v1/chat` (Server-Sent Events), para quem prefere
  integrar por HTTP em vez de invocar o binário.
- **Ferramentas locais**: `ls`, `read_file`, `write_file` (reais, com
  contraparte no Bash original) + 8 ferramentas "stub" (`edit_file`,
  `glob`, `grep`, `write_todos`, `parallel`, `task`, `WebSearch`,
  `ImageGeneration`) que respondem `tool_not_implemented` de forma
  explícita — ver [`docs/tools.md`](docs/tools.md).

## Requisitos

- Python 3.12+ (ou Docker)
- Uma sessão autenticada válida no serviço MeliGPT, capturada em HAR

## Instalação

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Configuração inicial (importar credenciais)

1. Abra o MeliGPT no navegador, com o DevTools na aba Network.
2. Envie uma mensagem qualquer.
3. Clique com o botão direito na requisição `openAI` → "Save all as HAR".
4. Importe:

```bash
meligpt import-har caminho/para/sessao.har
```

Isso grava `ACCESS_TOKEN` e `COOKIE_HEADER` em
`~/.config/meligpt-cli/secrets.env` (permissão `600`). **Apague o HAR
depois** — ele contém os mesmos segredos.

## Uso — CLI

```bash
meligpt "explique este trecho de código"
meligpt --auto-files "compare /files/a.txt com /files/b.txt"
meligpt -f /files/relatorio.md "resuma este arquivo"
meligpt --no-discovery "não tente descobrir arquivos automaticamente"
```

Se o token expirar (HTTP 401), a CLI pergunta interativamente se você quer
importar um HAR novo e tenta novamente **uma única vez**.

## Refresh automático de token (sem precisar reimportar HAR)

Enquanto `meligpt serve` estiver rodando, um loop em background renova o
`access_token` sozinho, chamando `POST /api/auth/refresh` com o
`refreshToken` que já está salvo — exatamente o que o navegador faz por
trás dos panos. Ele agenda a renovação com base no `exp` real do JWT atual
(com uma margem de segurança de `MELIGPT_TOKEN_REFRESH_MARGIN_SECONDS`,
default 120s antes de expirar), então você não precisa mais reimportar o
HAR manualmente a cada ~15 minutos.

Isso só funciona enquanto o **refreshToken** em si continuar válido (no
HAR observado, ele dura bem mais que o access token). Quando o
refreshToken também expirar, o refresh automático vai falhar
silenciosamente (logado como aviso) e você vai precisar importar um HAR
novo — nesse caso a CLI volta ao fluxo interativo normal de recuperação de
401.

Desative com `MELIGPT_AUTO_REFRESH_ENABLED=false` se preferir controlar
manualmente, ou dispare um refresh na hora com:
```bash
curl -X POST http://localhost:8080/v1/auth/refresh
```

## Uso — servidor HTTP/SSE opcional

```bash
meligpt serve --host 0.0.0.0 --port 8080
```

```bash
curl -N -X POST http://localhost:8080/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "explique este trecho de código"}'
```

Eventos emitidos: `text_delta`, `info`, `warning`, `tool_result`, `done`,
`error`. O servidor **não** faz recuperação interativa de 401 (não há
terminal em um processo de servidor); um 401 vira um evento `error`
estruturado para o cliente decidir o que fazer — na prática isso deve ficar
raro com o refresh automático ligado.

## Uso — endpoint compatível com OpenAI (para OpenClaude e similares)

O servidor também expõe `POST /v1/chat/completions` e `GET /v1/models` no
formato da API de Chat Completions da OpenAI, para conectar clientes que
só falam esse protocolo (ex.: OpenClaude via `OPENAI_BASE_URL`):

```bash
export OPENAI_BASE_URL=http://localhost:8080/v1
export OPENAI_API_KEY=qualquer-coisa   # não é validado, mas o cliente exige o campo
export OPENAI_MODEL=meligpt
```

**Limitação importante:** este adaptador só repassa texto — ele não
implementa function calling no formato OpenAI (`tools`/`tool_calls`
estruturados). Ferramentas que o MeliGPT executar remotamente continuam
sendo espelhadas localmente e aparecem como texto na resposta, mas o loop
de tool-calling *nativo* do OpenClaude (bash, grep, glob rodando do lado
dele) não é acionado por este endpoint — para isso ele depende do modelo
remoto devolver `tool_calls` estruturados, o que exigiria o MeliGPT
suportar o parâmetro `tools` (hoje sempre enviado vazio: `"tools": []`).

## Configuração

Todas as variáveis usam o prefixo `MELIGPT_` — ver
[`.env.example`](.env.example) para a lista completa (diretórios, limites,
timeouts, endpoint, modelo, host/porta do servidor).

## Volumes / diretórios

| Caminho (dentro do container) | Conteúdo |
|---|---|
| `/data/config` | `secrets.env` |
| `/data/files`  | raiz sandbox das ferramentas `ls`/`read_file`/`write_file` |

## Ferramentas disponíveis

Ver [`docs/tools.md`](docs/tools.md) para o schema completo de cada uma.

## Testes

```bash
pip install -e ".[dev]"
ruff check .
ruff format --check .
mypy src
pytest -q
pytest --cov=src --cov-report=term-missing
```

## Docker

```bash
docker build -t meligpt-cli:local .
docker run --rm -it \
  -v meligpt-config:/data/config \
  -v meligpt-files:/data/files \
  meligpt-cli:local chat "olá"

docker compose up -d   # sobe o servidor HTTP/SSE
```

## Troubleshooting

| Sintoma | Causa provável | Solução |
|---|---|---|
| `secrets_not_found` | `secrets.env` ausente | rode `meligpt import-har` |
| `authentication_error` / 401 repetido | HAR capturado de uma sessão já expirada | capture um HAR novo, mais recente |
| `upstream_forbidden` / 403 | sessão/conta sem permissão, VPN, ou bloqueio de rede | confirme que a conta usada no navegador tem acesso |
| `path_traversal` / `symlink_not_allowed` | a ferramenta tentou sair da raiz `/data/files` | comportamento esperado — é a sandbox funcionando |
| Ferramenta retorna `tool_not_implemented` | ferramenta da Fase B (sem provedor real) | ver `docs/tools.md` — não existia no Bash original |

## Migração a partir da versão Bash

Ver [`docs/migration.md`](docs/migration.md) para a correspondência
completa Bash → Python e o plano de rollback.
