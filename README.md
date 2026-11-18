# Robô de Inadimplência — Morais Corretora

Entra nos portais das seguradoras, baixa o relatório de parcelas em aberto e junta tudo em
**uma única planilha Excel** (`saidas/CONTROLE_INADIMPLENCIA_AAAA-MM-DD.xlsx`).

**Etapa 1 (atual):** extração + planilha consolidada.
**Etapa 2 (futura):** cobrança automática via WhatsApp (Digisac).

| Seguradora | Situação |
|---|---|
| Allianz (AllianzNet) | ✅ implementada — aguardando 1º teste no portal real |

## A planilha gerada

- **Resumo**: uma linha por seguradora com a situação da extração (OK/ERRO), a quantidade de parcelas e o valor total.
- **Inadimplência Consolidada**: uma linha por parcela em aberto:
  `SEGURADORA, SEGURADO, CPF/CNPJ, APÓLICE, RECIBO, RAMO, PARCELA, VENCIMENTO, DIAS EM ATRASO, VALOR, PREV. CANCELAMENTO, COMISSÃO`
  e, no fim, as colunas de controle da equipe em branco (`PRODUTOR, PAGAMENTO, NOVA DATA, CONTATO, DATA LIMITE`).

## Instalação (uma vez, no computador do escritório com Windows)

1. Instale o **Python 3.12+** em https://www.python.org/downloads/ e marque **"Add Python to PATH"**.
2. Copie esta pasta para o computador (ex.: `C:\RoboInadimplencia`).
3. Dê dois cliques em **`instalar.bat`**.
4. Abra o arquivo **`.env`** no Bloco de Notas e preencha o usuário e a senha de cada seguradora.
   > O `.env` fica só nesse computador e nunca vai para o GitHub.

## Uso

- Dois cliques em **`executar.bat`** rodam todas as seguradoras.
- Para **ver o navegador trabalhando** (útil no 1º teste), coloque `NAVEGADOR_OCULTO=false` no `.env`.
- Para rodar só uma: `executar.bat allianz`
- Para converter um relatório que já foi baixado manualmente:
  `executar.bat --arquivo allianz=C:\Users\...\Downloads\GESTAO_DE_INADIMPLENTES.csv`

Quando dá erro, o robô salva um **print da tela** e um **log** na pasta `logs\`, e a aba *Resumo* mostra quais seguradoras falharam.

## Rodar sozinho todo dia (Agendador de Tarefas do Windows)

1. Menu Iniciar → **Agendador de Tarefas** → *Criar Tarefa Básica*.
2. Nome: `Robô Inadimplência`. Disparador: **Diariamente**, ex.: 07:00.
3. Ação: *Iniciar um programa* → selecione `executar.bat`. Em "Iniciar em", coloque a pasta do robô.
4. Nas propriedades da tarefa, marque **"Executar estando o usuário conectado ou não"**.

O computador precisa estar ligado no horário agendado.

## Como funciona (Allianz)

Repete o caminho que a equipe faz manualmente:
Gestão → Financeiro → Gestão de Parcelas → aba *Gestão de Inadimplentes* →
Status *Inadimplente*, vencimento dos últimos `DIAS_RETROATIVOS` dias (padrão 90) até hoje →
*Pesquisar* → *Gerar Planilha*.

## Adicionar uma nova seguradora

1. Criar `robo/seguradoras/<nome>.py` com uma classe que tenha `baixar(page)` e `normalizar(arquivo)` (use `allianz.py` como modelo).
2. Registrar em `robo/seguradoras/__init__.py`.
3. Adicionar `<NOME>_USUARIO` / `<NOME>_SENHA` no `.env` e no `.env.example`.
