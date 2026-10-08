# -*- coding: utf-8 -*-
"""B.I Comercial (Bitrix) -> comercial.json. Roda de hora em hora (server.py).
Cada métrica usa a data do próprio evento: negócio = criação, proposta = última proposta do card,
venda = entrada na etapa Ganho (histórico de etapas). Sem dados pessoais de clientes."""
import os, json, datetime, threading, traceback, urllib.parse, unicodedata
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "comercial.json")
SP = ZoneInfo("America/Sao_Paulo")
DESDE = "2026-01-01"                       # histórico considerado (negócios mexidos desde então)
CATS = {"0": "Vendas Internas", "2": "LightWall"}
VEND = {"948": "Patrícia", "38": "Luiz", "890": "Thauany", "16942": "Ingrid", "16812": "Vanessa", "376": "Douglas"}
F_MOTIVO = "UF_CRM_67E591F01CB70"           # "Motivo da Desqualificação" (pedido ao mover p/ Perdido)
_LOCK = threading.Lock()

import generate as G                       # call() do Bitrix + Redis
call = G.call

def _norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(s.split())

def _dt(s):
    """Data/hora do Bitrix (vem com fuso do servidor) -> datetime em São Paulo."""
    if not s: return None
    try: return datetime.datetime.fromisoformat(str(s)).astimezone(SP)
    except Exception: return None

def _d(s):
    x = _dt(s)
    return x.date().isoformat() if x else ""

def _qs(params, prefix=""):
    """dict -> query string no formato do PHP (filter[>=X]=..&select[]=..), p/ o batch do Bitrix."""
    out = []
    for k, v in params.items():
        key = f"{prefix}[{k}]" if prefix else str(k)
        if isinstance(v, dict): out.append(_qs(v, key))
        elif isinstance(v, (list, tuple)):
            for i, x in enumerate(v):
                out.append(_qs(x, f"{key}[{i}]") if isinstance(x, dict) else f"{urllib.parse.quote(key + '[]')}={urllib.parse.quote(str(x))}")
        else: out.append(f"{urllib.parse.quote(key)}={urllib.parse.quote(str(v))}")
    return "&".join(o for o in out if o)

def listar(method, params, pegar=lambda r: r):
    """Lista paginada inteira usando batch (até 50 páginas por requisição)."""
    first = call(method, {**params, "start": 0})
    itens = list(pegar(first.get("result")) or [])
    total = int(first.get("total") or 0)
    starts = list(range(50, total, 50))
    for i in range(0, len(starts), 50):
        cmd = {f"p{s}": f"{method}?{_qs({**params, 'start': s})}" for s in starts[i:i + 50]}
        res = call("batch", {"halt": 0, "cmd": cmd}).get("result", {})
        for s in starts[i:i + 50]:
            itens += list(pegar((res.get("result") or {}).get(f"p{s}")) or [])
    return itens

def _grupo(nome):
    n = _norm(nome)
    if "ganho" in n: return "ganho"
    if "perdido" in n: return "perdido"
    if "negociacao" in n: return "negociacao"
    if "sem retorno" in n: return "semretorno"
    if "renutri" in n: return "renutricao"
    return "outras"

def build():
    # ---- estrutura: etapas, fontes, motivos ----
    etapas, grupo_de = {}, {}
    for c in CATS:
        lst = call("crm.dealcategory.stage.list", {"id": int(c)})["result"]
        etapas[c] = [{"id": s["STATUS_ID"], "nome": s["NAME"], "g": _grupo(s["NAME"])} for s in lst]
        for s in etapas[c]: grupo_de[s["id"]] = s["g"]
    fontes = {str(s["STATUS_ID"]): s["NAME"] for s in call("crm.status.list", {"filter": {"ENTITY_ID": "SOURCE"}})["result"]}
    campos = call("crm.deal.fields", {})["result"]
    motivos = {str(i["ID"]): i["VALUE"] for i in (campos.get(F_MOTIVO, {}).get("items") or [])}

    # ---- negócios (mexidos desde DESDE) ----
    sel = ["ID", "CATEGORY_ID", "STAGE_ID", "OPPORTUNITY", "DATE_CREATE", "DATE_MODIFY", "CLOSEDATE", "ASSIGNED_BY_ID", "SOURCE_ID", F_MOTIVO]
    deals = {}
    for c in CATS:
        for d in listar("crm.deal.list", {"filter": {"CATEGORY_ID": int(c), ">=DATE_MODIFY": DESDE}, "select": sel, "order": {"ID": "ASC"}}):
            deals[str(d["ID"])] = d

    # ---- histórico de etapas: quando entrou em Ganho / Perdido ----
    hist = {}
    for c in CATS:
        for h in listar("crm.stagehistory.list", {"entityTypeId": 2, "filter": {"CATEGORY_ID": int(c), ">=CREATED_TIME": DESDE},
                                                  "select": ["OWNER_ID", "CREATED_TIME", "STAGE_ID"], "order": {"ID": "ASC"}},
                        pegar=lambda r: (r or {}).get("items")):
            hist.setdefault(str(h["OWNER_ID"]), []).append((h["CREATED_TIME"], h["STAGE_ID"]))

    # ---- propostas (documentos gerados no card): fica só a ÚLTIMA de cada card ----
    docs = listar("crm.documentgenerator.document.list", {"select": ["id", "entityId", "createTime", "updateTime", "number"],
                                                          "filter": {"entityTypeId": 2}, "order": {"id": "asc"}},
                  pegar=lambda r: (r or {}).get("documents"))
    por_card = {}
    for x in docs:
        did = str(x.get("entityId"))
        if did not in deals: continue
        por_card.setdefault(did, []).append(x)
    ultimas = {did: max(lst, key=lambda x: (x.get("createTime") or "", int(x["id"]))) for did, lst in por_card.items()}
    valores = {}
    falta = []
    for did, x in ultimas.items():
        key = f"comercial:doc:{x['id']}:{x.get('updateTime')}"
        v = None
        if G._RDS:
            try: v = G._RDS.get(key)
            except Exception: pass
        if v is not None: valores[x["id"]] = float(v)
        else: falta.append((x["id"], key))
    for i in range(0, len(falta), 50):
        lote = falta[i:i + 50]
        res = call("batch", {"halt": 0, "cmd": {f"d{doc}": f"crm.documentgenerator.document.get?id={doc}" for doc, _ in lote}}).get("result", {}).get("result", {})
        for doc, key in lote:
            r = (res.get(f"d{doc}") or {}).get("document", {}) if isinstance(res, dict) else {}
            try: v = float(((r.get("products") or {}).get("totalSum")) or 0)
            except Exception: v = 0.0
            valores[doc] = v
            if G._RDS:
                try: G._RDS.set(key, v)
                except Exception: pass

    # ---- primeiro contato: 1ª ligação (ou e-mail) registrada no card por um vendedor ----
    contato = {}
    for a in listar("crm.activity.list", {"filter": {"OWNER_TYPE_ID": 2, ">=CREATED": DESDE, "@PROVIDER_ID": ["VOXIMPLANT_CALL", "CRM_EMAIL"], "DIRECTION": 2},
                                          "select": ["OWNER_ID", "CREATED", "AUTHOR_ID"], "order": {"ID": "ASC"}}):
        did = str(a["OWNER_ID"])
        t = _dt(a.get("CREATED"))
        if did in deals and t and (did not in contato or t < contato[did]): contato[did] = t

    # ---- monta os negócios (só os 6 vendedores) ----
    out = []
    for did, d in deals.items():
        v = str(d.get("ASSIGNED_BY_ID"))
        if v not in VEND: continue
        st = d.get("STAGE_ID") or ""
        g = grupo_de.get(st, "outras")
        h = sorted(hist.get(did, []))
        won = next((_d(t) for t, s in h if grupo_de.get(s) == "ganho"), "")
        lost = next((_d(t) for t, s in reversed(h) if grupo_de.get(s) == "perdido"), "")
        if g == "ganho" and not won: won = _d(d.get("CLOSEDATE")) or _d(d.get("DATE_MODIFY"))
        if g == "perdido" and not lost: lost = _d(d.get("DATE_MODIFY"))
        if g != "ganho": won = ""                       # reaberto depois de ganho: não conta como venda
        if g != "perdido": lost = ""
        criado = _dt(d.get("DATE_CREATE"))
        try: o = round(float(d.get("OPPORTUNITY") or 0), 2)
        except Exception: o = 0.0
        up = ultimas.get(did)
        fc = contato.get(did)
        out.append({"id": did, "c": str(d["CATEGORY_ID"]), "v": v, "dc": criado.date().isoformat() if criado else "",
                    "o": o, "st": st, "g": g, "src": fontes.get(str(d.get("SOURCE_ID")), "Sem fonte"),
                    "won": won, "lost": lost, "mot": motivos.get(str(d.get(F_MOTIVO) or ""), "") if g == "perdido" else "",
                    "np": len(por_card.get(did, [])), "pd": _d(up.get("createTime")) if up else "",
                    "pv": round(valores.get(up["id"], 0.0), 2) if up else 0.0,
                    # horas até o 1º contato / dias até fechar
                    "fc": round((fc - criado).total_seconds() / 3600, 1) if (fc and criado and fc >= criado) else None,
                    "dias": (datetime.date.fromisoformat(won) - criado.date()).days if (won and criado) else None})

    # ---- ligações por vendedor (telefonia do Bitrix): feitas x atendidas, por dia ----
    lig = {}
    for x in listar("voximplant.statistic.get", {"FILTER": {">=CALL_START_DATE": DESDE, "CALL_TYPE": 1}, "SORT": "CALL_START_DATE", "ORDER": "ASC"}):
        v = str(x.get("PORTAL_USER_ID"))
        if v not in VEND: continue
        k = (_d(x.get("CALL_START_DATE")), v)
        o = lig.setdefault(k, {"d": k[0], "v": v, "n": 0, "ok": 0, "seg": 0})
        o["n"] += 1
        if str(x.get("CALL_FAILED_CODE")) == "200":
            o["ok"] += 1; o["seg"] += int(x.get("CALL_DURATION") or 0)

    return {"gerado_em": datetime.datetime.now(SP).isoformat(timespec="minutes"),
            "hoje": datetime.datetime.now(SP).date().isoformat(), "desde": DESDE,
            "vend": VEND, "pipes": CATS, "etapas": etapas, "deals": out, "ligacoes": list(lig.values())}

def atualizar():
    if not _LOCK.acquire(blocking=False):
        print("[COMERCIAL] já está atualizando, pulando"); return
    try:
        if not os.path.exists(OUT) and G._RDS:          # deploy novo: mostra o último bom enquanto gera
            try:
                c = G._RDS.get("comercial:ultimo")
                if c:
                    with open(OUT, "w", encoding="utf-8") as fp: fp.write(c.decode() if isinstance(c, bytes) else c)
            except Exception: pass
        dados = build()
        tmp = OUT + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fp: json.dump(dados, fp, ensure_ascii=False)
        os.replace(tmp, OUT)
        if G._RDS:
            try: G._RDS.set("comercial:ultimo", json.dumps(dados, ensure_ascii=False))
            except Exception: pass
        print(f"[COMERCIAL] gerado {dados['gerado_em']} — {len(dados['deals'])} negócios, {len(dados['ligacoes'])} dias×vendedor de ligações")
    except Exception:
        print("[COMERCIAL] falhou:\n" + traceback.format_exc())
        if not os.path.exists(OUT) and G._RDS:          # deploy novo: recupera o último bom do Redis
            try:
                c = G._RDS.get("comercial:ultimo")
                if c:
                    with open(OUT, "w", encoding="utf-8") as fp: fp.write(c.decode() if isinstance(c, bytes) else c)
            except Exception: pass
    finally:
        _LOCK.release()

if __name__ == "__main__":
    atualizar()
