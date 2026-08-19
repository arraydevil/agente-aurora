# Implantação na Vercel

Guia para publicar a Aurora com URL HTTPS pública. É o caminho mais curto: a
Vercel importa o repositório do GitHub, instala as dependências e publica.
**Não exige cartão de crédito nem instalar nada na sua máquina.**

Tempo estimado: **5 a 10 minutos**.

---

## Como funciona

A Vercel tem detecção nativa de FastAPI: ela procura uma instância chamada `app`
em entrypoints conhecidos — `main.py`, `app.py`, `index.py`, `server.py`,
`asgi.py`, `wsgi.py`, na raiz ou dentro de `src/` e `app/`.

O projeto já satisfaz isso: `app/main.py` expõe `app = FastAPI(...)`. **Não é
preciso arquivo de adaptação nem rewrite.** A aplicação inteira vira uma única
Vercel Function que atende todas as rotas.

```
vercel.json      maxDuration e includeFiles da função
app/main.py      entrypoint detectado automaticamente
dados/           PDF e CSVs, empacotados pela chave includeFiles
web/index.html   interface de chat, servida pela própria aplicação
```

O `vercel.json` é curto de propósito:

```json
{
  "functions": {
    "app/main.py": {
      "maxDuration": 60,
      "includeFiles": "{dados,web}/**"
    }
  }
}
```

> A chave de `functions` precisa ser o **caminho do entrypoint resolvido**
> (`app/main.py`), não um caminho genérico.

---

## Passo a passo

### 1. Importar o repositório

Acesse <https://vercel.com/new> e faça login com o **GitHub**.

Na lista de repositórios, encontre `agente-aurora` e clique em **Import**.
Se ele não aparecer, clique em **Adjust GitHub App Permissions** e libere o
acesso a esse repositório.

### 2. Configurar

Na tela de configuração, **não mude Framework Preset, Build Command nem Output
Directory**. A Vercel lê o `vercel.json` do repositório.

Expanda **Environment Variables** e adicione:

| Name | Value |
|---|---|
| `GROQ_API_KEY` | sua chave `gsk_...` |

Opcionalmente, para fixar o modelo:

| Name | Value |
|---|---|
| `GROQ_MODEL` | `openai/gpt-oss-120b` |

> A chave não está no repositório de propósito. Segredo nunca é versionado.

### 3. Publicar

Clique em **Deploy** e aguarde de 1 a 3 minutos.

Ao final, a Vercel mostra a URL, no formato
`https://agente-aurora.vercel.app`.

---

## Verificar

```bash
curl https://SUA-URL.vercel.app/api/saude
```

Esperado:

```json
{
  "estado": "ok",
  "trechos_indexados": 208,
  "documentos": {
    "politicas_lumina.pdf": 32,
    "catalogo_produtos.csv": 44,
    "glossario_ingredientes.csv": 132
  },
  "provedores_llm": [
    {"provedor": "groq", "configurado": true},
    {"provedor": "gemini", "configurado": false},
    {"provedor": "extrativo", "configurado": true}
  ]
}
```

Uma pergunta de ponta a ponta:

```bash
curl -X POST https://SUA-URL.vercel.app/api/perguntar \
  -H "Content-Type: application/json" \
  -d '{"pergunta": "A partir de quanto o frete é grátis?"}'
```

Confirme que vem `"provedor": "groq"`. Se vier `"extrativo"`, a chave não chegou
ao ambiente — o campo `tentativas` da resposta diz o motivo exato.

---

## Atualizar

Cada `git push` na branch `main` republica automaticamente. Não há passo manual.

---

## Solução de problemas

**`{"detail":"Not Found"}` na raiz do site.**
Esse 404 vem do próprio FastAPI, o que significa que a função subiu e o problema
é de rota. Quase sempre é um `rewrite` no `vercel.json` apontando para um caminho
que a aplicação não conhece. Com a detecção nativa de FastAPI **não deve existir
nenhum rewrite**: a Vercel entrega a rota original para a aplicação.

**Erro 500 e log dizendo `FileNotFoundError` em `dados/`.**
A chave `includeFiles` do `vercel.json` é o que empacota os documentos junto da
função. Confirme que o `vercel.json` foi enviado ao repositório e que o padrão
`{dados,web}/**` está intacto.

**A primeira visita demora alguns segundos.**
É o *cold start*: a função sobe, lê o PDF e monta o índice BM25 dos 208 trechos.
As requisições seguintes ficam em milissegundos, até a função hibernar de novo.

**`"provedor": "extrativo"` em toda resposta.**
Nenhum LLM respondeu. As causas usuais são `GROQ_API_KEY` ausente no ambiente da
Vercel, ou modelo descontinuado — a Groq aposenta modelos com frequência e a
chamada devolve 404. Liste os ativos da sua conta:

```bash
curl -H "Authorization: Bearer $GROQ_API_KEY" https://api.groq.com/openai/v1/models
```

E ajuste `GROQ_MODEL` em *Settings → Environment Variables*. Depois de alterar
variável, é preciso **Redeploy** para valer.

**Erro 504 por tempo esgotado.**
O `vercel.json` define `maxDuration: 60`. Se a Groq estiver em limite de taxa e
todas as repetições falharem, a requisição pode encostar nesse teto. Configurar
também `GEMINI_API_KEY` dá um segundo degrau à cascata.

---

## Outras plataformas

O projeto não depende da Vercel. Os mesmos arquivos rodam em:

- **Docker**, em qualquer lugar — `docs/deploy-aws.md` e o `Dockerfile`
- **AWS App Runner** — `apprunner.yaml`, veja [`deploy-aws.md`](deploy-aws.md)
- **Oracle Cloud** — [`deploy-oci.md`](deploy-oci.md)
