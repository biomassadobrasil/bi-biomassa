# -*- coding: utf-8 -*-
"""Conector Meta Marketing API (Graph). Token em env META_TOKEN, conta em META_AD_ACCOUNT."""
import os, json, urllib.parse, urllib.request

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
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)

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

def amostra():
    """Inspeção: campanhas ativas + tipos de 'action' disponíveis (p/ achar o lead)."""
    camps=campanhas()
    ativas=[c for c in camps if c.get("effective_status")=="ACTIVE"]
    ins=insights()
    # tipos de action que aparecem (p/ identificar o de lead)
    tipos=set()
    for i in ins:
        for a in i.get("actions",[]) or []: tipos.add(a.get("action_type"))
    return {"conta":_acct(),"total_campanhas":len(camps),"ativas":[{"id":c["id"],"nome":c["name"]} for c in ativas],
            "action_types_encontrados":sorted(tipos),
            "exemplo_insight":ins[0] if ins else None}
