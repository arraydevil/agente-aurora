# Aurora — Agente de Atendimento com Base de Conhecimento Documental

> Desafio **Tech Builder Challenge** — Oracle Next Education (ONE) · 

Aurora é uma agente de inteligência artificial que atende clientes de um
e-commerce ficticio de dermocosméticos. Ela responde em linguagem natural sobre produtos,
ingredientes cosméticos, combinação de ativos, prazos de entrega, trocas,
devoluções e privacidade — **sempre a partir do conteúdo de documentos reais
(PDF e CSV) inseridos previamente no código, e sempre citando de onde tirou a informação.**

O diferencial do projeto está na base de conhecimento: além das políticas da
loja, a Aurora consulta um glossário curado de **132 ingredientes na nomenclatura
INCI**, com função, comedogenicidade, contraindicações e regras de
incompatibilidade entre ativos. Isso permite responder perguntas que um chatbot
de FAQ comum não alcança, como *"posso usar retinol e ácido glicólico na mesma
noite?"* ou *"esse sérum é seguro na gestação?"*.

---

## Índice

- [O problema](#o-problema)
- [Arquitetura da solução](#arquitetura-da-solução)
- [Base de conhecimento](#base-de-conhecimento)
- [Como o RAG foi implementado](#como-o-rag-foi-implementado)
- [Tecnologias utilizadas](#tecnologias-utilizadas)
- [Como executar](#como-executar)
- [API](#api)
- [Exemplos de perguntas](#exemplos-de-perguntas)
- [Exemplos de respostas](#exemplos-de-respostas)
- [Testes](#testes)
- [Deploy](#deploy)
- [Estrutura do repositório](#estrutura-do-repositório)
- [Decisões de projeto](#decisões-de-projeto)
- [Limitações conhecidas](#limitações-conhecidas)

---

## O problema

Um e-commerce de beleza recebe sempre as mesmas perguntas, e elas se dividem em
dois grupos que normalmente vivem em sistemas separados:

1. **Operacionais** — "quando chega?", "posso trocar?", "há frete aonde moro?"
   As respostas normalmente estão em documentos de política, longos e chatos de ler.
2. **Técnicas de produto** — "serve para pele oleosa?", "possuo alergia a ativo x tem outros que posso usar?", "posso usar estando grávida?", "esses dois ativos podem juntos?" As respostas dependem de conhecimento dermocosmético que o atendente humano nem sempre domina.

---

## Arquitetura da solução

```
                        ┌──────────────────────────────┐
                        │   Interface de chat (HTML)   │
                        │      web/index.html          │
                        └───────────────┬──────────────┘
                                        │ POST /api/perguntar
                        ┌───────────────▼──────────────┐
                        │      API FastAPI             │
                        │      app/main.py             │
                        └───────────────┬──────────────┘
                                        │
                        ┌───────────────▼──────────────┐
                        │   Agente Aurora              │
                        │   app/agente.py              │
                        └───┬───────────────────────┬──┘
                            │                       │
              ┌─────────────▼─────────┐   ┌─────────▼──────────────┐
              │  Recuperação BM25     │   │  Roteador de LLM       │
              │  app/indice.py        │   │  app/llm/roteador.py   │
              └─────────────┬─────────┘   └─────────┬──────────────┘
                            │                       │
              ┌─────────────▼─────────┐   ┌─────────▼──────────────┐
              │  Ingestão de          │   │ 1. Groq                │
              │  documentos           │   │ 2. Gemini (reserva)    │
              │  app/ingestao.py      │   │ 3. Extrativo (sem LLM) │
              └─────────────┬─────────┘   └────────────────────────┘
                            │
       ┌────────────────────┼────────────────────┐
       │                    │                    │
┌──────▼───────┐   ┌────────▼────────┐   ┌───────▼──────────┐
│ politicas_   │   │ catalogo_       │   │ glossario_       │
│ lumina.pdf   │   │ produtos.csv    │   │ ingredientes.csv │
│ 8 páginas    │   │ 44 produtos     │   │ 132 ingredientes │
└──────────────┘   └─────────────────┘   └──────────────────┘
```

### Fluxo de uma pergunta

1. A cliente envia a pergunta pela interface web ou pela API.
2. Se a mensagem for **apenas social** — "olá", "obrigada", "tchau" — a Aurora
   responde na hora, sem busca e sem chamar o LLM. Sem esse desvio, um "olá"
   caía na guarda de escopo e era recebido com *"não encontrei essa informação
   nos documentos"*. Mensagem que mistura cumprimento e pergunta de verdade
   ("bom dia, qual o prazo de entrega?") segue o fluxo normal.
3. O **índice BM25** pontua os 208 trechos indexados e devolve os 6 mais
   relevantes, com limite por documento para garantir diversidade de fonte.
4. Se nada passar do limiar de relevância, o agente responde que não sabe —
   **sem chamar o LLM**. Isso evita alucinação e economiza chamada.
5. Os trechos recuperados viram um prompt ancorado, com instrução explícita de
   usar somente aquele conteúdo.
6. O **roteador de LLM** chama o provedor configurado. Se falhar, desce para o
   próximo da lista sem derrubar a requisição.
7. A resposta passa pela limpeza de marcação e volta com a lista de trechos
   consultados, o provedor que respondeu e o tempo de processamento.

---

## Base de conhecimento

Três documentos-fonte, nos dois formatos exigidos pelo desafio:

| Documento | Formato | Conteúdo | Trechos gerados |
|---|---|---|---|
| `dados/politicas_lumina.pdf` | **PDF**, 8 páginas | Privacidade e LGPD, trocas e devoluções, envios e entregas, FAQ, termos de uso e guia de combinação de ativos | 32 |
| `dados/catalogo_produtos.csv` | **CSV** | 44 produtos com preço, volume, tipo de pele, ativos, indicações, estoque, segurança na gestação e selo vegano | 44 |
| `dados/glossario_ingredientes.csv` | **CSV** | 132 ingredientes INCI com função, comedogenicidade, tipos de pele, contraindicações e alertas | 132 |
| | | **Total indexado** | **208 trechos** |

### Origem dos documentos

O repositório guarda a **fonte editável** de cada documento, não só o resultado:

- `docs_fonte/politicas_lumina.md` → o PDF é gerado por `scripts/gerar_pdf.py`
  (ReportLab), com sumário visual, tabelas e paginação.
- `dados/base_ingredientes.json` → o CSV é gerado por
  `scripts/gerar_glossario_csv.py`, e o JSON também guarda as sete regras de
  incompatibilidade entre ativos que alimentam a seção 7 do PDF.

Assim dá para auditar de onde veio cada informação, e regerar tudo com dois
comandos.

> **Aviso.** A Lumina Beauty é uma loja fictícia criada para o desafio. Os dados
> de ingredientes são baseados em fontes públicas (INCI/PCPC, CosIng da Comissão
> Europeia, RDC 600/2022 e 894/2024 da ANVISA, relatórios do CIR) e têm caráter
> educativo. Não substituem avaliação de dermatologista.

---

## Como o RAG foi implementado

### Leitura dos documentos (`app/ingestao.py`)

**PDF.** O texto é extraído página a página com `pypdf`. Cabeçalho e rodapé são
descartados por regex. O corpo é quebrado em **seções numeradas** (`3.4 Reação
alérgica`, `7.1 Combinações que exigem cuidado`), o que produz trechos com
fronteira semântica de verdade, em vez de cortes arbitrários. Seções muito
longas são fatiadas em pedaços de até 1200 caracteres com 150 de sobreposição,
sempre quebrando em fim de frase. Cada trecho carrega a seção e a página de
origem — é isso que permite a citação `seção 3.4 Reação alérgica, p. 3`.

**CSV.** Cada linha vira uma **ficha em texto corrido**, não uma tupla. A linha
do catálogo

```csv
LB-0004,Retinol 0.3% em Sérum Encapsulado,Lumina Lab,Tratamento,Sérum,139.90,...,nao,sim,54,4.5
```

é reescrita como:

```
PRODUTO LB-0004 — Retinol 0.3% em Sérum Encapsulado (Lumina Lab).
Categoria: Tratamento / Sérum. Apresentação: 30ml.
Preço: R$ 139,90. Estoque: 54 unidades, disponível em estoque.
Indicado para pele: mista, oleosa, madura.
Ativos principais: Retinol, Squalane.
Gestação: contraindicado na gestação e na amamentação. Vegano: sim.
```

A reescrita não é cosmética. O buscador e o LLM trabalham muito melhor com
`Preço: R$ 139,90` do que com um campo solto — e a escolha de cada palavra
importa: a versão inicial usava *"NÃO indicado na gestação"*, mas `não` é
palavra vazia no índice, então a negação sumia e o retinol podia ser recuperado
como se fosse liberado para gestantes. Trocamos por **`contraindicado`**, um
token próprio e inequívoco.

### Recuperação (`app/indice.py`)

**BM25 Okapi implementado em Python puro**, sem banco vetorial e sem modelo de
embedding. Para uma base de poucas centenas de trechos, BM25 entrega qualidade
equivalente sem exigir GPU, serviço externo ou centenas de MB de dependência —
o que mantém o pacote enxuto e o deploy simples em qualquer plataforma.

Três adaptações ao português e ao domínio:

1. **Normalização** — remoção de acento, minúsculas e corte de plural simples,
   para que "ácidos" e "ácido" caiam no mesmo termo.
2. **Expansão de sinônimos** — a cliente escreve "grávida", o documento diz
   "gestação"; ela escreve "espinha", o glossário diz "acne"; ela escreve
   "sumiu", a política diz "extravio". Um dicionário de ~50 entradas faz essa
   ponte.
3. **Cobertura mínima, com exceção para nomes de entidade** — um único termo em
   comum normalmente não caracteriza relevância: a palavra "hoje" aparece por
   acaso na ficha da oxibenzona, e sem essa regra *"qual a escalação do time
   hoje"* recuperava aquele trecho. Mas exigir dois acertos quebrou
   *"o que é niacinamida e para que serve"* — só "niacinamida" existe no
   índice, porque "serve" não aparece em documento nenhum. A regra final aceita
   um acerto único **quando o termo nomeia um ingrediente ou produto da base**,
   conjunto extraído dos campos INCI, nome popular, nome e código.

Há ainda um **limite por documento** (padrão: 4), para que seis fichas de
ingrediente não afoguem a política de troca quando a pergunta toca os dois
assuntos.

### Geração (`app/agente.py` e `app/llm/`)

O prompt de sistema define a persona e impõe as regras que sustentam a
confiabilidade: responder só com os trechos fornecidos, nunca inventar preço,
prazo ou código, admitir quando não sabe, avisar sobre incompatibilidade entre
ativos mesmo sem ser perguntado, e nunca diagnosticar nem prescrever. Define
também a voz da Aurora — acolhedora, sem jargão, no máximo dois emojis por
resposta, e parágrafos curtos separados por linha em branco.

As fontes **não** aparecem no corpo da resposta: elas voltam no campo `fontes`
do JSON, e a interface as exibe em um painel próprio. Repetir a lista no texto
só polui a leitura.

Depois da geração vem uma camada de limpeza (`limpar_resposta`, em
`app/agente.py`). O prompt pede texto puro, mas nenhum modelo obedece sempre —
escapa um `**`, uma tabela em pipes, um marcador `[2]` no meio da frase. A
limpeza remove essa marcação, converte tabela em lista e corta qualquer bloco
"Fontes" que o modelo tenha escrito por conta própria. Fica no servidor, e não
no frontend, para que a API, a interface e os exemplos gerados saiam iguais.

O **roteador de provedores** percorre a lista de `PROVEDORES_LLM` em ordem —
hoje Groq e depois Gemini — e desce um degrau sempre que algo falha. O último
degrau não usa LLM nenhum: monta a resposta com os trechos recuperados,
avisando que aquilo não é recomendação. A aplicação nunca fica muda.

---

## Tecnologias utilizadas

| Camada | Tecnologia | Por quê |
|---|---|---|
| Linguagem | Python 3.11+ | Ecossistema maduro para IA e leitura de documentos |
| API | FastAPI + Uvicorn | Validação por tipo e Swagger automático em `/docs` |
| Validação | Pydantic v2 | Contrato de entrada e saída da API |
| Leitura de PDF | pypdf | Extração de texto página a página |
| Geração de PDF | ReportLab | Constrói o PDF a partir do markdown-fonte |
| Recuperação | BM25 Okapi (implementação própria) | RAG com busca esparsa: sem embedding e sem banco vetorial |
| LLM em produção | **Groq** (`openai/gpt-oss-120b`) | Latência baixa e nível gratuito generoso |
| LLM de reserva | Google Gemini (`gemini-3.6-flash`) | Segundo degrau da cascata de provedores |
| Cliente HTTP | httpx | Chamadas REST aos provedores de LLM |
| Frontend | HTML, CSS e JavaScript sem framework | Zero build, um arquivo, paleta sakura |
| Testes | pytest | 80 testes de ingestão, recuperação, limpeza e resposta |
| Hospedagem | **Vercel** | Build a partir do GitHub e redeploy a cada `git push` |
| Empacotamento | Docker | Mesma imagem em qualquer nuvem ou na máquina local |

> **Sobre RAG e banco vetorial.** O projeto usa RAG — recuperar, aumentar o
> prompt, gerar — mas com **recuperação esparsa**, não vetorial. Não há
> embedding, Chroma, FAISS nem pgvector: a busca é BM25 Okapi escrita à mão em
> `app/indice.py`. Vetores são uma implementação possível da etapa de
> recuperação, não um requisito de RAG. O porquê da escolha está em
> [Decisões de projeto](#decisões-de-projeto).

---

## Como executar

### Pré-requisitos

- Python 3.10 ou superior
- Git

### 1. Clonar e instalar

```bash
git clone https://github.com/<seu-usuario>/agente-aurora.git
cd agente-aurora

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Configurar as credenciais

```bash
cp .env.example .env             # Windows: copy .env.example .env
```

Abra o `.env` e preencha ao menos um provedor. O caminho mais curto é a **Groq**,
cuja chave sai em um minuto em <https://console.groq.com/keys>, sem cartão:

```env
PROVEDORES_LLM=groq,gemini
GROQ_API_KEY=gsk_sua_chave_aqui
GROQ_MODEL=openai/gpt-oss-120b
```

> Groq e Google aposentam modelos com frequência, e a chamada passa a devolver
> `404`. Para ver os que a sua conta tem ativos:
> ```bash
> curl -H "Authorization: Bearer $GROQ_API_KEY" https://api.groq.com/openai/v1/models
> ```

> Sem nenhum provedor configurado a aplicação **sobe do mesmo jeito** e responde
> em modo extrativo, devolvendo os trechos recuperados dos documentos.

### 3. (Opcional) Regerar os documentos

Os artefatos já estão versionados. Para regerar depois de editar as fontes:

```bash
python scripts/gerar_glossario_csv.py    # base_ingredientes.json -> CSV
python scripts/gerar_pdf.py              # markdown -> PDF de políticas
```

### 4. Subir a aplicação

```bash
uvicorn app.main:app --reload --port 8000
```

Abra **http://localhost:8000** para o chat, ou **http://localhost:8000/docs**
para o Swagger.

### Com Docker

```bash
docker build -t agente-aurora .
docker run -d -p 8000:8000 --env-file .env --name aurora agente-aurora
```

---

## API

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/` | Interface de chat |
| `POST` | `/api/perguntar` | Envia uma pergunta e recebe a resposta com fontes |
| `GET` | `/api/exemplos` | Perguntas sugeridas |
| `GET` | `/api/documentos` | Estatísticas dos documentos indexados |
| `GET` | `/api/saude` | Health check e status dos provedores de LLM |
| `GET` | `/docs` | Documentação interativa (Swagger) |

### Exemplo de chamada

```bash
curl -X POST http://localhost:8000/api/perguntar \
  -H "Content-Type: application/json" \
  -d '{"pergunta": "Posso usar retinol e ácido glicólico na mesma noite?"}'
```

### Formato da resposta

```json
{
  "resposta": "Não recomendamos usar os dois na mesma noite...",
  "fontes": [
    {
      "documento": "politicas_lumina.pdf",
      "referencia": "seção 7.1 Combinações que exigem cuidado, p. 6-7 (1/2)",
      "pontuacao": 15.97,
      "tipo": "pdf"
    },
    {
      "documento": "glossario_ingredientes.csv",
      "referencia": "ingrediente Glycolic Acid, linha 33",
      "pontuacao": 7.41,
      "tipo": "csv"
    }
  ],
  "provedor": "groq",
  "trechos_recuperados": 6,
  "tempo_ms": 1840
}
```

---

## Exemplos de perguntas

Perguntas que a Aurora responde a partir dos documentos:

**Sobre ingredientes e combinações** *(glossário CSV + guia no PDF)*
- Posso usar retinol e ácido glicólico na mesma noite?
- O que é niacinamida e para que serve?
- Óleo de coco no rosto pode causar cravos?
- Estou grávida, quais ativos do catálogo eu posso usar?
- Vitamina C e peróxido de benzoíla podem ser usados juntos?

**Sobre produtos** *(catálogo CSV)*
- Qual protetor solar vocês têm para pele oleosa até R$ 120?
- Quais produtos de vocês são veganos e cruelty-free?
- Tem alguma coisa para manchas de melasma?

**Sobre a operação da loja** *(PDF de políticas)*
- Em quantos dias chega em Manaus e quanto custa o frete?
- Comprei um sérum, abri e tive alergia. Consigo devolver?
- Meu pedido está parado no rastreio há 12 dias. E agora?
- Como faço para excluir meus dados do site?
- A partir de quanto o frete é grátis?

E, por desenho, ela **não** responde "quem ganhou a Copa de 1982" — devolve que
a informação não está nos documentos e oferece o contato humano.

---

## Exemplos de respostas

As respostas reais geradas pelo agente estão em
**[`docs/exemplos_respostas.md`](docs/exemplos_respostas.md)**, com o provedor
que respondeu, o tempo de processamento e os trechos citados em cada uma.

O arquivo não é escrito à mão: é produzido executando o agente de verdade.

```bash
python scripts/gerar_exemplos.py
```

---

## Testes

```bash
pytest -q
```

64 testes cobrindo:

- extração do PDF, com verificação de que valores críticos sobrevivem
  (`7 dias corridos`, `R$ 199,00`, `LGPD`, `peróxido de benzoíla`);
- conversão de tipos do CSV (preço como `float`, estoque como `int`);
- tokenização, remoção de plural, palavras vazias e expansão de sinônimos;
- recuperação da seção correta para consultas conhecidas;
- rejeição de pergunta fora do escopo;
- limite por documento;
- resposta do agente com fontes, inclusive sem nenhum LLM configurado.

Três arquivos são regressão de defeitos reais encontrados durante o
desenvolvimento, e não teste escrito por obrigação:

- `test_entidades.py` — a palavra solta que trazia trecho irrelevante, e a busca
  por nome de ingrediente que parou de funcionar quando o primeiro foi corrigido.
- `test_limpeza.py` — tabela em pipes e bloco "Fontes" aparecendo literais na
  tela, incluindo o caso de não confundir "nossas **fontes** de vitamina C" com
  um cabeçalho de fontes.
- `test_social.py` — "olá" sendo recebido com *"não encontrei essa informação
  nos documentos"*.

---

## Deploy

A aplicação está publicada na **Vercel**, importada direto do GitHub e
republicada a cada `git push` na `main`.

Passo a passo em **[`docs/deploy-vercel.md`](docs/deploy-vercel.md)**.

### Evidência do deploy

| | |
|---|---|
| **URL pública** | **<https://agente-aurora.vercel.app>** |
| **Captura de tela** | `docs/evidencia-deploy.png` |

Conferência rápida do que está no ar:

```bash
curl https://agente-aurora.vercel.app/api/saude
```

### Portabilidade

O mesmo código roda, sem bifurcação por plataforma, em quatro destinos. Só muda
o arquivo de configuração da vez:

| Destino | Arquivo | Guia |
|---|---|---|
| Vercel | `vercel.json` | [`deploy-vercel.md`](docs/deploy-vercel.md) |
| AWS App Runner | `apprunner.yaml` | [`deploy-aws.md`](docs/deploy-aws.md) |
| Docker, em qualquer lugar | `Dockerfile` | [`deploy-aws.md`](docs/deploy-aws.md) |

Nenhum arquivo de adaptação foi necessário: a Vercel detecta a instância FastAPI
em `app/main.py` sozinha, e o App Runner e o Docker apenas chamam o mesmo
`app.main:app`. Nenhuma linha do agente conhece a plataforma onde está rodando.

---

## Estrutura do repositório

```
agente-aurora/
├── app/
│   ├── main.py               API FastAPI e rotas
│   ├── agente.py             Orquestração do agente e prompt de sistema
│   ├── indice.py             BM25 Okapi, tokenização e sinônimos
│   ├── ingestao.py           Leitura de PDF e CSV, geração de trechos
│   └── llm/
│       ├── base.py           Contrato dos provedores
│       ├── reserva.py        Groq e Gemini via REST
│       └── roteador.py       Fallback em cascata
├── dados/
│   ├── politicas_lumina.pdf       documento-fonte (PDF)
│   ├── catalogo_produtos.csv      documento-fonte (CSV)
│   ├── glossario_ingredientes.csv documento-fonte (CSV)
│   └── base_ingredientes.json     fonte editável do glossário
├── docs_fonte/
│   └── politicas_lumina.md   markdown que origina o PDF
├── scripts/
│   ├── gerar_pdf.py
│   ├── gerar_glossario_csv.py
│   └── gerar_exemplos.py
├── web/index.html            interface de chat
├── testes/
│   ├── test_pipeline.py      ingestão, recuperação e resposta
│   ├── test_entidades.py     cobertura mínima e nomes de entidade
│   ├── test_limpeza.py       remoção de marcação das respostas
│   └── test_social.py        saudação, agradecimento e despedida
├── docs/deploy-vercel.md     guia de implantação
├── Dockerfile
├── requirements.txt
└── .env.example
```

---

## Decisões de projeto

**BM25 em vez de banco vetorial.** Com 208 trechos, embeddings trariam ganho
marginal e um custo real: modelo para baixar, dependência pesada, e uma chamada
externa a mais no caminho de cada pergunta. BM25 é determinístico, roda em
milissegundos, cabe em qualquer plano gratuito e é auditável — dá para explicar
exatamente por que um trecho foi escolhido.

**Fallback em cascata entre provedores.** Uma demonstração que morre porque um
serviço externo oscilou não demonstra nada. A cascata tenta cada provedor
configurado e, no último degrau, responde com os próprios trechos recuperados,
sem LLM nenhum.

Trocar de provedor de inferência custa alterar uma lista no `.env`. Trocar de
nuvem custa acrescentar um arquivo de configuração. O agente, a ingestão e a
recuperação não são tocados em nenhum dos dois casos.

**Recusa explícita.** Quando nada passa do limiar, o agente responde que não
sabe **antes** de chamar o LLM. Um agente que responde tudo é um agente em que
não se pode confiar em nada.

**Documentos com fonte versionada.** O PDF e o CSV são gerados por script a
partir de markdown e JSON versionados. O repositório mostra a origem de cada
informação, em vez de um binário sem procedência.

**Citação obrigatória.** Toda resposta carrega os trechos consultados, com
documento, seção e página ou linha. É o que permite a cliente conferir, e a
equipe auditar.

---

## Limitações conhecidas

- A loja e os dados são fictícios; o conteúdo é educativo e não substitui
  avaliação dermatológica.
- O índice é reconstruído a cada inicialização e fica em memória. Para uma base
  muito maior valeria persistir o índice ou migrar para busca híbrida.
- O histórico de conversa usa janela curta (4 turnos) e não é persistido entre
  sessões.
- A expansão de sinônimos é um dicionário manual. Escala bem até algumas
  centenas de termos; além disso, embeddings passam a compensar.
- Não há autenticação nem limite de requisições — a aplicação é uma
  demonstração, não um serviço de produção.

---

<div align="center">

Desenvolvido para o **Tech Builder Challenge** · Oracle Next Education · 2026

</div>
