# -*- coding: utf-8 -*-
"""Serve o B.I e regenera sozinho às 08:00 e 12:30 (America/Sao_Paulo)."""
import os, json, threading, traceback
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, Response
from apscheduler.schedulers.background import BackgroundScheduler
import generate

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "index.html")
app = Flask(__name__)

def regenerar():
    try:
        generate.run()
    except Exception:
        print("[BI] erro ao gerar:\n" + traceback.format_exc())

@app.route("/")
def home():
    if not os.path.exists(INDEX):
        return "Gerando o B.I pela primeira vez, recarregue em instantes…", 503
    return Response(open(INDEX, encoding="utf-8").read(), mimetype="text/html")

@app.route("/health")
def health():
    return "ok", 200

@app.route("/atualizar")
def atualizar():
    regenerar()
    return "Atualizado.", 200

@app.route("/_tinyprop")
def _tinyprop():
    import tiny
    out={}
    cands=["propostas.comerciais.pesquisa.php","proposta.comercial.pesquisa.php",
           "propostas.pesquisa.php","proposta.pesquisa.php","orcamentos.pesquisa.php"]
    for ep in cands:
        try:
            r=tiny.raw(ep,{"pagina":1}).get("retorno",{})
            info={"status":r.get("status")}
            if r.get("erros"): info["erros"]=r.get("erros")
            # descobre a chave de lista e campos
            for k,v in r.items():
                if isinstance(v,list) and v:
                    item=v[0].get(list(v[0].keys())[0]) if isinstance(v[0],dict) else v[0]
                    info["lista_key"]=k
                    info["campos"]=sorted(item.keys()) if isinstance(item,dict) else str(item)[:100]
                    break
            out[ep]=info
        except Exception as e:
            out[ep]={"exc":str(e)[:150]}
    return Response(json.dumps(out,ensure_ascii=False,indent=2),mimetype="application/json")

# agenda 08:00 e 12:30 no horário de São Paulo
tz = ZoneInfo("America/Sao_Paulo")
sched = BackgroundScheduler(timezone=tz)
sched.add_job(regenerar, "cron", hour=8, minute=0)
sched.add_job(regenerar, "cron", hour=12, minute=30)
sched.start()

# gera na subida (em thread pra não travar o boot do Railway)
threading.Thread(target=regenerar, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
