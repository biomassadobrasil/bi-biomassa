# -*- coding: utf-8 -*-
"""Serve o B.I e regenera sozinho às 08:00 e 12:30 (America/Sao_Paulo)."""
import os, json, threading, traceback
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, Response, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
import generate
import trafego
import comercial

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

def regenerar_trafego():
    try:
        trafego.atualizar()
    except Exception:
        print("[TRAFEGO] erro ao gerar:\n" + traceback.format_exc())

@app.route("/trafego.json")
def trafego_json():
    if not os.path.exists(trafego.OUT):
        return jsonify({"carregando": True}), 503
    r = Response(open(trafego.OUT, encoding="utf-8").read(), mimetype="application/json")
    r.headers["Cache-Control"] = "no-store"
    return r

_alc_cache = {}
@app.route("/api/trafego/alcance")
def trafego_alcance():
    """Alcance da Meta num período personalizado (não dá pra somar dia a dia)."""
    ini, fim = request.args.get("ini", ""), request.args.get("fim", "")
    camps = [c for c in request.args.get("camps", "").split(",") if c.isdigit()]
    try:
        datetime.strptime(ini, "%Y-%m-%d"); datetime.strptime(fim, "%Y-%m-%d")
    except ValueError:
        return jsonify({"erro": "datas inválidas"}), 400
    key = (ini, fim, tuple(camps), datetime.now().strftime("%Y%m%d%H"))
    if key not in _alc_cache:
        try: _alc_cache[key] = trafego.alcance_meta(ini, fim, camps or None)
        except Exception as e: return jsonify({"erro": str(e)[:200]}), 502
    return jsonify(_alc_cache[key])

def regenerar_comercial():
    try:
        comercial.atualizar()
    except Exception:
        print("[COMERCIAL] erro ao gerar:\n" + traceback.format_exc())

@app.route("/comercial.json")
def comercial_json():
    if not os.path.exists(comercial.OUT):
        return jsonify({"carregando": True}), 503
    r = Response(open(comercial.OUT, encoding="utf-8").read(), mimetype="application/json")
    r.headers["Cache-Control"] = "no-store"
    return r

@app.route("/trafego/atualizar")
def trafego_atualizar():
    regenerar_trafego()
    return "Tráfego Pago atualizado.", 200

# agenda 08:00 e 12:30 no horário de São Paulo
tz = ZoneInfo("America/Sao_Paulo")
sched = BackgroundScheduler(timezone=tz)
sched.add_job(regenerar, "cron", hour=8, minute=0)
sched.add_job(regenerar, "cron", hour=12, minute=30)
sched.add_job(regenerar_trafego, "cron", minute=5)    # Tráfego Pago: de hora em hora
sched.add_job(regenerar_comercial, "cron", minute=25) # Comercial: de hora em hora
sched.start()

# gera na subida (em thread pra não travar o boot do Railway)
threading.Thread(target=regenerar, daemon=True).start()
threading.Thread(target=regenerar_trafego, daemon=True).start()
threading.Thread(target=regenerar_comercial, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
