# Implantação na Oracle Cloud Infrastructure

Guia completo para colocar a Aurora no ar em uma instância **Always Free** da
OCI, com a Generative AI autenticada por *instance principal* (sem chave privada
no servidor).

Tempo estimado: **40 a 60 minutos**, contando a criação da conta.

---

## Sumário

1. [Conta e requisitos](#1-conta-e-requisitos)
2. [Criar a rede](#2-criar-a-rede-vcn)
3. [Criar a instância](#3-criar-a-instância-de-computação)
4. [Abrir a porta na security list](#4-abrir-a-porta-na-security-list)
5. [Liberar a porta no firewall da instância](#5-liberar-a-porta-no-firewall-da-instância)
6. [Instalar o Docker](#6-instalar-o-docker)
7. [Permitir o acesso à Generative AI](#7-permitir-o-acesso-à-generative-ai)
8. [Subir a aplicação](#8-subir-a-aplicação)
9. [HTTPS com domínio](#9-https-com-domínio-opcional)
10. [Verificação final](#10-verificação-final)
11. [Solução de problemas](#solução-de-problemas)

---

## 1. Conta e requisitos

Crie a conta em <https://signup.oraclecloud.com>.

- A Oracle exige **cartão de crédito** apenas para verificação de identidade.
  É feita uma cobrança de aproximadamente **US$ 1,00**, estornada em seguida.
  Cartões virtuais de bancos digitais costumam funcionar.
- Escolha a **home region** com atenção: ela não pode ser alterada depois.
  Para o Brasil, `São Paulo (sa-saopaulo-1)` ou `Vinhedo (sa-vinhedo-1)`.
- Confirme que o serviço **Generative AI** está disponível na região escolhida
  em *Analytics & AI → Generative AI*. Se não estiver, use `us-chicago-1` no
  `OCI_REGION` — o serviço é acessível de outra região.

Anote o **OCID do compartimento** em *Identity → Compartments*. Ele vai no
`.env` como `OCI_COMPARTMENT_ID`.

---

## 2. Criar a rede (VCN)

*Networking → Virtual Cloud Networks → Start VCN Wizard*

1. Escolha **Create VCN with Internet Connectivity**.
2. Nome: `vcn-aurora`.
3. Aceite os blocos CIDR padrão.
4. **Create**.

O assistente cria a subnet pública, o internet gateway e a tabela de rotas.

---

## 3. Criar a instância de computação

*Compute → Instances → Create Instance*

| Campo | Valor |
|---|---|
| Nome | `aurora-agente` |
| Imagem | Canonical Ubuntu 22.04 |
| Shape | `VM.Standard.A1.Flex` (ARM) |
| OCPUs | 2 |
| Memória | 12 GB |
| Rede | `vcn-aurora`, subnet **pública** |
| IP público | **Assign a public IPv4 address** |
| Chave SSH | gere e **baixe a chave privada** |

> O tier Always Free dá 4 OCPUs e 24 GB de Ampere A1 no total. Usar 2 e 12 deixa
> margem para uma segunda instância.

Guarde o **IP público** exibido ao final.

Teste o acesso:

```bash
chmod 600 ~/Downloads/ssh-key-aurora.key
ssh -i ~/Downloads/ssh-key-aurora.key ubuntu@<IP_PUBLICO>
```

---

## 4. Abrir a porta na security list

*Networking → VCN → `vcn-aurora` → Subnets → subnet pública → Security Lists →
Default Security List → Add Ingress Rules*

| Campo | Valor |
|---|---|
| Source CIDR | `0.0.0.0/0` |
| IP Protocol | TCP |
| Destination Port Range | `80` |

Repita para a porta **443** se for usar HTTPS.

---

## 5. Liberar a porta no firewall da instância

**Este é o passo que mais trava gente.** A imagem Ubuntu da OCI vem com regras
de `iptables` que descartam tudo além do SSH. Abrir a porta na security list não
basta.

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

Confirme que a regra entrou antes do `REJECT`:

```bash
sudo iptables -L INPUT -n --line-numbers
```

---

## 6. Instalar o Docker

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y docker.io git
sudo systemctl enable --now docker
sudo usermod -aG docker ubuntu
```

Saia e entre de novo no SSH para o grupo valer:

```bash
exit
ssh -i ~/Downloads/ssh-key-aurora.key ubuntu@<IP_PUBLICO>
docker --version
```

---

## 7. Permitir o acesso à Generative AI

Com *instance principal*, a VM se autentica pela própria identidade. Nenhuma
chave privada precisa existir no servidor — é a forma correta de fazer isso.

### 7.1 Criar o grupo dinâmico

*Identity & Security → Domains → Default → Dynamic Groups → Create*

- Nome: `dg-aurora`
- Regra (substitua pelo OCID do seu compartimento):

```
ALL {instance.compartment.id = 'ocid1.compartment.oc1..xxxxxxxx'}
```

### 7.2 Criar a policy

*Identity & Security → Policies → Create Policy* (no compartimento raiz)

- Nome: `policy-aurora-genai`
- Instrução (substitua `<nome-do-compartimento>`):

```
Allow dynamic-group dg-aurora to use generative-ai-family in compartment <nome-do-compartimento>
```

### 7.3 Ajustar o `.env`

```env
OCI_AUTH=instance_principal
OCI_COMPARTMENT_ID=ocid1.compartment.oc1..xxxxxxxx
OCI_REGION=sa-saopaulo-1
OCI_GENAI_MODEL_ID=meta.llama-3.3-70b-instruct
OCI_GENAI_API_FORMAT=GENERIC
```

---

## 8. Subir a aplicação

```bash
git clone https://github.com/<seu-usuario>/agente-aurora.git
cd agente-aurora

cp .env.example .env
nano .env          # preencha conforme o passo 7.3

docker build -t agente-aurora .

docker run -d \
  --name aurora \
  --restart unless-stopped \
  -p 80:8000 \
  --env-file .env \
  agente-aurora
```

Acompanhe a subida:

```bash
docker logs -f aurora
```

Você deve ver:

```
Aurora pronta — 208 trechos indexados de politicas_lumina.pdf, catalogo_produtos.csv, glossario_ingredientes.csv
```

Acesse **http://\<IP_PUBLICO\>**.

---

## 9. HTTPS com domínio (opcional)

Com um domínio apontando para o IP público, o Caddy resolve o certificado
sozinho.

```bash
docker run -d --name aurora --restart unless-stopped \
  -p 8000:8000 --env-file .env agente-aurora

sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```

`/etc/caddy/Caddyfile`:

```
seu-dominio.com.br {
    reverse_proxy localhost:8000
}
```

```bash
sudo systemctl reload caddy
```

---

## 10. Verificação final

```bash
curl http://<IP_PUBLICO>/api/saude
```

Resposta esperada:

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
    {"provedor": "oci", "configurado": true},
    {"provedor": "groq", "configurado": false},
    {"provedor": "gemini", "configurado": false},
    {"provedor": "extrativo", "configurado": true}
  ]
}
```

Teste uma pergunta de ponta a ponta:

```bash
curl -X POST http://<IP_PUBLICO>/api/perguntar \
  -H "Content-Type: application/json" \
  -d '{"pergunta": "A partir de quanto o frete é grátis?"}'
```

Confirme que `"provedor": "oci"` aparece na resposta — é a evidência de que a
Generative AI da OCI respondeu, e não um provedor de reserva.

Para a evidência do desafio, tire um print da interface funcionando com o IP
público visível na barra de endereços e salve em `docs/evidencia-deploy.png`.

---

## Solução de problemas

**A página não abre, mas o container está de pé.**
Quase sempre é o passo 5. Rode `sudo iptables -L INPUT -n --line-numbers` e
confirme que a regra de ACCEPT está **antes** da linha de REJECT.

**`Out of host capacity` ao criar a instância.**
A capacidade de Ampere A1 no free tier é disputada. Tente outro *availability
domain*, tente em outro horário, ou reduza para 1 OCPU e 6 GB.

**`NotAuthorizedOrNotFound` ao chamar a Generative AI.**
A policy do passo 7.2 não está valendo. Confira se ela foi criada no
compartimento **raiz**, se o OCID na regra do grupo dinâmico é o do
compartimento da instância, e se o serviço existe na região configurada.

**`ServiceError: 404 NotFound` com o model id.**
O modelo foi descontinuado ou não existe naquela região. Liste os disponíveis em
*Analytics & AI → Generative AI → Playground* e ajuste `OCI_GENAI_MODEL_ID`.

**A resposta vem com `"provedor": "extrativo"`.**
Nenhum LLM respondeu. Veja o motivo exato no campo `tentativas` da resposta
JSON, ou em `docker logs aurora`.

**O container reinicia sozinho.**
`docker logs aurora` mostra o erro. Se for falta de memória durante o
`pip install` do SDK da OCI, adicione swap:

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```
