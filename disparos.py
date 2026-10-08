# -*- coding: utf-8 -*-
"""B.I Disparos (WhatsApp) -> disparos.json. Roda de hora em hora (server.py).
Fontes: Meta (conta do WhatsApp Business: envios/custo por categoria e, se os insights de modelo
estiverem ligados, por modelo), BioZap (Redis: quem recebeu/respondeu o disparo automático) e
os negócios do Bitrix (comercial.json). Sem dados pessoais: telefones nunca saem daqui."""
import os, json, datetime, threading, traceback, urllib.request, urllib.parse, urllib.error
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "disparos.json")
SP = ZoneInfo("America/Sao_Paulo")
WABA = os.environ.get("WHATSAPP_WABA_ID", "413003979330290")   # conta "Biomassa do Brasil" (+55 11 94722-6372)
DIAS = 180
GRAPH = "https://graph.facebook.com/v21.0"
FONTES_DISPARO = ("disparo", "biozap")        # fontes do Bitrix que vêm de disparo
_LOCK = threading.Lock()

try:
    from generate import _RDS
except Exception:
    _RDS = None

def _get(path, params):
    tok = os.environ.get("META_TOKEN", "")
    if not tok: raise RuntimeError("Falta META_TOKEN")
    url = f"{GRAPH}/{path}?{urllib.parse.urlencode({**params, 'access_token': tok})}"
    try:
        with urllib.request.urlopen(url, timeout=90) as r: return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try: err = json.loads(body).get("error", {})
        except Exception: err = {"message": body[:200]}
        raise RuntimeError(err.get("error_data") or err.get("message") or str(e.code))

def _dia(ts):
    return datetime.datetime.fromtimestamp(int(ts), SP).date().isoformat()

def build_meta():
    fim = int(datetime.datetime.now(SP).timestamp()); ini = fim - DIAS * 86400
    # modelos (nome, categoria, texto, botões)
    modelos = []
    for t in _get(f"{WABA}/message_templates", {"fields": "id,name,status,category,language,components", "limit": 200}).get("data", []):
        comp = t.get("components", [])
        corpo = next((c.get("text", "") for c in comp if c.get("type") == "BODY"), "")
        botoes = [b.get("text") for c in comp if c.get("type") == "BUTTONS" for b in c.get("buttons", [])]
        modelos.append({"id": t["id"], "nome": t["name"], "cat": t.get("category"), "status": t.get("status"),
                        "texto": corpo, "botoes": botoes})
    # envios e custo por dia e categoria (cobrança da Meta)
    diario = {}
    r = _get(WABA, {"fields": f'pricing_analytics.start({ini}).end({fim}).granularity(DAILY).dimensions(["PRICING_CATEGORY"])'})
    for blk in (r.get("pricing_analytics") or {}).get("data", []):
        for p in blk.get("data_points", []):
            d = _dia(p["start"]); cat = p.get("pricing_category")
            o = diario.setdefault(d, {"d": d, "mk": 0, "ut": 0, "sv": 0, "cmk": 0.0, "cut": 0.0, "csv": 0.0})
            k = {"MARKETING": "mk", "UTILITY": "ut", "SERVICE": "sv"}.get(cat)
            if not k: continue
            o[k] += int(p.get("volume") or 0); o["c" + k] = round(o["c" + k] + float(p.get("cost") or 0), 4)
    # por modelo (só se os insights de modelo estiverem ligados na conta)
    por_modelo, insights = [], False
    try:
        ini_t = fim - 89 * 86400        # a Meta limita a ~90 dias
        for i in range(0, len(modelos), 10):
            lote = modelos[i:i + 10]
            r = _get(f"{WABA}/template_analytics", {"start": ini_t, "end": fim, "granularity": "DAILY",
                     "template_ids": json.dumps([m["id"] for m in lote]), "metric_types": json.dumps(["SENT", "DELIVERED", "READ", "CLICKED", "COST"])})
            nome = {m["id"]: m["nome"] for m in lote}
            for blk in r.get("data", []):
                for p in blk.get("data_points", []):
                    cl = sum(c.get("count", 0) for c in (p.get("clicked") or []))
                    cu = sum(c.get("value", 0) for c in (p.get("cost") or []) if c.get("type") == "amount_spent")
                    if not (p.get("sent") or cl or cu): continue
                    por_modelo.append({"t": nome.get(p.get("template_id"), p.get("template_id")), "d": _dia(p["start"]),
                                       "s": p.get("sent", 0), "e": p.get("delivered", 0), "l": p.get("read", 0), "k": cl, "c": round(cu, 4)})
        insights = True
    except Exception as e:
        if "not been enabled" not in str(e): print("[DISPAROS] template_analytics:", str(e)[:200])
    info = _get(WABA, {"fields": "currency"})
    return {"moeda": info.get("currency", "USD"), "modelos": modelos, "diario": sorted(diario.values(), key=lambda x: x["d"]),
            "por_modelo": por_modelo, "insights": insights}

def build_biozap(deals_por_id):
    """Disparos automáticos registrados pelo BioZap: quem recebeu (campanha), respondeu e qual negócio virou."""
    if not _RDS: return {"campanhas": [], "ok": False}
    rx = lambda b: b.decode("utf-8", "replace") if isinstance(b, bytes) else (b or "")
    camp_de, resp = {}, set()
    for k in _RDS.scan_iter("campanhaDisparo:*", count=1000):
        camp_de[rx(k).split(":", 1)[1]] = rx(_RDS.get(k))
    for k in _RDS.scan_iter("bi:disparoRespondido:*", count=1000):
        partes = rx(k).split(":")
        if len(partes) >= 4: resp.add((partes[2], partes[3]))
    deal_de = {}
    for k in _RDS.scan_iter("dealOrigem:*", count=1000):
        deal_de[rx(k).split(":", 1)[1]] = rx(_RDS.get(k))
    agg = {}
    for tel, camp in camp_de.items():
        o = agg.setdefault(camp, {"nome": camp, "env": 0, "resp": 0, "deals": []})
        o["env"] += 1
        if (camp, tel) in resp: o["resp"] += 1
        did = deal_de.get(tel)
        if did and did in deals_por_id: o["deals"].append(did)
    return {"campanhas": list(agg.values()), "ok": True}

def build():
    # negócios do Bitrix já levantados pelo B.I Comercial
    try:
        with open(os.path.join(HERE, "comercial.json"), encoding="utf-8") as fp: com = json.load(fp)
    except Exception:
        com = {"deals": [], "vend": {}}
    deals_por_id = {d["id"]: d for d in com.get("deals", [])}
    bz = build_biozap(deals_por_id)
    ids_bz = {i for c in bz["campanhas"] for i in c["deals"]}
    negocios = [{"id": d["id"], "dc": d["dc"], "won": d["won"], "lost": d["lost"], "o": d["o"], "np": d["np"], "v": d["v"], "src": d["src"],
                 "bz": d["id"] in ids_bz}
                for d in com.get("deals", []) if any(t in d["src"].lower() for t in FONTES_DISPARO) or d["id"] in ids_bz]
    try:
        meta = build_meta(); meta["ok"] = True
    except Exception as e:
        print("[DISPAROS] Meta falhou:\n" + traceback.format_exc())
        meta = {"ok": False, "erro": str(e)[:200], "modelos": [], "diario": [], "por_modelo": [], "insights": False}
    agora = datetime.datetime.now(SP)
    return {"gerado_em": agora.isoformat(timespec="minutes"), "hoje": agora.date().isoformat(),
            "meta": meta, "biozap": bz, "negocios": negocios, "vend": com.get("vend", {})}

def atualizar():
    if not _LOCK.acquire(blocking=False): return
    try:
        dados = build()
        tmp = OUT + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fp: json.dump(dados, fp, ensure_ascii=False)
        os.replace(tmp, OUT)
        print(f"[DISPAROS] gerado {dados['gerado_em']} — {len(dados['meta']['diario'])} dias, insights={dados['meta']['insights']}, {len(dados['negocios'])} negócios")
    except Exception:
        print("[DISPAROS] falhou:\n" + traceback.format_exc())
    finally:
        _LOCK.release()

if __name__ == "__main__":
    atualizar()
