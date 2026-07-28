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

## Por que 8 das 11 "ferramentas" pedidas são stubs

O prompt de migração usado nesta tarefa assumia um agente de coding
genérico com 12 ferramentas (`WebSearch`, `ImageGeneration`, `task`,
`edit_file`, `glob`, `grep`, `write_todos`, `parallel`, `ls`, `read_file`,
`write_file`). O projeto Bash real só implementa 3: `ls`, `read_file`,
`write_file` (ver `legacy/local-tools.sh`). Não existe, no projeto
original, nenhuma integração de busca web, geração de imagem, subagentes,
edição de texto em arquivo, glob, grep, lista de tarefas ou execução
paralela.

Decisão registrada aqui (conforme pedido, "se algum comportamento estiver
ambíguo... registre a decisão"): as 8 ferramentas sem contraparte real
foram implementadas como **stubs explícitos** — mesmo nome público, mesmo
lugar no catálogo (`ToolRegistry`), mas sempre respondem
`tool_not_implemented` em vez de fingir um comportamento que não existe.
Isso preserva a superfície de interface pedida sem inventar integrações
não solicitadas pelo dono do projeto. Ver `docs/tools.md`.

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
