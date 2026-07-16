# B.I Comercial Biomassa — serviço Railway

Serve o dashboard num link fixo e **atualiza sozinho às 08:00 e 12:30** (horário de São Paulo).
Não usa IA — é só script puxando o Bitrix e remontando os números. Custo = R$ 0 de IA.

## Arquivos
- `server.py` — servidor web (Flask) + agendador (08:00 e 12:30) + gera na subida
- `generate.py` — puxa o Bitrix, calcula tudo e injeta no `template.html` → `index.html`
- `template.html` — o dashboard (com marcadores `__DATA__` e `__GENDATE__`)
- `requirements.txt`, `Procfile` — deploy

## Deploy no Railway (uma vez)
1. Suba esta pasta num repositório GitHub (ou use o Railway CLI `railway up`).
2. No Railway: **New Project → Deploy from GitHub repo** → escolha o repo.
3. Em **Variables**, adicione:
   - `BI_WEBHOOK` = `https://biomassadobrasil.bitrix24.com.br/rest/16/SEU_TOKEN/`
     (o webhook de entrada, escopo `crm`, somente leitura)
4. O Railway instala o `requirements.txt` e roda `python server.py` (Procfile).
5. Em **Settings → Networking → Generate Domain** para ter a URL pública.
6. Abra a URL — o painel aparece (na 1ª subida leva alguns segundos gerando).

## Rotas
- `/` → o dashboard
- `/atualizar` → força uma atualização na hora (útil pra testar)
- `/health` → monitor de uptime

## Trocar o horário
Em `server.py`, nos `sched.add_job(...)` — `hour`/`minute` no fuso America/Sao_Paulo.
