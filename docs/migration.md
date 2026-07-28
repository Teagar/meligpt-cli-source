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
| — (não existia) | `tools/stubs/*` (8 ferramentas) | **novo catálogo de interface**, sem provedor real — ver `docs/tools.md` |

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
| 8 ferramentas (`edit_file`, `glob`, `grep`, `write_todos`, `parallel`, `task`, `WebSearch`, `ImageGeneration`) retornam `tool_not_implemented` | Não existiam no Bash original; ver `docs/tools.md`. | Ferramentas novas, sem regressão — apenas não fazem nada ainda |
| Mensagens de erro em português, com `code` estável em inglês (`snake_case`) | Facilita internacionalização futura sem quebrar clientes que só olham `code`. | O *campo* `code` é a interface estável, não o texto de `error` |

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
