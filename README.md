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

### Memória de conversa (como o OpenClaude "não esquece" mais)

O protocolo OpenAI não tem noção de sessão: o OpenClaude reenvia o
histórico inteiro em `messages` a cada requisição, "achando" que isso dá
memória ao servidor do outro lado. O MeliGPT, por baixo, já tem memória
de conversa de verdade (é LibreChat): uma vez que você manda
`conversationId` + `parentMessageId`, o próprio backend reconstrói o
histórico — não é preciso reenviar nada.

Este servidor aproveita isso: depois de cada resposta, ele guarda (só em
memória, por processo) um mapeamento entre "essa sequência específica de
mensagens do usuário" e o `conversationId`/`messageId` reais que o
MeliGPT devolveu — **a chave usa só as mensagens `user`, nunca
`system`/`assistant`** (ver `chat/session_store.py`), justamente porque
essas duas costumam ser reconstruídas do zero em situações legítimas de
continuação — por exemplo, `openclaude --continue` recarrega a conversa
salva e regenera o `system` e as anotações de tool call do `assistant`,
mas o texto que você digitou continua sendo o mesmo. No próximo turno —
que chega com essas mesmas perguntas do usuário + uma nova, porque é
assim que o OpenClaude funciona — o servidor reconhece a sessão e manda
**só a mensagem nova**, com `conversationId`/`parentMessageId` apontando
pra conversa certa. Isso resolve três problemas de uma vez:

- **O assistente não "esquece" e começa um chat novo a cada mensagem** —
  antes, cada chamada criava uma conversa `conversationId: null` nova no
  MeliGPT; agora ela é continuada de verdade.
- **Geração de imagem/vídeo usa só o pedido atual como prompt** — antes,
  como a "memória" era feita colando a transcrição inteira dentro do
  campo `text` (o mesmo campo usado como prompt de geração), pedir um
  vídeo no meio de uma conversa longa fazia o MeliGPT gerar a partir da
  conversa inteira, não do pedido. Agora `text` só carrega a mensagem
  atual quando a conversa está sendo continuada.
- **`openclaude --continue` volta pro chat original, em vez de criar um
  novo** — a sessão é reconhecida mesmo que o `system`/`assistant`
  tenham sido reconstruídos de forma diferente ao recarregar, e mesmo
  que as próprias mensagens `user` tragam blocos efêmeros injetados pelo
  OpenClaude/Claude Code (`<system-reminder>`, `<available-deferred-tools>`
  — reminders de estado, listas de ferramentas disponíveis no turno) que
  mudam a cada retomada mesmo pro MESMO texto digitado. Esses blocos são
  ignorados ao calcular a chave (`_stable_user_text` em
  `api/openai_compat.py`) — extensível caso o OpenClaude passe a usar
  outra tag ephemeral no futuro.

Quando não há uma sessão pra continuar (primeira mensagem da conversa, ou
o servidor reiniciou e perdeu o cache em memória), ele cai de volta para
o comportamento antigo só naquele turno: manda a transcrição inteira,
cria uma conversa nova, e a partir daí volta a ficar incremental. Ou
seja: nunca quebra, só degrada de forma previsível.

### Bifurcar (fork) uma conversa

`POST /v1/conversations/fork` espelha o botão "Fork" da UI web do
MeliGPT (confirmado por HAR real). Três opções, iguais às da interface:

| `option`            | Equivalente na UI                              |
|----------------------|-------------------------------------------------|
| `"directPath"`        | "Apenas mensagens visíveis"                     |
| `"includeBranches"`   | "Incluir ramificações relacionadas"             |
| `""` (padrão)          | "Incluir todos para/de aqui" (todas as mensagens, visíveis ou não) |

```bash
curl -X POST http://localhost:8080/v1/conversations/fork \
  -H "Content-Type: application/json" \
  -d '{"conversation_id": "<id>", "message_id": "<id>", "option": "includeBranches"}'
```

Ou pela CLI:

```bash
meligpt fork <conversation_id> <message_id> --option related-branches
```

`--option` aceita `visible-only`, `related-branches` ou `all` (default).
Como o protocolo OpenAI não tem conceito de fork, essa funcionalidade só
fica disponível via este endpoint/CLI — não há como acioná-la a partir do
próprio OpenClaude.

### `/loop` e `CronCreate` (OpenClaude)

Se você usa o OpenClaude apontado para este servidor, `/loop` e
`CronCreate` funcionam **sem nenhuma implementação adicional aqui**: é um
agendador 100% client-side do próprio OpenClaude/Claude Code, que roda
dentro do processo dele e reinjeta prompts na sessão — não fala com
nenhum backend externo. Cada disparo automático chega neste servidor como
uma chamada HTTP normal em `/v1/chat/completions`, indistinguível de uma
mensagem digitada à mão, e a memória de conversa incremental (ver acima)
já cobre isso.

## Restringir a uma pasta específica (recomendado)

Se você quer que o modelo (via OpenClaude) só leia/altere arquivos
dentro da pasta onde você está trabalhando — não o filesystem inteiro —
use `--here` (ou `--files-dir`) ao subir o servidor:

```bash
cd /tmp/tmp.ojoi4343   # a pasta do seu projeto
meligpt import-har seu-arquivo.har   # uma vez, para autenticar
meligpt serve --here
```

Isso restringe `ls`/`read_file`/`write_file`/`edit_file`/`glob`/`grep`
a essa pasta e subpastas — com a mesma proteção contra path traversal
usada em todo o resto do projeto (`..`, symlinks pra fora, etc. são
bloqueados, não só "escondidos"). Pra apontar pra uma pasta específica
sem precisar `cd` até ela:

```bash
meligpt serve --files-dir /tmp/tmp.ojoi4343
```

Como o `meligpt serve` é um processo único e de vida longa, o escopo
vale pra aquela execução inteira — pra trocar de projeto, pare o
servidor (`Ctrl+C`) e suba de novo com `--here` na nova pasta.

> ⚠️ **`bash` é a exceção**: ele começa nessa pasta (`cwd`), mas não é
> limitado a ela do mesmo jeito — um comando pode fazer `cd ..` ou
> referenciar um caminho absoluto fora do escopo, e vai funcionar. Não
> existe sandbox de processo (container/chroot) por trás disso. Se
> precisar de garantia real contra isso, rode `meligpt serve` dentro de
> um container com bind mount só da pasta do projeto.

## Acesso total ao filesystem (sem restrição)

Se você quer que o modelo (via OpenClaude) execute comandos e crie/edite
arquivos livremente na sua máquina inteira — não só numa pasta — use o
preset `.env.full-access.example`:

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
filesystem real. Prefira a seção anterior (`--here`/`--files-dir`) a
menos que você realmente precise disso — é estritamente mais arriscado,
e só faz sentido em máquina pessoal/dev, nunca num servidor
compartilhado ou exposto à internet.

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
meligpt models                    # lista todo o catálogo, agrupado por GERAL/IMAGEM/VÍDEO
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
catálogo local fixo, dividido em três categorias
(`meligpt models` agrupa a saída assim):

- **GERAL (chat)** — 47 modelos.
- **IMAGEM** — 7 modelos.
- **VÍDEO** — 4 modelos.

Ver `.env.example` para `MELIGPT_MODELS_URL` / `MELIGPT_MODELS_CACHE_SECONDS`.

### IDs confirmados vs. melhor-esforço

Só **12** desses modelos (8 de chat + os 4 de vídeo) foram confirmados por
HAR real — uma chamada de verdade, observada ao vivo, que funcionou. O
resto do catálogo veio colado da UI do MeliGPT (nome + provedor visíveis
no seletor), sem o id interno usado no payload — então o id de cada um
foi **inferido** pelo padrão observado nos 12 confirmados (nome em
minúsculas, espaços viram hífen), com duas exceções onde dá pra usar algo
mais confiável que um chute: os modelos Bedrock (`amazon.nova-*`,
`us.meta.llama*`) seguem o formato de id oficial e público da AWS, e
`gpt-oss-120b`/`gpt-oss-20b` são os nomes públicos reais dos modelos
open-weight da OpenAI.

Todo modelo inferido sai marcado `confirmed: false` — em `meligpt models`
(`[NÃO CONFIRMADO]`) e em `GET /v1/models`/`GET /v1/models/{id}` (campo
`"confirmed"`, extensão fora do padrão OpenAI que o OpenClaude ignora).

**Se um desses falhar** (o backend do MeliGPT devolve erro de "modelo
desconhecido" ou similar), é só corrigir a string do id em
`src/meligpt/catalog.py` — é o único lugar que precisa mudar, não tem id
espalhado em mais nenhum arquivo. Se puder, mande um HAR da chamada que
funcionou (mesmo processo usado pra confirmar os 12 originais e o fork:
`Network` do DevTools → filtra por `/api/ask/` → botão direito → "Save
all as HAR") pra eu marcar como `confirmed: true` de vez.

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

O catálogo (`meligpt models`) inclui 4 modelos de vídeo — **todos os 4
ids confirmados por HAR real** (geração bem-sucedida de cada um,
2026-08-10/11; ver `tests/fixtures/video_generation_sse_*.txt` e
`tests/integration/test_video_generation_real_har.py`):

| Nome de exibição | Id | Provedor |
|---|---|---|
| Veo 3.1 Fast Generate | `veo-3.1-fast-generate-001` | google |
| Veo 3.1 Generate | `veo-3.1-generate-001` | google |
| Sora 2 | `sora-2` | openAI |
| HappyHorse 1.0 | `happyhorse-1.0-t2v` | alibaba |

```bash
meligpt chat --model veo-3.1-fast-generate-001 "gere um vídeo de um gato correndo"
```

No OpenClaude, `/model` (ou o seletor equivalente) troca o modelo, e o
pedido de vídeo funciona pelo `/v1/chat/completions` normalmente (ver
"Rotas HTTP via API" acima).

Nenhum dos 4 ids era adivinhável só pelo nome de exibição — Veo e
HappyHorse têm sufixos de versão (`-001`, `-t2v`) que só apareceram no
payload real. Se o MeliGPT trocar de versão no futuro (erro do
servidor), o único lugar que precisa mudar é `_VIDEO_MODELS` em
`src/meligpt/catalog.py`.

**Confirmado pelos mesmos HARs** (e já corrigido no código):
- O payload da requisição sempre inclui um campo `"examples"`
  (`[{"input": {"content": ""}, "output": {"content": ""}}]`) que nossa
  implementação não mandava antes — isso quebrava geração de vídeo.
- A resposta final vem como uma tag `<videoplayer url="/api/media/..."/>`
  (não markdown) — a extração de mídia já lida com isso (é baseada em
  regex sobre o texto, não assume nenhum formato específico ao redor do
  link).
- O evento SSE de nível de transporte é `event: message` com payload
  `{"final": true, "responseMessage": {...}}` — diferente de
  `on_message_delta`/`on_run_step_completed` (texto/imagem), mas nosso
  parser já reconhecia `responseMessage` independente do nome do evento.
- Confirmado com os 4 provedores diferentes (openAI, google, alibaba →
  generic) — a mesma rota (`/api/ask/{endpoint}`) e o mesmo formato de
  resposta valem pra qualquer um deles.

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
