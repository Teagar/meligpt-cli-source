# Migração Bash → Python

## Correspondência de arquivos

| Bash (`legacy/`) | Python | Situação |
|---|---|---|
| `chat-api.sh` (parsing de argumentos, loop principal) | `cli.py` | migrado |
| `chat-api.sh` (montagem do payload/headers, `curl`, leitura do SSE) | `clients/meligpt_http.py` | migrado |
| `chat-api.sh` (parsing dos eventos `on_message_delta`/`on_run_step_completed`) | `chat/events.py` | migrado |
| `chat-api.sh` (extração de hints de arquivo/pasta do prompt) | `chat/prompt_builder.py` | migrado |
| `chat-api.sh` (orquestração: montar contexto, enviar, espelhar tool calls, tratar 401) | `chat/service.py` | migrado |
| `local-tools.sh` (`resolve_path`) | `filesystem/paths.py` + `filesystem/security.py` | migrado e reforçado (dir_fd/O_NOFOLLOW) |
| `local-tools.sh` (case `ls`/`list_files`) | `tools/files/ls.py` | migrado |
| `local-tools.sh` (case `read_file`) | `tools/files/read_file.py` | migrado (+ offset/limit opcionais) |
| `local-tools.sh` (case `write_file`) | `tools/files/write_file.py` | migrado (+ escrita atômica via `dir_fd`) |
| `local-file-discovery.sh` | `filesystem/discovery.py` | migrado |
| `local-file-context.sh` | `filesystem/context.py` | migrado (+ escaping XML de path/conteúdo) |
| `importar-har.sh` | `auth/har_importer.py` + comando `meligpt import-har` | migrado |
| `secrets.env` (formato) | `auth/secrets.py` | mantido o mesmo formato (`ACCESS_TOKEN`, `COOKIE_HEADER`) |
| — (não existia) | `api/` (servidor HTTP/SSE) | **novo**, pedido explicitamente nesta migração |
| — (não existia) | `edit_file`, `glob`, `grep`, `write_todos` (implementados de verdade) | **novo, adicionado depois** — operações locais sem depender de nenhum provedor externo, ver `docs/tools.md` |
| — (não existia) | `catalog.py` (catálogo de modelos multi-provedor) + `GET /v1/models`, `/v1/models/{id}`, `/v1/providers`, `meligpt models`/`meligpt providers`, `--model`/`--endpoint` na CLI e em `/v1/chat`/`/v1/chat/completions` | **novo, adicionado depois** — sem contraparte no Bash original |
| — (não existia) | `media.py` (detecção/download de imagens geradas via `/api/media/...`, confirmado por HAR) + evento `generated_image` em `/v1/chat` e markdown embutido em `/v1/chat/completions` | **novo, adicionado depois** — sem contraparte no Bash original |
| — (não existia) | `WebSearch` (implementada de verdade, `tools/research/web_search.py`) | **novo, adicionado depois** — sem contraparte no Bash original |
| — (não existia) | `tools/stubs/*` (`parallel`, `task`, `ImageGeneration` como tool_call client-side — a geração de imagem em si já funciona via `media.py`, ver `docs/tools.md`) | continuam sem implementação client-side — exigiriam política de subagentes ou schema de tool_call não confirmado por HAR |

## Itens legados (mantidos em `legacy/`)

Todos os 5 scripts Bash originais e o `README.md` original foram
preservados em `legacy/` durante a transição. Eles não são mais chamados
pelo código Python (não há adaptador Bash→Python nesta versão, pois as 3
ferramentas reais foram totalmente reescritas nativamente). Podem ser
removidos quando você confirmar que a versão Python atende seu uso diário.

## Diferenças de comportamento conhecidas

| Diferença | Motivo | Compatível? |
|---|---|---|
| Symlinks apontando **para dentro** da própria raiz sandbox agora são sempre bloqueados | O Bash original também bloqueava (`[[ ! -L $current ]]`); a política foi apenas tornada explícita e testada — não é uma mudança de comportamento observável. | Sim |
| `read_file` aceita `offset`/`limit` opcionais | Pedido explícito do prompt de migração (seção 4.5); omitir os dois reproduz exatamente o comportamento antigo (lê o arquivo inteiro, respeitando o limite de tamanho). | Sim, aditivo |
| Servidor HTTP/SSE (`meligpt serve`) | Não existia no Bash; pedido explicitamente nesta migração. | Novo, não substitui a CLI |
| `edit_file`, `glob`, `grep`, `write_todos` agora funcionam de verdade (antes eram stub) | Uso real com OpenClaude mostrou que o modelo remoto já chama essas ferramentas espontaneamente | Ferramentas novas, sem regressão — mesma segurança de filesystem das originais |
| `parallel`, `task`, `ImageGeneration` (como tool_call client-side) continuam retornando `tool_not_implemented` | Sem contraparte no Bash original e sem provedor/política/schema definidos; ver `docs/tools.md` — a geração de imagem em si funciona via `media.py`, sem depender desta ferramenta | Sem regressão — apenas não fazem nada ainda |
| Mensagens de erro em português, com `code` estável em inglês (`snake_case`) | Facilita internacionalização futura sem quebrar clientes que só olham `code`. | O *campo* `code` é a interface estável, não o texto de `error` |

## Correções pós-lançamento

| Data | Bug | Correção |
|---|---|---|
| 2026-08-10 | Com `MELIGPT_FILES_DIR=/` (modo de acesso total ao filesystem, usado para deixar o OpenClaude editar/criar arquivos reais), baixar uma imagem gerada falhava com `falha ao salvar imagem gerada: não foi possível criar diretório intermediário: generated-images/...` — a pasta de mídia tentava se criar sob a raiz real do filesystem (`/generated-images`), que exige permissão de root. Encontrado via teste end-to-end real com `openclaude -p`. | `Settings.resolved_media_dir()` (nova, default `config_dir/generated-images`) é agora sempre independente de `files_dir` — nunca tenta gravar sob a raiz do filesystem. Ver `tests/integration/test_chat_service.py::test_run_chat_downloads_generated_image_with_full_filesystem_access` (regressão exata do bug) e `tests/unit/test_full_filesystem_guard.py::test_media_dir_independent_of_root_files_dir`. |

## Recursos adicionados depois do lançamento inicial

| Data | O quê | Onde |
|---|---|---|
| 2026-08-10 | `GeneratedImage` renomeado para `GeneratedMedia` (campo `media_type`: `image`/`video`/`other`, inferido pela extensão) — o mecanismo de download já era agnóstico de extensão, só faltava deixar de nomear tudo como "imagem". | `chat/service.py`, `media.py` |
| 2026-08-10 | `media_dir` — escolher onde salvar mídia gerada num turno específico (`--media-dir` na CLI, campo `media_dir` em `/v1/chat` e `/v1/chat/completions`). Sem isso, usa o destino padrão (`Settings.resolved_media_dir()`). | `chat/service.py:run_chat`, `cli.py`, `api/routes.py`, `api/openai_compat.py` |
| 2026-08-10 | 4 modelos de vídeo adicionados ao catálogo local (`sora-2`, `veo-3.1-generate`, `veo-3.1-fast-generate`, `happyhorse-1.0`) — nomes de exibição confirmados pelo usuário, **ids inferidos** (não confirmados por HAR). `resolve_model()` ganhou `require_type=None` para `meligpt chat`/`POST /v1/chat` aceitarem modelos de vídeo/imagem. | `catalog.py` |
| 2026-08-10 | Correção: `/v1/chat/completions` inicialmente bloqueava modelos não-`chat` (`400 model_type_not_supported`) — mas é o ÚNICO endpoint que clientes OpenAI-compatible como o OpenClaude falam, então isso deixava vídeo/imagem inacessíveis na prática (reproduzido: `openclaude` com `/model sora-2` pedindo vídeo retornava esse erro). Removida a restrição — aceita qualquer tipo de modelo agora, igual `/v1/chat`. Ver `tests/integration/test_openai_compat.py::test_openai_chat_completions_generates_video_end_to_end`. | `api/openai_compat.py` |

## Plano de rollback

1. Pare o serviço/processo Python.
2. Use diretamente os scripts em `legacy/` (`chat-api.sh`, etc.) — eles
   continuam funcionais e usam o mesmo `secrets.env`/`files/` (formatos
   preservados).
3. Nenhuma migração de dados é necessária: `secrets.env` e a árvore
   `files/` são lidos e escritos no mesmo formato pelas duas versões.

## Instruções de atualização

```bash
git pull
pip install -e ".[dev]" --upgrade
# secrets.env e a pasta files/ não precisam de nenhuma conversão
meligpt "teste rápido para confirmar que continua funcionando"
```
