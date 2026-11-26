# Robô de Inadimplência — Morais Corretora

Entra nos portais das seguradoras, baixa o relatório de parcelas em aberto e junta tudo em
**uma única planilha Excel** (`saidas/CONTROLE_INADIMPLENCIA_AAAA-MM-DD.xlsx`).

**Etapa 1 (atual):** extração + planilha consolidada.
**Etapa 2 (futura):** cobrança automática via WhatsApp (Digisac).

| Seguradora | Situação |
|---|---|
| Allianz (AllianzNet) | ✅ testada no portal real em 26/11/2026 (135 parcelas, ~20 s) |

## A planilha gerada

- **Resumo**: uma linha por seguradora com a situação da extração (OK/ERRO), a quantidade de parcelas e o valor total.
- **Inadimplência Consolidada**: uma linha por parcela em aberto.
  - As **10 primeiras colunas são iguais às do modelo da equipe**:
    `SEGURADORA, SEGURADO, APÓLICE/CPF, PAGAMENTO, PARCELA, VENCIMENTO, PRODUTOR, NOVA DATA, CONTATO, DATA LIMITE`.
    PAGAMENTO (com lista CARTÃO/DÉBITO/PIX/BOLETO), PRODUTOR, NOVA DATA, CONTATO e DATA LIMITE saem em branco para a equipe preencher.
  - Depois vêm as colunas extras trazidas pelo robô (cabeçalho num azul mais claro):
    `CPF/CNPJ, APÓLICE, RECIBO, RAMO, DIAS EM ATRASO, VALOR, PREV. CANCELAMENTO, COMISSÃO`.
  - Segurado repetido fica destacado em rosa, como no modelo.

## Painel web

Um site para acompanhar tudo num lugar só, aberto pelo navegador:

- **Extração de hoje**: se cada seguradora foi extraída com sucesso, deu erro (com o motivo) ou não rodou, mais um histórico dos últimos 14 dias.
- **Visão geral**: total em aberto e quantas parcelas estão perto de cancelar. Clicar num indicador filtra a tabela.
- **Parcelas em aberto** com filtros: busca por nome/CPF/recibo, seguradora, ramo, **risco de cancelamento**, "cancela em até X dias" e "atraso mínimo". Dá para ordenar por qualquer coluna e exportar o resultado para o Excel.
- **Saíram da lista**: parcelas que estavam na extração anterior e sumiram (provavelmente pagas).
- Botão **Atualizar agora**, que roda o robô na hora.

Classificação de risco (pela data prevista de cancelamento informada pela seguradora):

| Risco | Regra |
|---|---|
| Prazo vencido | a data prevista de cancelamento já passou |
| Crítico | cancela em até 7 dias |
| Atenção | cancela em 8 a 15 dias |
| Monitorar | mais de 15 dias |

Se uma seguradora não informar a data de cancelamento, o risco é calculado pelos dias de atraso
(60+ crítico, 30+ atenção).

**Como abrir:** dois cliques em `painel.bat` (deixe a janela aberta). No próprio computador:
http://localhost:8050. Nos outros computadores do escritório: `http://<ip-do-computador>:8050`.
Defina `PAINEL_USUARIO` e `PAINEL_SENHA` no `.env`. Sem senha, o painel só abre no próprio computador.

O histórico fica em `dados/inadimplencia.db` (não vai para o GitHub).

## Instalação (uma vez, no computador do escritório com Windows)

1. Instale o **Python 3.12+** em https://www.python.org/downloads/ e marque **"Add Python to PATH"**.
2. Copie esta pasta para o computador (ex.: `C:\RoboInadimplencia`).
3. Dê dois cliques em **`instalar.bat`**.
4. Abra o arquivo **`.env`** no Bloco de Notas e preencha o usuário e a senha de cada seguradora e a senha do painel.
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

Detalhes técnicos: a tela de parcelas é um sistema antigo dentro de um iframe (`/drbl13/`);
os campos usados são `#status` (valor `1` = Inadimplente), `#dtInicio`, `#dtFim`,
`#cmdPesquisar` e `#cmdGerarArquivo`. O CSV vem com `;`, uma linha em branco no topo
e CPF no formato `="00000000000"` — tudo tratado na leitura.

## Adicionar uma nova seguradora

1. Criar `robo/seguradoras/<nome>.py` com uma classe que tenha `baixar(page)` e `normalizar(arquivo)` (use `allianz.py` como modelo).
2. Registrar em `robo/seguradoras/__init__.py`.
3. Adicionar `<NOME>_USUARIO` / `<NOME>_SENHA` no `.env` e no `.env.example`.
