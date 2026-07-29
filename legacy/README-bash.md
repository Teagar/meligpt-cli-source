# MeliGPT CLI

Cliente de linha de comando não oficial para enviar mensagens ao MeliGPT diretamente pelo terminal no Arch Linux.

O script realiza uma requisição HTTP para a API, processa a resposta em formato **Server-Sent Events (SSE)** e exibe os fragmentos de texto em tempo real.

> [!WARNING]
> Este projeto utiliza credenciais de uma sessão autenticada. Não publique tokens, cookies, arquivos HAR ou o arquivo `secrets.env`. Use-o somente com uma conta e um serviço aos quais você tenha acesso autorizado.

## Funcionalidades

- Envio de prompts diretamente pelo terminal
- Exibição da resposta em tempo real
- Processamento de eventos SSE
- Leitura segura das credenciais em arquivo separado
- Compatibilidade com Bash e Zsh
- Possibilidade de instalação como comando global `meligpt`

## Requisitos

- Linux
- Bash
- [`curl`](https://curl.se/)
- [`jq`](https://jqlang.github.io/jq/)

No Arch Linux:

```bash
sudo pacman -S --needed bash curl jq
```

## Estrutura do projeto

```text
~/.config/meligpt-cli/
├── chat-api.sh
└── secrets.env
```

Permissões recomendadas:

```text
~/.config/meligpt-cli/          700
chat-api.sh                     700
secrets.env                     600
```

## Instalação

Crie o diretório de configuração:

```bash
install -d -m 700 ~/.config/meligpt-cli
```

Copie o script para o diretório:

```bash
cp chat-api.sh ~/.config/meligpt-cli/chat-api.sh
chmod 700 ~/.config/meligpt-cli/chat-api.sh
```

## Configuração das credenciais

Crie o arquivo:

```bash
nano ~/.config/meligpt-cli/secrets.env
```

Use este modelo, substituindo os valores apenas localmente:

```bash
export ACCESS_TOKEN='SEU_ACCESS_TOKEN'
export COOKIE_HEADER='SEU_COOKIE_HEADER_COMPLETO'
```

Proteja o arquivo:

```bash
chmod 600 ~/.config/meligpt-cli/secrets.env
```

### Como obter credenciais válidas

1. Entre no MeliGPT pelo navegador.
2. Confirme que consegue enviar uma mensagem pela interface.
3. Abra as ferramentas de desenvolvimento.
4. Acesse a aba **Rede/Network**.
5. Envie uma mensagem.
6. Localize a requisição:

   ```text
   POST /api/ask/openAI
   ```

7. Use os valores de `Authorization` e `Cookie` da requisição válida.

No arquivo `secrets.env`:

- remova o prefixo `Bearer` do valor de `ACCESS_TOKEN`;
- mantenha o valor completo do header `Cookie` em `COOKIE_HEADER`.

Exemplo conceitual:

```text
Authorization: Bearer eyJ...
Cookie: cookie_a=...; cookie_b=...
```

Transforma-se em:

```bash
export ACCESS_TOKEN='eyJ...'
export COOKIE_HEADER='cookie_a=...; cookie_b=...'
```

> Nunca inclua credenciais reais no código, no README, em commits, em issues ou em mensagens públicas.

## Uso

Execute o script passando o prompt como argumento:

```bash
~/.config/meligpt-cli/chat-api.sh \
  'Responda apenas: teste recebido'
```

Exemplo de saída:

```text
Enviando mensagem...
IA:
teste recebido
```

Argumentos com várias palavras devem estar entre aspas:

```bash
~/.config/meligpt-cli/chat-api.sh \
  'Explique o que é Server-Sent Events em três tópicos.'
```

## Instalar como comando global

Crie um link simbólico em `~/.local/bin`:

```bash
mkdir -p ~/.local/bin

ln -sf \
  ~/.config/meligpt-cli/chat-api.sh \
  ~/.local/bin/meligpt
```

Adicione o diretório ao `PATH` no Zsh:

```bash
grep -qxF 'export PATH="$HOME/.local/bin:$PATH"' ~/.zshrc ||
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc

source ~/.zshrc
```

Para Bash, use `~/.bashrc`:

```bash
grep -qxF 'export PATH="$HOME/.local/bin:$PATH"' ~/.bashrc ||
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

source ~/.bashrc
```

Depois disso:

```bash
meligpt 'Responda apenas: funcionando'
```

## Importar credenciais de um HAR

Um arquivo HAR pode conter senhas, tokens, cookies, dados pessoais e conteúdo das conversas. Ele deve ser processado somente localmente e excluído quando não for mais necessário.

Instale o `jq`:

```bash
sudo pacman -S --needed jq
```

Execute o importador local já configurado:

```bash
bash ~/importar-har.sh
```

Arraste para o terminal um HAR recém-exportado contendo uma requisição bem-sucedida para:

```text
POST https://public-meligpt.adminml.com/api/ask/openAI
```

O importador deve procurar uma resposta HTTP `200` e salvar as credenciais em:

```text
~/.config/meligpt-cli/secrets.env
```

Depois de confirmar o funcionamento, remova o HAR com segurança adequada ao seu ambiente.

## Segurança

### Não versionar segredos

Adicione ao `.gitignore`:

```gitignore
secrets.env
*.har
*.log
headers.txt
stream.txt
.env
.env.*
```

Se o projeto estiver dentro do diretório de configuração, confirme antes de fazer commit:

```bash
git status
git diff --cached
```

Procure possíveis segredos:

```bash
grep -RInE \
  'ACCESS_TOKEN|COOKIE_HEADER|Authorization:|Bearer |refreshToken|tigerToken' \
  . \
  --exclude='README.md' \
  --exclude='.gitignore'
```

### Permissões

Aplique as permissões recomendadas:

```bash
chmod 700 ~/.config/meligpt-cli
chmod 700 ~/.config/meligpt-cli/chat-api.sh
chmod 600 ~/.config/meligpt-cli/secrets.env
```

Confira:

```bash
stat -c '%A %a %n' \
  ~/.config/meligpt-cli \
  ~/.config/meligpt-cli/chat-api.sh \
  ~/.config/meligpt-cli/secrets.env
```

### Credenciais expostas

Se um token, cookie ou HAR for publicado acidentalmente:

1. encerre a sessão correspondente;
2. renove as credenciais;
3. gere um novo token;
4. substitua o `secrets.env`;
5. remova o segredo do histórico do Git, se aplicável.

Apagar apenas o arquivo no último commit não remove o segredo de commits anteriores.

## Solução de problemas

### HTTP 401 — Unauthorized

Possíveis causas:

- token expirado;
- token copiado incorretamente;
- prefixo `Bearer` mantido dentro de `ACCESS_TOKEN`;
- token e cookies obtidos de sessões diferentes.

Solução:

1. renove a sessão no navegador;
2. confirme que a interface web funciona;
3. capture uma nova requisição bem-sucedida;
4. atualize o `secrets.env`.

### HTTP 403 — Forbidden

Se a resposta vier como HTML do CloudFront ou WAF, a requisição provavelmente foi bloqueada antes de chegar à API.

Possíveis causas:

- sessão inválida;
- conta restrita;
- token e cookies incompatíveis;
- política de rede;
- bloqueio do serviço;
- headers obrigatórios ausentes.

Não tente contornar restrições de conta, rede ou serviço. Confirme o acesso pela interface oficial e consulte o suporte ou a equipe responsável quando necessário.

### `jq: command not found`

Instale o pacote:

```bash
sudo pacman -S --needed jq
```

### `curl: command not found`

Instale o pacote:

```bash
sudo pacman -S --needed curl
```

### `Permission denied`

Torne o script executável:

```bash
chmod 700 ~/.config/meligpt-cli/chat-api.sh
```

### `secrets.env` não encontrado

Confira se o arquivo existe:

```bash
ls -l ~/.config/meligpt-cli/secrets.env
```

Crie-o novamente se necessário e aplique:

```bash
chmod 600 ~/.config/meligpt-cli/secrets.env
```

### A resposta chega, mas nenhum texto aparece

A API pode ter alterado o formato dos eventos SSE. Ative o modo de diagnóstico do script, caso implementado, e verifique o stream sem publicar seu conteúdo.

Tenha cuidado: logs podem conter prompts, respostas e informações sensíveis.

## Atualização das credenciais

Tokens de acesso são temporários. Quando expirarem:

1. autentique-se novamente no navegador;
2. envie uma mensagem pela interface;
3. capture uma requisição HTTP `200`;
4. atualize `ACCESS_TOKEN` e `COOKIE_HEADER`;
5. teste o cliente novamente.

Teste rápido:

```bash
meligpt 'Responda apenas: credenciais válidas'
```

## Limitações

- Depende de um endpoint não documentado publicamente.
- Mudanças no formato da API ou do SSE podem quebrar o script.
- Tokens e cookies expiram.
- Acesso depende das permissões da conta.
- O projeto não substitui uma API ou SDK oficial.
- Não há garantia de estabilidade ou compatibilidade futura.

## Aviso

Este é um projeto não oficial, sem associação ou suporte do Mercado Livre, MeliGPT ou de seus mantenedores.

Use apenas em ambientes autorizados e respeite:

- as políticas internas da organização;
- os termos do serviço;
- as regras de segurança da informação;
- as permissões da sua conta;
- a legislação aplicável.

## Licença

Adicione a licença adequada ao projeto antes de redistribuí-lo. Para um projeto aberto e simples, uma opção comum é a licença MIT.
