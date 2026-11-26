"""Painel web de inadimplência.

Uso:  python -m painel        (ou painel.bat no Windows)
Abre em http://localhost:8050 (ou http://<ip-do-computador>:8050 na rede do escritório).
"""
from __future__ import annotations

import subprocess
import sys
import threading
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

from robo import banco, config
from robo.seguradoras import SEGURADORAS

PASTA_WEB = Path(__file__).resolve().parent / "web"
DIAS_HISTORICO = 14

app = Flask(__name__)


# ------------------------------------------------------------------ acesso
def exige_login(f):
    @wraps(f)
    def interno(*a, **kw):
        if config.PAINEL_SENHA:
            auth = request.authorization
            if not auth or auth.username != config.PAINEL_USUARIO or auth.password != config.PAINEL_SENHA:
                return Response("Login necessário", 401,
                                {"WWW-Authenticate": 'Basic realm="Painel Inadimplencia"'})
        return f(*a, **kw)
    return interno


# --------------------------------------------------------------- consultas
def _seguradoras_conhecidas(con) -> list[str]:
    nomes = {cls.nome for cls in SEGURADORAS.values()}
    nomes |= {r[0] for r in con.execute("SELECT DISTINCT seguradora FROM extracoes")}
    return sorted(nomes)


def _ultimas_ok(con) -> dict:
    """Última extração bem-sucedida de cada seguradora."""
    linhas = con.execute("""
        SELECT e.* FROM extracoes e
        JOIN (SELECT seguradora, MAX(id) id FROM extracoes WHERE situacao='OK' GROUP BY seguradora) u
          ON u.id = e.id
    """).fetchall()
    return {l["seguradora"]: l for l in linhas}


def _risco(dias_cancelar, dias_atraso) -> str:
    if dias_cancelar is None:  # seguradora sem data prevista: usa o atraso
        if dias_atraso is None:
            return "monitorar"
        return "critico" if dias_atraso >= 60 else "atencao" if dias_atraso >= 30 else "monitorar"
    if dias_cancelar < 0:
        return "vencido"
    if dias_cancelar <= 7:
        return "critico"
    if dias_cancelar <= 15:
        return "atencao"
    return "monitorar"


def _dias(iso: str | None, hoje: date, inverso: bool = False):
    if not iso:
        return None
    d = date.fromisoformat(iso)
    return (d - hoje).days if inverso else (hoje - d).days


@app.get("/api/painel")
@exige_login
def api_painel():
    hoje = date.today()
    dias = [(hoje - timedelta(days=i)).isoformat() for i in range(DIAS_HISTORICO - 1, -1, -1)]
    with banco.conectar() as con:
        nomes = _seguradoras_conhecidas(con)
        ultimas_ok = _ultimas_ok(con)
        # situação mais recente de cada seguradora em cada dia
        hist = con.execute("""
            SELECT e.seguradora, e.data, e.situacao, e.horario, e.quantidade, e.valor_total, e.detalhe
            FROM extracoes e
            JOIN (SELECT seguradora, data, MAX(id) id FROM extracoes WHERE data >= ?
                  GROUP BY seguradora, data) u ON u.id = e.id
        """, (dias[0],)).fetchall()
        ultima_exec = con.execute("SELECT * FROM execucoes ORDER BY id DESC LIMIT 1").fetchone()

    por_dia = {(h["seguradora"], h["data"]): dict(h) for h in hist}
    seguradoras = []
    for nome in nomes:
        hoje_info = por_dia.get((nome, hoje.isoformat()))
        ok = ultimas_ok.get(nome)
        seguradoras.append({
            "nome": nome,
            "hoje": hoje_info,
            "ultima_ok": ok["horario"] if ok else None,
            "historico": [(por_dia.get((nome, d)) or {}).get("situacao") for d in dias],
        })
    resumo_hoje = {
        "ok": sum(1 for s in seguradoras if s["hoje"] and s["hoje"]["situacao"] == "OK"),
        "erro": sum(1 for s in seguradoras if s["hoje"] and s["hoje"]["situacao"] != "OK"),
        "pendente": sum(1 for s in seguradoras if not s["hoje"]),
        "total": len(seguradoras),
    }
    return jsonify({
        "hoje": hoje.isoformat(),
        "dias": dias,
        "seguradoras": seguradoras,
        "resumo_hoje": resumo_hoje,
        "ultima_execucao": dict(ultima_exec) if ultima_exec else None,
        "robo": _estado_robo(),
    })


@app.get("/api/parcelas")
@exige_login
def api_parcelas():
    hoje = date.today()
    with banco.conectar() as con:
        ultimas = _ultimas_ok(con)
        ids = [l["id"] for l in ultimas.values()]
        if not ids:
            return jsonify({"parcelas": [], "regularizadas": []})
        marc = ",".join("?" * len(ids))
        atuais = con.execute(f"""
            SELECT p.*, x.horario AS extraido_em FROM parcelas p
            JOIN extracoes x ON x.id = p.extracao_id
            WHERE p.extracao_id IN ({marc})
        """, ids).fetchall()
        # Desde quando cada parcela aparece em aberto (primeira extração em que surgiu)
        primeira = {
            (r["seguradora"], r["recibo"], r["parcela"]): r["desde"]
            for r in con.execute("""
                SELECT p.seguradora, p.recibo, p.parcela, MIN(x.data) desde
                FROM parcelas p JOIN extracoes x ON x.id = p.extracao_id
                GROUP BY p.seguradora, p.recibo, p.parcela
            """)
        }
        # Extração OK anterior de cada seguradora -> parcelas que saíram da lista
        regularizadas = []
        for nome, ult in ultimas.items():
            ant = con.execute(
                "SELECT id, data FROM extracoes WHERE seguradora=? AND situacao='OK' AND id<?"
                " ORDER BY id DESC LIMIT 1", (nome, ult["id"])).fetchone()
            if not ant:
                continue
            saiu = con.execute("""
                SELECT p.* FROM parcelas p WHERE p.extracao_id = ?
                AND NOT EXISTS (SELECT 1 FROM parcelas q WHERE q.extracao_id = ?
                                AND q.recibo IS p.recibo AND q.parcela IS p.parcela)
            """, (ant["id"], ult["id"])).fetchall()
            for r in saiu:
                d = dict(r)
                d["visto_ate"] = ant["data"]
                regularizadas.append(d)

    saida = []
    for r in atuais:
        d = dict(r)
        d["dias_atraso"] = _dias(d["vencimento"], hoje)
        d["dias_cancelar"] = _dias(d["prev_cancelamento"], hoje, inverso=True)
        d["risco"] = _risco(d["dias_cancelar"], d["dias_atraso"])
        d["aberta_desde"] = primeira.get((d["seguradora"], d["recibo"], d["parcela"]))
        saida.append(d)
    return jsonify({"parcelas": saida, "regularizadas": regularizadas})


# ----------------------------------------------------- rodar o robô pelo site
_robo = {"processo": None, "inicio": None, "log": ""}
_trava = threading.Lock()


def _estado_robo() -> dict:
    p = _robo["processo"]
    rodando = p is not None and p.poll() is None
    return {
        "rodando": rodando,
        "inicio": _robo["inicio"],
        "codigo_saida": None if p is None or rodando else p.returncode,
        "log": _robo["log"][-3000:],
    }


def _acompanhar(p):
    for linha in p.stdout:
        _robo["log"] += linha


@app.post("/api/executar")
@exige_login
def api_executar():
    with _trava:
        if _estado_robo()["rodando"]:
            return jsonify({"ok": False, "mensagem": "O robô já está em execução."}), 409
        p = subprocess.Popen(
            [sys.executable, "-m", "robo"], cwd=config.RAIZ, text=True, encoding="utf-8",
            errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        _robo.update(processo=p, inicio=datetime.now().isoformat(" ", "seconds"), log="")
        threading.Thread(target=_acompanhar, args=(p,), daemon=True).start()
    return jsonify({"ok": True})


@app.get("/api/executar")
@exige_login
def api_estado_robo():
    return jsonify(_estado_robo())


# ------------------------------------------------------------------ páginas
@app.get("/")
@exige_login
def inicio():
    return send_from_directory(PASTA_WEB, "index.html")


def main():
    from waitress import serve

    host = "0.0.0.0" if config.PAINEL_SENHA else "127.0.0.1"
    print(f"Painel em http://localhost:{config.PAINEL_PORTA}")
    if not config.PAINEL_SENHA:
        print("Aviso: PAINEL_SENHA não definida no .env — painel acessível só neste computador.")
    else:
        print("Na rede do escritório: http://<ip-deste-computador>:%d" % config.PAINEL_PORTA)
    serve(app, host=host, port=config.PAINEL_PORTA, threads=4)


if __name__ == "__main__":
    main()
