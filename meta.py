# -*- coding: utf-8 -*-
"""Conector Meta Marketing API (Graph). Token em env META_TOKEN, conta em META_AD_ACCOUNT."""
import os, json, urllib.parse, urllib.request, urllib.error

VER = "v21.0"
BASE = f"https://graph.facebook.com/{VER}"

def _acct():
    a = (os.environ.get("META_AD_ACCOUNT") or "").strip()
    if a and not a.startswith("act_"): a = "act_" + a
    return a

def _get(path, params):
    token = os.environ.get("META_TOKEN", "")
    if not token: raise RuntimeError("Falta META_TOKEN")
    q = {"access_token": token, **params}
    url = f"{BASE}/{path}?{urllib.parse.urlencode(q)}"
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"Meta {e.code} em {path}: {body}")

def campanhas():
    """Lista campanhas com status (ACTIVE/PAUSED)."""
    out=[]; after=None
    while True:
        p={"fields":"id,name,effective_status","limit":200}
        if after: p["after"]=after
        res=_get(f"{_acct()}/campaigns", p)
        out+=res.get("data",[])
        after=(res.get("paging",{}).get("cursors",{}) or {}).get("after")
        if not after or not res.get("data"): break
    return out

def insights(date_preset="maximum"):
    """Insights por campanha (histórico). Traz actions (onde ficam os leads)."""
    out=[]; after=None
    while True:
        p={"level":"campaign","date_preset":date_preset,
           "fields":"campaign_id,campaign_name,spend,impressions,clicks,actions","limit":200}
        if after: p["after"]=after
        res=_get(f"{_acct()}/insights", p)
        out+=res.get("data",[])
        after=(res.get("paging",{}).get("cursors",{}) or {}).get("after")
        if not after or not res.get("data"): break
    return out

def resumo_ativas():
    """Campanhas ATIVAS com leads (métrica 'lead'), gasto, impressões, cliques."""
    ids={c["id"]:c["name"] for c in campanhas() if c.get("effective_status")=="ACTIVE"}
    ins=insights()
    out=[]
    for i in ins:
        cid=i.get("campaign_id")
        if cid not in ids: continue
        acts={a["action_type"]:float(a["value"]) for a in (i.get("actions") or [])}
        leads=acts.get("lead") or acts.get("onsite_conversion.lead_grouped") or acts.get("offsite_complete_registration_add_meta_leads") or 0
        out.append({"nome":ids[cid],"leads":int(leads),
                    "gasto":round(float(i.get("spend") or 0),2),
                    "impressoes":int(i.get("impressions") or 0),
                    "cliques":int(i.get("clicks") or 0)})
    return sorted(out,key=lambda x:-x["leads"])

def amostra():
    """Inspeção: campanhas ativas + suas actions (p/ casar com o nº de leads)."""
    camps=campanhas()
    ativas=[c for c in camps if c.get("effective_status")=="ACTIVE"]
    ativ_ids={c["id"] for c in ativas}
    ins=insights()
    by_id={i.get("campaign_id"):i for i in ins}
    detalhe=[]
    for c in ativas:
        i=by_id.get(c["id"],{})
        acts={a["action_type"]:a["value"] for a in (i.get("actions") or [])}
        detalhe.append({"nome":c["name"],"impressoes":i.get("impressions"),"cliques":i.get("clicks"),
                        "gasto":i.get("spend"),"actions":acts})
    return {"conta":_acct(),"ativas":detalhe}
