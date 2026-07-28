# Ferramentas

11 ferramentas no catálogo (`tools/registry.py`): 3 reais (com contraparte
funcional no Bash original) e 8 "stub" (interface pronta, sem provedor —
ver `docs/architecture.md` para a justificativa de não terem sido
inventadas).

---

## `ls`

**Finalidade:** listar arquivos/diretórios sob a raiz sandbox.

**Entrada:**
```json
{ "path": "/sub/pasta", "recursive": false }
```
- `path` (opcional, default `"/"`): caminho virtual do diretório.
- `recursive` (opcional, default `false`).

**Saída:**
```json
{
  "success": true,
  "path": "/sub/pasta",
  "recursive": false,
  "truncated": false,
  "entries": [
    {"name": "a.txt", "path": "/sub/pasta/a.txt", "type": "file", "size": 123},
    {"name": "docs", "path": "/sub/pasta/docs", "type": "directory", "size": 0}
  ]
}
```

**Erros possíveis:** `not_a_directory`, `permission_denied`,
`invalid_path`, `path_traversal`, `symlink_not_allowed`.

**Limites:** `MELIGPT_MAX_LS_RESULTS` (default 1000) — resultados além
disso vêm com `"truncated": true`.

---

## `read_file`

**Finalidade:** ler o conteúdo textual de um arquivo.

**Entrada:**
```json
{ "file_path": "/relatorio.md", "offset": 0, "limit": 4096 }
```
- `file_path` (obrigatório).
- `offset`, `limit` (opcionais — omitir os dois reproduz o comportamento
  do Bash original: lê o arquivo inteiro, respeitando o limite de
  tamanho).

**Saída:**
```json
{
  "success": true,
  "content": "...",
  "size": 4531,
  "path": "/relatorio.md",
  "truncated": false
}
```

**Erros possíveis:** `file_not_found`, `not_a_file`, `binary_file`,
`file_too_large`, `permission_denied`, `path_traversal`,
`symlink_not_allowed`, `invalid_path`.

**Limites:** `MELIGPT_MAX_FILE_SIZE` (default 1 MiB) quando `offset`/`limit`
não são informados.

---

## `write_file`

**Finalidade:** gravar conteúdo textual em um arquivo (criação atômica).

**Entrada:**
```json
{ "file_path": "/saida.txt", "content": "texto exato\n" }
```

**Saída:**
```json
{ "success": true, "content": "gravado localmente: /saida.txt" }
```

**Erros possíveis:** `file_too_large`, `tool_validation_error` (conteúdo
ausente, ou tentativa de gravar na raiz/num diretório existente),
`symlink_not_allowed`, `path_traversal`, `tool_execution_error` (falha de
E/S durante a escrita atômica — o arquivo original nunca é corrompido).

**Limites:** `MELIGPT_MAX_FILE_SIZE`.

---

## `edit_file` — *não implementado*

Substituiria texto exato em um arquivo (única ocorrência ou todas).
**Sem contraparte no Bash original.** Sempre retorna:
```json
{ "success": false, "error": "...", "code": "tool_not_implemented" }
```
Para implementar: reaproveitar `filesystem/security.py` para
resolução/segurança e a escrita atômica de `tools/files/write_file.py`;
detectar ambiguidade contando ocorrências antes de substituir.

## `glob` — *não implementado*

Buscaria arquivos por padrão (`**/*.java`). Sem contraparte no Bash
original. Mesma resposta `tool_not_implemented`.

## `grep` — *não implementado*

Pesquisaria texto/regex dentro dos arquivos autorizados. Sem contraparte
no Bash original. Mesma resposta `tool_not_implemented`.

## `write_todos` — *não implementado*

Manteria uma lista estruturada de tarefas (`pending`/`in_progress`/
`completed`). Sem contraparte no Bash original. Mesma resposta
`tool_not_implemented`.

## `parallel` — *não implementado*

Executaria ferramentas independentes concorrentemente. O executor Bash
original processa uma tool call por vez; não há orquestração paralela a
migrar. Mesma resposta `tool_not_implemented`.

## `task` — *não implementado*

Delegaria uma tarefa isolada a um subagente. Sem contraparte no Bash
original (não há conceito de subagente). Mesma resposta
`tool_not_implemented`.

## `WebSearch` — *não implementado*

Pesquisaria a web via provedor externo configurável. **Nenhum provedor de
busca está integrado ao MeliGPT original** — implementar exigiria uma
decisão de produto (qual provedor, quais credenciais) que não cabe a esta
migração inventar. Mesma resposta `tool_not_implemented`. Para habilitar:
implemente `clients/web_search.py` e configure
`MELIGPT_WEB_SEARCH_PROVIDER` em `config.py`.

## `ImageGeneration` — *não implementado*

Geraria/editaria imagens via provedor externo configurável. Mesma
observação de `WebSearch`: nenhum provedor está integrado ao projeto
original. Mesma resposta `tool_not_implemented`.

---

## Contrato de erro comum

Toda ferramenta, real ou stub, retorna em caso de falha:

```json
{ "success": false, "error": "mensagem legível", "code": "codigo_estavel" }
```

`code` é a interface estável para integrações programáticas; `error` é
para humanos e pode mudar de texto entre versões.
