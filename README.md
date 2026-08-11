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
- **Ferramentas locais**: `ls`, `read_file`, `write_file`, `edit_file`,
  `glob`, `grep`, `write_todos`, `WebSearch`, `bash` (todas implementadas
  de verdade — `bash` vem **desligada por padrão** por segurança) + 3
  ferramentas "stub" (`parallel`, `task`, `ImageGeneration`) que
  respondem `tool_not_implemented` de forma explícita — ver
  [`docs/tools.md`](docs/tools.md).

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
estruturados). Ferramentas que o MeliGPT executar remotamente (`ls`,
`read_file`, `write_file`, `edit_file`, `glob`, `grep`, `write_todos`,
`WebSearch` — todas implementadas de verdade, ver
[`docs/tools.md`](docs/tools.md)) continuam sendo espelhadas localmente e
aparecem como texto na resposta, mas o loop de tool-calling *nativo* do
OpenClaude (bash, grep, glob rodando do lado dele) não é acionado por
este endpoint — para isso ele depende do modelo remoto devolver
`tool_calls` estruturados, o que exigiria o MeliGPT suportar o parâmetro
`tools` (hoje sempre enviado vazio: `"tools": []`).

Todas as ferramentas acima funcionam igual pela CLI e por este endpoint —
ambos os caminhos passam pela mesma orquestração
(`chat/service.py:run_chat`), então qualquer ferramenta chamada pelo
modelo remoto é espelhada da mesma forma independente de como você está
conversando com ele.

### `/loop` e `CronCreate` (OpenClaude)

Se você usa o OpenClaude apontado para este servidor, `/loop` e
`CronCreate` funcionam **sem nenhuma implementação adicional aqui**: é um
agendador 100% client-side do próprio OpenClaude/Claude Code, que roda
dentro do processo dele e reinjeta prompts na sessão — não fala com
nenhum backend externo. Cada disparo automático chega neste servidor como
uma chamada HTTP normal em `/v1/chat/completions`, indistinguível de uma
mensagem digitada à mão, e a memória multi-turno (transcrição inteira
reenviada a cada turno) já cobre isso.

## Uso local com bash + filesystem real liberados

Se você quer que o modelo (via OpenClaude) execute comandos e crie/edite
arquivos livremente na sua máquina — não num sandbox — use o preset
`.env.full-access.example`:

```bash
cp .env.full-access.example .env
meligpt import-har seu-arquivo.har   # uma vez, para autenticar
meligpt serve
```

No OpenClaude, aponte o provider (base URL) para `http://localhost:8080/v1`
e rode com um modo de permissão que não interrompe a cada ação:

```bash
openclaude --permission-mode acceptEdits
# ou, sem nenhum prompt de confirmação (só em máquina que você controla):
openclaude --dangerously-skip-permissions
```

Depois de subir o servidor, rode `./scripts/verify_full_access.sh` para
conferir em 2 minutos se a config de acesso total (bash + filesystem real
+ catálogo de modelos) está correta antes de testar pelo OpenClaude.

⚠️ Isso dá ao modelo remoto acesso de shell e escrita irrestrita no seu
filesystem real. Só faz sentido em máquina pessoal/dev — nunca num
servidor compartilhado ou exposto à internet.

## Catálogo de modelos multi-provedor

O MeliGPT expõe vários "provedores" via rotas HTTP distintas
(`/api/ask/openAI`, `/api/ask/google`, `/api/ask/nova`,
`/api/ask/generic` para o restante), e cada requisição também carrega um
campo `"endpoint"` no corpo — que **nem sempre coincide com a rota**: o
Claude, por exemplo, usa a rota `/api/ask/generic` mas manda
`"endpoint": "bedrock"` no payload. O catálogo (`src/meligpt/catalog.py`)
guarda os dois separadamente (`route` vs `payload_endpoint`) para lidar
com isso.

```bash
meligpt models                    # lista todo o catálogo
meligpt models --provider google  # filtra por provedor
meligpt providers                 # lista as rotas conhecidas

meligpt chat --model gemini-3.6-flash "explique este código"
meligpt chat --endpoint anthropic "explique este código"
```

Rotas HTTP via API:

- `GET /v1/models` (aceita `?provider=` e `?endpoint=`)
- `GET /v1/models/{id}`
- `GET /v1/providers`
- `POST /v1/chat` aceita `"model"` e/ou `"endpoint"` no corpo
- `POST /v1/chat/completions` (compatível com OpenAI) troca de
  modelo/rota quando `"model"` bate com um id real do catálogo; caso
  contrário preserva o comportamento padrão (`Settings.model` /
  `resolved_endpoint()`) — então clientes como o OpenClaude, que sempre
  mandam um rótulo genérico (`"meligpt"`), continuam funcionando sem
  mudança nenhuma. Aceita modelos de qualquer tipo (chat/image/video) —
  é o único endpoint que clientes OpenAI-compatible como o OpenClaude
  falam, então bloquear por tipo os deixaria inacessíveis na prática.

Sem `MELIGPT_MODELS_URL` configurado (não há evidência de HAR para uma
URL de catálogo remoto real — fica puramente opcional), o servidor usa um
catálogo local fixo com os 12 modelos confirmados/inferidos manualmente
(8 de chat + 4 de vídeo — ver seção "Modelos de vídeo" abaixo). Ver
`.env.example` para `MELIGPT_MODELS_URL` / `MELIGPT_MODELS_CACHE_SECONDS`.

**Memória de conversa:** o MeliGPT não expõe `conversationId` persistente
para este adaptador, mas o OpenClaude (como qualquer cliente
OpenAI-compatible padrão) reenvia o histórico completo em `messages` a
cada requisição. Por isso o adaptador serializa a conversa inteira num
único prompt de texto a cada turno — sem precisar guardar estado no
servidor, o modelo remoto passa a "lembrar" o que foi dito antes.

**Contexto automático de arquivos:** antes de cada turno, o adaptador
lista o sandbox local (`ls` recursivo) e injeta um snapshot compacto dos
caminhos existentes junto com o prompt — assim o modelo já sabe quais
arquivos existem sem que o usuário precise pedir `ls` manualmente
primeiro. A descoberta automática por nome de arquivo (pensada para
prompts curtos digitados por humano) continua desligada nesse endpoint,
já que rodar sobre uma transcrição inteira gerava avisos de "arquivo não
encontrado" falsos; referências explícitas `/files/...` continuam
funcionando normalmente.

## Configuração

Todas as variáveis usam o prefixo `MELIGPT_` — ver
[`.env.example`](.env.example) para a lista completa (diretórios, limites,
timeouts, endpoint, modelo, host/porta do servidor, chave do provedor de
busca web, toggle experimental de `browsing` nativo).

## Volumes / diretórios

| Caminho (dentro do container) | Conteúdo |
|---|---|
| `/data/config` | `secrets.env` |
| `/data/files`  | raiz sandbox das ferramentas `ls`/`read_file`/`write_file` |

## Fazendo `write_file`/`read_file`/`edit_file` operarem na sua pasta real (OpenClaude local)

Por padrão, as ferramentas de arquivo escrevem num sandbox isolado
(`/data/files` no Docker, `~/.config/meligpt-cli/files` fora dele) — **não**
na pasta onde você está rodando o OpenClaude, mesmo que os dois processos
estejam na mesma máquina. Isso é proposital (o mesmo `meligpt serve` pode,
em tese, atender qualquer cliente, não só um OpenClaude local).

Se você roda `meligpt serve` no **mesmo dispositivo** que o OpenClaude e
quer que as ferramentas leiam/escrevam de verdade na pasta onde você está
(`pwd`), ligue o modo passagem direta:

```bash
export MELIGPT_FILES_DIR=/
export MELIGPT_ALLOW_FULL_FILESYSTEM_ACCESS=true
meligpt serve
```

Com isso, um caminho como `/tmp/tmp.v2Ugw0ltmU/index.js` (o que o
OpenClaude relata como seu cwd) passa a apontar para o caminho real
`/tmp/tmp.v2Ugw0ltmU/index.js` no disco, não mais para dentro de um
sandbox isolado.

> ⚠️ Isso dá ao modelo remoto acesso de leitura/escrita a **todo o
> filesystem visível a este processo** — não só à pasta do seu projeto.
> Rode com o usuário mais restrito possível, evite rodar como root, e
> desligue quando não estiver usando ativamente. Sem
> `MELIGPT_ALLOW_FULL_FILESYSTEM_ACCESS=true`, o servidor recusa iniciar
> com `MELIGPT_FILES_DIR=/` — essa segunda variável existe justamente
> para você não ativar isso sem querer.

## Ferramentas disponíveis

Ver [`docs/tools.md`](docs/tools.md) para o schema completo de cada uma.

> ⚠️ **`bash` dá execução de comando real** e vem **desligada por
> padrão**. Só ative com `MELIGPT_ENABLE_BASH_TOOL=true` rodando dentro
> de um container isolado (como o próprio `Dockerfile` deste projeto já
> configura — usuário não-root, filesystem read-only fora de `/data`).
> Fora de um container assim, ligar essa ferramenta equivale a dar
> acesso de shell ao host onde o `meligpt serve` está rodando.

## Geração de imagens e vídeos

Quando o modelo remoto gera uma imagem ou vídeo, o MeliGPT serve o
arquivo via `GET /api/media/{userId}/{filename}` (rota confirmada por
HAR — vista com imagens, mas independente de extensão, então vídeo
funciona pelo mesmo mecanismo). O servidor detecta esse link no texto da
resposta, baixa o arquivo autenticado e salva localmente — sem precisar
de nenhuma ferramenta adicional do lado do modelo.

**Onde é salvo:**
- Por padrão: `MELIGPT_CONFIG_DIR/generated-images/` (configurável via
  `MELIGPT_MEDIA_DIR`) — **sempre** independente de `MELIGPT_FILES_DIR`,
  mesmo em modo de acesso total (`MELIGPT_FILES_DIR=/`), porque gravar
  sob a raiz real do filesystem exigiria permissão de root e falharia
  (bug real encontrado e corrigido em teste end-to-end; ver
  `docs/migration.md` para o changelog).
- Pra escolher onde salvar num turno específico, use `--media-dir`
  (CLI) ou o campo `"media_dir"` (`/v1/chat` e `/v1/chat/completions`)
  — caminho relativo à raiz de arquivos configurada, ou absoluto em modo
  de acesso total (mesma semântica de `write_file`):
  ```bash
  meligpt chat --media-dir minhas-imagens "gere um gato"
  meligpt chat --media-dir /home/voce/Imagens "gere um gato"
  ```

**Como aparece:**
- **CLI**: `Imagem gerada salva em: <caminho>` ou `Vídeo gerado salvo em: <caminho>`.
- **`POST /v1/chat`** (SSE): evento `generated_media` com `virtual_path`,
  `url` e `media_type` (`"image"`/`"video"`/`"other"`).
- **`POST /v1/chat/completions`** (compatível OpenAI, streaming e
  não-streaming): aparece embutido no texto da resposta como
  `![imagem gerada](<caminho>)` ou `![vídeo gerado](<caminho>)`.

Falha ao baixar um arquivo específico vira um aviso — nunca derruba o
resto da resposta. Não há suporte (ainda) para reenviar uma imagem/vídeo
gerado de volta como referência num próximo turno, nem para editar mídia
existente — isso exigiria confirmar o schema de tool_call que o MeliGPT
usa para essas ações, que não temos evidência de HAR.

### Modelos de vídeo

O catálogo (`meligpt models`) inclui 4 modelos de vídeo, cujos **nomes
de exibição** foram confirmados pelo usuário no seletor do MeliGPT, mas
cujos **ids técnicos abaixo são inferidos** (seguindo o padrão dos ids
de chat já confirmados por HAR) — nunca vimos o payload real de uma
requisição usando eles:

| Nome de exibição | Id inferido | Provedor |
|---|---|---|
| Sora 2 | `sora-2` | openAI |
| Veo 3.1 Generate | `veo-3.1-generate` | google |
| Veo 3.1 Fast Generate | `veo-3.1-fast-generate` | google |
| HappyHorse 1.0 | `happyhorse-1.0` | alibaba |

```bash
meligpt chat --model sora-2 "gere um vídeo de um gato correndo"
```

No OpenClaude, `/model` (ou o seletor equivalente) troca o modelo pra
`sora-2`/`veo-3.1-generate`/etc., e o pedido de vídeo funciona pelo
`/v1/chat/completions` normalmente (ver "Rotas HTTP via API" acima).

Se o id não bater com o que o MeliGPT espera de verdade (erro do
servidor), o único lugar que precisa mudar é `_VIDEO_MODELS` em
`src/meligpt/catalog.py` — troque a string do id pela correta.

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
| Ferramenta retorna `tool_not_implemented` | `parallel`/`task`/`ImageGeneration` (sem provedor real) | ver `docs/tools.md` |
| Ferramenta espelhada falha com `tool_validation_error` (`file_path`/`content` inválido) | **Causa raiz identificada e corrigida** (confirmada via HAR real): o MeliGPT manda `on_run_step_completed` duas vezes para a mesma tool call, a segunda sem `args` — isso apagava os argumentos reais antes de chegar na ferramenta. Se ainda acontecer, é um formato de chave novo que ninguém tinha visto | a própria mensagem de erro mostra `args brutos: {...}` — cole isso ao reportar; as ferramentas de arquivo já aceitam vários aliases (`file_path`, `path`, `filepath`, `file`, `filename`, `target_path`, `target` / `content`, `text`, `file_content`, `data`, `body`) antes de desistir |
| `bash` retorna `tool_disabled` | ferramenta desligada por padrão (execução real de comando) | ative com `MELIGPT_ENABLE_BASH_TOOL=true` **só** se estiver rodando isolado em Docker — ver `docs/tools.md` |
| `write_file` falhava com "caminho local não encontrado" para caminhos tipo `/tmp/tmp.xxxx/arquivo.js` | **Corrigido**: o modelo remoto manda um caminho "de host" (refletindo o cwd que o cliente relatou a ele); `write_file` agora cria as subpastas automaticamente dentro da raiz sandbox, como `mkdir -p` | nenhuma ação necessária |
| Arquivo criado com sucesso (`[write_file] gravado localmente: ...`), mas não aparece na pasta onde você está rodando o OpenClaude | por padrão as ferramentas escrevem num sandbox isolado, não na pasta real do host, mesmo na mesma máquina | ligue o modo passagem direta — ver seção "Fazendo write_file/read_file/edit_file operarem na sua pasta real" acima |
| `unsafe_configuration` ao iniciar (`MELIGPT_FILES_DIR=/`) | confirmação de segurança exigida para o modo passagem direta | defina também `MELIGPT_ALLOW_FULL_FILESYSTEM_ACCESS=true`, sabendo que isso dá acesso ao filesystem inteiro visível ao processo |

## Migração a partir da versão Bash

Ver [`docs/migration.md`](docs/migration.md) para a correspondência
completa Bash → Python e o plano de rollback.
