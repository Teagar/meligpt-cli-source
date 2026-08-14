# Arquitetura

## Visão geral

O projeto original (`legacy/`) é um **cliente** de linha de comando: um
único usuário roda `chat-api.sh` no seu terminal, que fala HTTP/SSE com um
serviço remoto (`public-meligpt.adminml.com`) usando a sessão do próprio
usuário, e espelha localmente (no disco do próprio usuário) as tool calls
que o modelo remoto pede.

Isso é fundamentalmente diferente de "uma API com rotas que atendem
múltiplos clientes" — não existe, no Bash original, um servidor. A
reescrita preserva essa natureza de **CLI pessoal** como forma primária de
uso, e adiciona um **servidor HTTP/SSE opcional** (pedido explicitamente
para esta migração) que expõe a mesma orquestração para quem prefere
integrar por HTTP.

## Por que 4 das 11 "ferramentas" pedidas ainda são stubs

O prompt de migração usado nesta tarefa assumia um agente de coding
genérico com 12 ferramentas (`WebSearch`, `ImageGeneration`, `task`,
`edit_file`, `glob`, `grep`, `write_todos`, `parallel`, `ls`, `read_file`,
`write_file`). O projeto Bash real só implementava 3: `ls`, `read_file`,
`write_file` (ver `legacy/local-tools.sh`).

Decisão original (conforme pedido, "se algum comportamento estiver
ambíguo... registre a decisão"): as 8 ferramentas sem contraparte real
viraram **stubs explícitos** — mesmo nome público, mesmo lugar no
catálogo (`ToolRegistry`), sempre respondendo `tool_not_implemented` em
vez de fingir um comportamento que não existia.

Atualização posterior: uso real com o OpenClaude mostrou que o modelo
remoto do MeliGPT já tenta chamar `write_file` espontaneamente (sem que
nada tenha sido "ensinado" a ele sobre essas ferramentas) — então
implementar de verdade `edit_file`, `glob`, `grep` e `write_todos` trouxe
valor imediato, sem depender de nenhum provedor externo (são operações
100% locais, com a mesma segurança de filesystem das ferramentas
originais). `parallel`, `task`, `WebSearch` e `ImageGeneration` continuam
stub: os dois primeiros exigiriam inventar uma política de
concorrência/subagentes que não existe em lugar nenhum do projeto, e os
dois últimos dependem de um provedor externo (busca, geração de imagem)
que ninguém pediu para integrar. Ver `docs/tools.md`.

## Fluxo de chamadas (CLI)

```
cli.py
  └─ chat.service.run_chat()
       ├─ chat.prompt_builder.interpret_prompt()      (extração de intenção, sem tocar disco)
       ├─ filesystem.discovery.find_by_name /
       │  find_directory_by_name                       (etapa de descoberta)
       ├─ filesystem.context.build_local_context()      (usa tools.files.ls/read_file)
       ├─ auth.token_manager.TokenManager.load_credentials()
       ├─ clients.meligpt_http.MeliGPTClient.stream_chat()  (SSE assíncrono)
       │     └─ em 401: auth.token_manager.recover_from_401()  (máx. 1 tentativa)
       └─ tools.registry.ToolRegistry.dispatch()        (espelha write_file/read_file/ls)
```

O servidor HTTP (`api/routes.py`) chama exatamente `chat.service.run_chat()`
e traduz os eventos para SSE — nenhuma lógica de negócio é duplicada.

## Memória de conversa no adaptador OpenAI-compatible

`api/openai_compat.py` (usado pelo OpenClaude) não recebe nenhum
identificador de sessão do protocolo OpenAI — só um `messages[]` que
cresce a cada turno. `chat/session_store.py` guarda um cache LRU, em
memória, por processo: `hash(histórico) -> (conversationId, messageId)`
reais do MeliGPT. A cada turno:

1. Calcula o hash do histórico SEM a última mensagem.
2. Se bate com uma entrada do cache: manda só a última mensagem, com
   `conversationId`/`parentMessageId` da entrada — continua a conversa
   MeliGPT de verdade.
3. Se não bate (primeiro turno, ou cache perdido num restart): monta a
   transcrição inteira como bootstrap (`_build_transcript_prompt`),
   conversa nova no MeliGPT.
4. Depois de qualquer resposta bem-sucedida, grava
   `hash(histórico + resposta) -> (conversationId, messageId)` — pronto
   pro próximo turno encaixar no passo 2.

Isso substitui uma versão anterior que sempre recriava uma conversa nova
e sempre mandava a transcrição inteira como prompt — o que também
quebrava geração de imagem/vídeo (o mesmo campo `text` é usado como
prompt de geração pelo MeliGPT, então a geração acabava usando a conversa
inteira em vez do pedido atual).

## Fork de conversa

`clients/meligpt_http.py:MeliGPTClient.fork_conversation()` chama
`POST /api/convos/fork` do MeliGPT/LibreChat diretamente (payload e
semântica confirmados por HAR real) — não há árvore de mensagens local
pra replicar, o MeliGPT já é a fonte da verdade. Exposto via
`chat/service.py:fork_conversation()` (mesma política de retry de 401 que
`run_chat`), `POST /v1/conversations/fork` e `meligpt fork`.

## Registro de ferramentas

`tools/registry.py` expõe um `ToolRegistry` (nome → instância). Nenhum
outro módulo despacha por comparação de string (`if tool_name == "ls"`).
Cada ferramenta implementa o protocolo mínimo em `tools/base.py`
(`name`, `description`, `async execute(arguments, settings) -> dict`).

## Segurança de caminhos

Único módulo autorizado a tocar o filesystem por caminho virtual:
`filesystem/security.py`. Estratégia (ver docstring do módulo para
detalhes):

1. `filesystem/paths.py` rejeita qualquer componente **exatamente** `..`
   antes de qualquer normalização lexical.
2. `filesystem/security.py` resolve componente a componente a partir de um
   file descriptor da raiz sandbox, abrindo cada diretório intermediário
   com `O_DIRECTORY | O_NOFOLLOW` relativo ao descritor anterior
   (`dir_fd`). Isso amarra a resolução a inodes verificados, eliminando a
   janela clássica de TOCTOU "resolve por string, depois abre por string".
3. O componente final também é aberto com `O_NOFOLLOW` relativo ao
   descritor do pai — **nenhum symlink é seguido**, nem para leitura, nem
   para escrita, nem apontando para dentro ou para fora da raiz. A escrita
   usa `os.replace(..., src_dir_fd=..., dst_dir_fd=...)`, que substitui a
   *entrada de diretório*, nunca o alvo de um link.
4. Erros diferenciam `PathTraversalError`, `SymlinkNotAllowedError`,
   `FileNotFoundToolError`, `NotADirectoryToolError`,
   `PermissionDeniedToolError`.

### Semântica de caminho virtual

| Entrada | Resolve para (relativo à raiz sandbox) |
|---|---|
| `/` ou `/files` | raiz |
| `/files/x` | `x` |
| `/x` | `x` (o `/` inicial é a raiz *virtual*, não a raiz real do SO) |
| `./x` | `x` |
| `x` | `x` |

**Criação automática de diretórios intermediários** (`write_file`
apenas, via `create_missing_dirs=True` em `resolve_secure`): confirmado
em uso real que o modelo remoto costuma informar um caminho absoluto que
reflete o cwd "de host" relatado pelo cliente (ex.: `/tmp/tmp.xxxx/`),
não consciente de que a raiz `/` aqui é virtual. Exigir que cada
subpasta já exista antes de escrever um arquivo não é o comportamento
esperado de um `write_file` de agente de código — a maioria das
implementações equivalentes (incluindo as ferramentas nativas de agentes
de coding) já faz `mkdir -p` implícito. A criação respeita as mesmas
garantias de segurança: cada componente continua sendo resolvido via
`dir_fd`/`O_NOFOLLOW`, então não é possível criar diretório atravessando
um symlink nem escapar da raiz.

## SSE, streaming e 401

`clients/meligpt_http.py` usa `httpx.AsyncClient` em modo streaming
(nunca bloqueia o event loop). Content-Type inesperado, status != 200 e
timeouts viram exceções estruturadas (`UpstreamHTTPError`,
`UpstreamForbiddenError`, `UpstreamTimeoutError`, `UpstreamError`).

A recuperação de 401 (`auth/token_manager.py`) segue exatamente a política
do Bash original: no máximo **uma** nova tentativa por execução
(equivalente a `MELIGPT_RETRIED_AFTER_401` no script). Em modo não
interativo (ex.: servidor HTTP), a recuperação automática não é tentada —
o erro é propagado estruturado para o chamador decidir.

No servidor (`api/routes.py`), a desconexão do cliente é detectada via
`request.is_disconnected()`, verificada antes de cada evento produzido;
o cancelamento do `async generator` do `httpx` fecha o cliente HTTP
subjacente automaticamente (`async with`).

### Deduplicação de eventos `on_run_step_completed` (tool calls)

Confirmado via HAR real contra o backend (modelo Claude/bedrock): o
MeliGPT emite `on_run_step_completed` **mais de uma vez** para a mesma
tool call — a primeira ocorrência traz `tool_call.args` completo (às
vezes como string JSON), e uma segunda ocorrência de "fechamento" chega
com o mesmo `id`, mas **sem** o campo `args`/`arguments`. `chat/service.py`
mantém as tool calls vistas num dicionário por `id`; sem tratamento
especial, a segunda ocorrência sobrescreveria a primeira com argumentos
vazios, e toda ferramenta espelhada falharia com "argumento inválido"
mesmo o modelo tendo enviado tudo certo.

A regra aplicada: um evento novo só substitui um evento já visto para o
mesmo `id` se ele tiver argumentos não vazios, ou se o evento já visto
também não tinha argumentos. Isso preserva a primeira ocorrência "rica"
e ignora ocorrências posteriores vazias, sem nunca perder uma atualização
legítima. Ver `_has_arguments`/`_coerce_arguments` em `chat/service.py` e
o teste de regressão
`tests/integration/test_chat_service.py::test_run_chat_survives_duplicate_completed_event_without_args`,
que reproduz o payload real capturado.

## Concorrência

- Toda a orquestração de rede é `asyncio` nativo (`httpx`, `FastAPI`,
  `uvicorn`).
- As operações de filesystem usadas pelas 3 ferramentas reais são
  chamadas de sistema curtas (`os.open`/`os.lstat`/`os.pread`/etc.) —
  deliberadamente **não** usamos `asyncio.to_thread` para elas, pois o
  overhead de agendamento seria maior que o custo da própria chamada em
  arquivos dentro do tamanho limite configurado; isso é documentado aqui
  como uma decisão explícita, não um descuido.
- Não há estado global mutável compartilhado entre requisições no
  servidor: cada chamada a `run_chat()` cria seu próprio
  `TokenManager`/`MeliGPTClient`.

## Modo passagem direta (`MELIGPT_FILES_DIR=/`)

Cenário real que motivou isso: quando `meligpt serve` roda no mesmo
dispositivo que o cliente (ex.: OpenClaude apontando
`OPENAI_BASE_URL=http://localhost:8080/v1`), o modelo remoto reporta um
cwd "de host" real (ex.: `/tmp/tmp.v2Ugw0ltmU`, o diretório onde o
usuário efetivamente digitou `openclaude`). Com o sandbox padrão, um
`file_path` como `/tmp/tmp.v2Ugw0ltmU/index.js` é tratado como caminho
*virtual* (a barra inicial é a raiz virtual, não a raiz real do SO — ver
seção acima), então o arquivo é gravado dentro do sandbox isolado, nunca
na pasta real onde o usuário está — resultado observado: `write_file`
"funciona" (retorna sucesso), mas o arquivo nunca aparece onde o usuário
espera.

Como o servidor e o cliente estão na mesma máquina, a correção é
literal: se `MELIGPT_FILES_DIR` for exatamente `/`, a resolução de
caminho vigente (`/x` → `x` relativo à raiz) produz `/` + `x` = `x` — ou
seja, o caminho virtual passa a *ser* o caminho real do host, palavra por
palavra. Nenhuma lógica nova de resolução foi necessária; o mesmo
`resolve_secure`/`dir_fd`/`O_NOFOLLOW` que protege o sandbox isolado
continua valendo — a única coisa que muda é *onde* a raiz aponta.

**Isso é uma mudança de modelo de ameaça, não um bug a ser sempre
corrigido por padrão**: um sandbox isolado é o comportamento correto
quando o servidor MeliGPT é remoto de verdade (o caso original do
projeto Bash). Por isso a flag exige confirmação dupla
(`MELIGPT_FILES_DIR=/` **e** `MELIGPT_ALLOW_FULL_FILESYSTEM_ACCESS=true`)
e falha rápido — na criação do app (`create_app`) e no início da CLI, não
apenas na primeira requisição — se só uma das duas estiver presente. A
lista de diretórios excluídos de varreduras recursivas
(`filesystem/exclusions.py`) também foi ampliada para incluir
pseudo-sistemas de arquivo do host (`proc`, `sys`, `dev`, `boot`),
reduzindo o risco de uma varredura recursiva (`ls -r`, `glob`, `grep`)
tentar descer neles quando a raiz é `/`.

## Trade-offs registrados

- **`parallel`/`task` como stubs**: implementar paralelismo/subagentes
  reais exigiria inventar uma política de concorrência, profundidade e
  isolamento que não existe no projeto original. Preferimos deixar a
  interface pronta (`tool_not_implemented`) a arriscar um comportamento
  não solicitado.
- **Servidor HTTP como adição, não substituição**: o CLI continua sendo o
  ponto de entrada padrão do container (`ENTRYPOINT`); `serve` é um
  subcomando explícito.
- **`edit_file` fora do escopo real**: como não há implementação Bash de
  referência, não fizemos engenharia reversa de um comportamento
  inexistente — a interface está pronta para receber uma implementação
  futura (ver `docs/tools.md`).
