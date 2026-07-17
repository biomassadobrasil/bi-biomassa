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

@app.route("/tiny-debug")
def tiny_debug():
    """Inspeção do formato do Tiny (uso interno, temporário)."""
    try:
        import tiny
        return Response(json.dumps(tiny.amostra(), ensure_ascii=False, indent=2),
                        mimetype="application/json")
    except Exception as e:
        import traceback
        return Response("ERRO: "+str(e)+"\n\n"+traceback.format_exc(), mimetype="text/plain"), 500

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
