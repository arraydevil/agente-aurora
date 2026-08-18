# Implantação no AWS App Runner

Guia para publicar a Aurora com URL HTTPS pública, a partir do código no GitHub.
O App Runner constrói a aplicação na nuvem: **não é preciso ter Docker
instalado**, nem criar repositório no ECR.

Tempo estimado: **15 a 25 minutos**.

---

## Sumário

1. [Antes de começar](#1-antes-de-começar)
2. [Conectar o GitHub](#2-conectar-o-github)
3. [Criar o serviço](#3-criar-o-serviço)
4. [Configurar a chave da Groq](#4-configurar-a-chave-da-groq)
5. [Health check](#5-health-check)
6. [Verificar](#6-verificar)
7. [Atualizar a aplicação](#7-atualizar-a-aplicação)
8. [Custo](#8-custo)
9. [Solução de problemas](#solução-de-problemas)

---

## 1. Antes de começar

Você precisa de:

- Conta AWS ativa
- O repositório **público** no GitHub com o `apprunner.yaml` na raiz
- A chave da Groq (`gsk_...`)

Escolha uma região que tenha App Runner. `us-east-1` (Norte da Virgínia) é a mais
barata e a que tem tudo disponível primeiro. `sa-east-1` (São Paulo) reduz a
latência para usuários no Brasil, mas custa mais.

> A latência aqui pesa pouco: o gargalo da resposta é a chamada ao LLM, que leva
> 1 a 2 segundos. Alguns milissegundos de rede não mudam a experiência.

---

## 2. Conectar o GitHub

Console da AWS → busque **App Runner** → **Create an App Runner service**

1. **Repository type:** `Source code repository`
2. Em **Connect to GitHub**, clique em **Add new**
3. Autorize o *AWS Connector for GitHub* na sua conta
4. Escolha o repositório `agente-aurora` e o branch `main`
5. **Deployment trigger:** `Automatic` — cada `git push` na `main` republica sozinho

---

## 3. Criar o serviço

**Configure build**

- Marque **Use a configuration file**
- O App Runner encontra o `apprunner.yaml` na raiz do repositório e lê dali o
  runtime (Python 3.11), o comando de build, o comando de execução e a porta

**Configure service**

| Campo | Valor |
|---|---|
| Service name | `agente-aurora` |
| Virtual CPU | 0.25 vCPU |
| Virtual memory | 0.5 GB |

> 0.25 vCPU e 0.5 GB dão conta com folga. A indexação BM25 dos 208 trechos
> acontece uma vez, na subida, e ocupa poucos megabytes.

Clique em **Create & deploy**. A primeira implantação leva de 5 a 10 minutos.

---

## 4. Configurar a chave da Groq

A chave **não** entra no `apprunner.yaml`, que é versionado. Ela vai como
variável de ambiente do serviço.

App Runner → seu serviço → **Configuration** → **Configure service** → **Edit**
→ **Environment variables** → **Add environment variable**

| Source | Name | Value |
|---|---|---|
| Plain text | `GROQ_API_KEY` | `gsk_...` |

Salve. O serviço reimplanta sozinho.

### Alternativa mais segura: Secrets Manager

Para não deixar a chave visível no console:

1. Secrets Manager → **Store a new secret** → *Other type of secret* → *Plaintext*
2. Cole só o valor da chave. Nome: `aurora/groq-api-key`
3. Dê ao serviço uma **Instance role** com permissão
   `secretsmanager:GetSecretValue` sobre esse ARN
4. Na variável de ambiente, escolha **Source: Secrets Manager** e informe o ARN

---

## 5. Health check

Por padrão o App Runner só testa se a porta responde (TCP). A aplicação tem um
endpoint próprio, que confirma também que os documentos foram indexados:

**Configuration** → **Health check** → **Edit**

| Campo | Valor |
|---|---|
| Protocol | `HTTP` |
| Path | `/api/saude` |
| Interval | 10 s |
| Timeout | 5 s |
| Healthy threshold | 1 |
| Unhealthy threshold | 5 |

Com isso, uma instância que subiu mas falhou ao ler o PDF é substituída em vez
de ficar servindo erro.

---

## 6. Verificar

A URL aparece no topo da página do serviço, no formato
`https://xxxxxxxx.us-east-1.awsapprunner.com`.

```bash
curl https://SUA-URL.awsapprunner.com/api/saude
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
curl -X POST https://SUA-URL.awsapprunner.com/api/perguntar \
  -H "Content-Type: application/json" \
  -d '{"pergunta": "A partir de quanto o frete é grátis?"}'
```

Confirme que vem `"provedor": "groq"`. Se vier `"extrativo"`, a chave não chegou
ao serviço — veja o campo `tentativas` da resposta, que diz o motivo exato.

Por fim, abra a URL no navegador e faça uma pergunta pela interface.

---

## 7. Atualizar a aplicação

Com o gatilho automático ligado:

```bash
git push origin main
```

O App Runner detecta o commit, reconstrói e troca a versão sem derrubar a
anterior. Acompanhe em **Activity** e **Logs** no console.

Para pausar e parar de gastar sem apagar nada: **Actions** → **Pause**.
Retomar leva cerca de um minuto.

---

## 8. Custo

O App Runner cobra separadamente por memória provisionada (mesmo ocioso) e por
CPU (só enquanto processa requisição).

Com 0.25 vCPU e 0.5 GB, um serviço de demonstração fica na casa de
**US$ 5 a 8 por mês**, praticamente tudo em memória provisionada. Créditos da
AWS cobrem isso com sobra.

Se o projeto for ficar meses parado entre uma entrevista e outra, use
**Pause** — em pausa, não há cobrança de memória.

---

## Solução de problemas

**O build falha em `pip3 install -r requirements.txt`.**
Veja os *Build logs* no console. O `requirements.txt` não inclui o SDK da OCI de
propósito: são mais de 100 MB para um provedor que não é usado aqui. Se você
precisar dele, use `requirements-oci.txt`.

**Serviço fica em `Create failed` sem log claro.**
Quase sempre é o `apprunner.yaml`: ele precisa estar na **raiz** do repositório,
o `runtime` tem que ser `python311` e o `runtime-version`, `3.11`. Um erro de
indentação no YAML derruba a implantação inteira.

**Health check falhando e reciclando a instância.**
Se você configurou o path `/api/saude`, aumente o *Unhealthy threshold* e o
*Timeout*: a primeira subida lê e indexa o PDF antes de responder. Confirme no
log a linha `Aurora pronta — 208 trechos indexados`.

**A resposta vem com `"provedor": "extrativo"`.**
Nenhum LLM respondeu. O campo `tentativas` no JSON diz o porquê. As causas
usuais: `GROQ_API_KEY` ausente no serviço, ou modelo descontinuado — a Groq
aposenta modelos com frequência e devolve 404. Liste os ativos com:

```bash
curl -H "Authorization: Bearer $GROQ_API_KEY" https://api.groq.com/openai/v1/models
```

E ajuste `GROQ_MODEL` nas variáveis de ambiente do serviço.

**Erro 429 sob demonstração ao vivo.**
É o limite por minuto do nível gratuito da Groq. A aplicação já repete a chamada
respeitando o cabeçalho `retry-after`; se persistir, espace as perguntas ou
configure também a `GEMINI_API_KEY` como segundo degrau.

---

## Sobre a Oracle Cloud

Este projeto foi originalmente arquitetado para a OCI, e o provedor
`app/llm/oci_genai.py` continua no repositório, com suporte a autenticação por
*instance principal*. O guia correspondente está em
[`deploy-oci.md`](deploy-oci.md).

A migração para a AWS custou poucos commits justamente porque a camada de LLM é
um roteador com provedores intercambiáveis — trocar de nuvem não exigiu tocar no
agente, na ingestão nem na recuperação.
