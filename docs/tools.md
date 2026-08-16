# Ferramentas

11 ferramentas no catálogo (`tools/registry.py`): **9 reais** (`ls`,
`read_file`, `write_file`, `edit_file`, `glob`, `grep`, `write_todos`,
`WebSearch`, `bash`) e **3 stub** (`parallel`, `task`, `ImageGeneration`
— interface pronta, sem política/provedor definido, ver
`docs/architecture.md`). Note que `bash` é real mas **desligada por
padrão** por segurança — ver seção própria abaixo.

---

## `ls`

**Finalidade:** listar arquivos/diretórios sob a raiz sandbox.

**Entrada:**
```json
{ "path": "/sub/pasta", "recursive": false }
```

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

**Erros:** `not_a_directory`, `permission_denied`, `invalid_path`,
`path_traversal`, `symlink_not_allowed`. **Limite:**
`MELIGPT_MAX_LS_RESULTS` (default 1000).

---

## `read_file`

**Finalidade:** ler o conteúdo textual de um arquivo.

**Entrada:**
```json
{ "file_path": "/relatorio.md", "offset": 0, "limit": 4096 }
```
`offset`/`limit` são opcionais.

**Saída:**
```json
{ "success": true, "content": "...", "size": 4531, "path": "/relatorio.md", "truncated": false }
```

**Erros:** `file_not_found`, `not_a_file`, `binary_file`, `file_too_large`,
`permission_denied`, `path_traversal`, `symlink_not_allowed`,
`invalid_path`. **Limite:** `MELIGPT_MAX_FILE_SIZE` (default 1 MiB) quando
`offset`/`limit` não são informados.

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

**Erros:** `file_too_large`, `tool_validation_error`,
`symlink_not_allowed`, `path_traversal`, `tool_execution_error` (o
arquivo original nunca é corrompido). **Limite:** `MELIGPT_MAX_FILE_SIZE`.

**Cria diretórios intermediários automaticamente** (como `mkdir -p`,
sempre dentro da raiz sandbox): se o modelo remoto mandar
`/tmp/tmp.xxxx/index.js` (refletindo um cwd "de host" que o cliente
informou a ele), as pastas `tmp/tmp.xxxx` são criadas na raiz virtual
antes de gravar o arquivo — sem isso, toda escrita em subpasta ainda não
existente falhava com "caminho local não encontrado".

---

## `edit_file`

**Finalidade:** substituir um trecho de texto exato por outro, sem
reescrever o arquivo inteiro.

**Entrada:**
```json
{
  "file_path": "/app.py",
  "old_string": "def foo():",
  "new_string": "def bar():",
  "replace_all": false
}
```
- `replace_all` (opcional, default `false`): sem ele, o texto precisa
  aparecer **exatamente uma vez** — mais de uma ocorrência é erro
  (`ambiguous_match`), evitando editar o trecho errado por engano.

**Saída:**
```json
{
  "success": true,
  "content": "editado localmente: /app.py (1 substituição(ões))",
  "path": "/app.py",
  "replacements": 1
}
```

**Erros:** `text_not_found` (o `old_string` não existe no arquivo),
`ambiguous_match` (aparece mais de uma vez sem `replace_all`),
`file_not_found`, `not_a_file`, `binary_file`, `symlink_not_allowed`,
`path_traversal`. Reaproveita a mesma escrita atômica de `write_file`
(`filesystem/atomic_io.py`) — uma falha no meio do processo nunca deixa o
arquivo original corrompido.

---

## `glob`

**Finalidade:** buscar arquivos por padrão (`**/*.java`, `src/*.py`
etc.).

**Entrada:**
```json
{ "pattern": "**/*.java", "path": "/src" }
```
`path` (opcional, default `/`): restringe a busca a uma subpasta.

**Saída:**
```json
{
  "success": true,
  "pattern": "**/*.java",
  "truncated": false,
  "matches": ["/src/Main.java", "/src/util/Helper.java"]
}
```

Suporta `**` (qualquer profundidade), `*`, `?` e `[...]`. Nunca segue
symlinks, nunca escapa a raiz sandbox. **Limite:**
`MELIGPT_MAX_GLOB_RESULTS` (default 1000), resultados ordenados
deterministicamente.

---

## `grep`

**Finalidade:** pesquisar texto (literal ou regex) dentro dos arquivos.

**Entrada:**
```json
{ "pattern": "TODO", "regex": false, "case_sensitive": true, "path": "/src" }
```

**Saída:**
```json
{
  "success": true,
  "pattern": "TODO",
  "files_scanned": 12,
  "truncated": false,
  "matches": [
    {"path": "/src/main.py", "line": 42, "text": "# TODO: revisar isso"}
  ]
}
```

**Erros:** `tool_validation_error` (regex inválida ou `pattern`
ausente), `not_a_directory`, `path_traversal`. Arquivos binários são
pulados silenciosamente (não geram erro, só ficam de fora do resultado).
**Limites:** `MELIGPT_MAX_GREP_RESULTS` (default 500) e
`MELIGPT_MAX_GREP_BYTES_PER_FILE` (default 1 MiB por arquivo).

---

## `write_todos`

**Finalidade:** manter uma lista estruturada de tarefas da sessão.

**Entrada:** cada chamada substitui a lista inteira.
```json
{
  "todos": [
    {"id": "t1", "content": "escrever testes", "status": "in_progress"},
    {"content": "revisar docs", "status": "pending"}
  ]
}
```
- `status` ∈ `pending` | `in_progress` | `completed`.
- No máximo **uma** tarefa pode estar `in_progress` por vez.
- `id` é opcional (gerado automaticamente se ausente).

**Saída:**
```json
{
  "success": true,
  "content": "lista de tarefas atualizada: [in_progress] escrever testes, [pending] revisar docs",
  "todos": [ ... ]
}
```

Persistida em `<config_dir>/todos.json`, gravação atômica. **Erros:**
`tool_validation_error` (status inválido, mais de uma tarefa
`in_progress`, `content` ausente).

---

## `WebSearch`

**Finalidade:** pesquisar a web e retornar resultados estruturados.

**Entrada:**
```json
{ "query": "python asyncio best practices" }
```

**Saída:**
```json
{
  "success": true,
  "query": "python asyncio best practices",
  "results": [
    {"title": "...", "url": "https://...", "snippet": "..."}
  ]
}
```

**Provedor:** Brave Search API (`MELIGPT_WEB_SEARCH_PROVIDER=brave`,
default). Precisa de `MELIGPT_BRAVE_API_KEY` (tier gratuito disponível em
https://brave.com/search/api/). Sem a chave configurada, retorna
`web_search_not_configured` — um erro estruturado e explícito, não um
`tool_not_implemented` genérico.

**Alternativa nativa (experimental, não testada ao vivo):**
`MELIGPT_ENABLE_BROWSING=true` liga o campo `browsing` que o próprio
payload do MeliGPT já expõe (visto no HAR, sempre `false` no client
original) — se o backend suportar esse plugin nativo (o formato do
payload sugere LibreChat), o modelo remoto passa a pesquisar a web
sozinho, sem precisar desta ferramenta local. Como não consigo validar
isso contra o backend real, trate como experimental e teste com cuidado.

## `bash`

**Finalidade:** executar um comando de shell dentro da raiz sandbox.

> ⚠️ **Desligada por padrão** (`MELIGPT_ENABLE_BASH_TOOL=false`). Ao
> contrário das outras ferramentas, `bash` não tem sandbox de caminho —
> é execução de comando real, com o mesmo poder de qualquer processo
> rodando no container. A fronteira de segurança é o isolamento do
> próprio Docker (usuário não-root, filesystem read-only fora de
> `/data` — ver `Dockerfile`). **Só ative isso rodando dentro de um
> container assim.** Fora de um container isolado, ligar essa
> ferramenta equivale a dar acesso de shell ao host onde o
> `meligpt serve` está rodando.

**Entrada:**
```json
{ "command": "ls -la && cat package.json" }
```

**Saída:**
```json
{
  "success": true,
  "content": "$ ls -la && cat package.json\n(exit code: 0)\n...",
  "exit_code": 0,
  "stdout": "...",
  "stderr": "",
  "stdout_truncated": false,
  "stderr_truncated": false
}
```

`success: true` significa apenas que o comando **executou** — o
resultado real está em `exit_code` (o modelo decide o que fazer com um
exit code != 0, igual um agente de terminal normal faria).

**Erros:** `tool_disabled` (ferramenta desligada — a mensagem já explica
como ativar), `tool_validation_error` (`command` ausente),
`tool_execution_error` (timeout ou falha ao iniciar o processo).
**Limites:** `MELIGPT_BASH_TIMEOUT_SECONDS` (default 30s, mata o processo
ao estourar) e `MELIGPT_BASH_MAX_OUTPUT_BYTES` (default 200000, por
stream).

## `parallel` — *não implementado*

Executaria ferramentas independentes concorrentemente. O executor
original processa uma tool call por vez; implementar de verdade exigiria
definir do zero uma política de concorrência/cancelamento que não existe
em nenhuma referência do projeto. Sempre retorna `tool_not_implemented`.

## `task` — *não implementado*

Delegaria uma tarefa isolada a um subagente (contexto isolado, limite de
profundidade). Sem conceito de subagente em nenhuma parte do projeto
original. Sempre retorna `tool_not_implemented`.

## `ImageGeneration` — tool_call client-side *não implementado*, mas geração de imagem funciona

A geração de imagem em si acontece do lado do MeliGPT remoto, não como
algo que o cliente precisa executar. Quando o modelo gera uma imagem, o
link `/api/media/{userId}/{filename}` (rota confirmada por HAR) aparece
no texto da resposta, e `chat/service.py` já baixa e salva isso
automaticamente em `generated-images/` — ver seção "Geração de imagens"
do README e `src/meligpt/media.py`. Esta ferramenta stub só existe para
o caso (não confirmado por HAR) de o modelo também emitir um tool_call
`ImageGeneration` separado esperando uma resposta client-side; se isso
acontecer, o turno mostra "ferramenta não espelhada: ImageGeneration"
como aviso informativo — o download da imagem (se houver) já terá
acontecido de qualquer forma. Sempre retorna `tool_not_implemented` se
alguém tentar chamá-la diretamente como ferramenta client-side.

---

## Contrato de erro comum

Toda ferramenta, real ou stub, retorna em caso de falha:

```json
{ "success": false, "error": "mensagem legível", "code": "codigo_estavel" }
```

`code` é a interface estável para integrações programáticas; `error` é
para humanos e pode mudar de texto entre versões.
