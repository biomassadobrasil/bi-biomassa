# -*- coding: utf-8 -*-
"""Conector Google Ads API (REST v21, GAQL).
Credenciais via env (GOOGLE_*) no Railway, ou fallback ~/google-ads.yaml no local.
Conta filha real (campanhas) = GOOGLE_CUSTOMER_ID; login = GOOGLE_LOGIN_CUSTOMER_ID (MCC)."""
import os, json, urllib.parse, urllib.request, urllib.error

VER = "v21"
TOKEN_URL = "https://oauth2.googleapis.com/token"

def _cfg():
    """Le config do env; se faltar, tenta o yaml local (dev)."""
    c = {
        "developer_token": os.environ.get("GOOGLE_DEV_TOKEN", ""),
        "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        "refresh_token": os.environ.get("GOOGLE_REFRESH_TOKEN", ""),
        "login_customer_id": os.environ.get("GOOGLE_LOGIN_CUSTOMER_ID", ""),
        "customer_id": os.environ.get("GOOGLE_CUSTOMER_ID", ""),
    }
    if not c["refresh_token"]:
        for p in ("/Users/macbookpro/google-ads.yaml", os.path.expanduser("~/google-ads.yaml")):
            if os.path.exists(p):
                y = {}
                for ln in open(p, encoding="utf-8"):
                    if ":" in ln and not ln.strip().startswith("#"):
                        k, _, v = ln.partition(":"); y[k.strip()] = v.strip().strip('"').strip("'")
                c["developer_token"] = c["developer_token"] or y.get("developer_token", "")
                c["client_id"] = c["client_id"] or y.get("client_id", "")
                c["client_secret"] = c["client_secret"] or y.get("client_secret", "")
                c["refresh_token"] = c["refresh_token"] or y.get("refresh_token", "")
                c["login_customer_id"] = c["login_customer_id"] or y.get("login_customer_id", "")
                c["customer_id"] = c["customer_id"] or "4175096156"
                break
    return c

def _access_token(c):
    body = urllib.parse.urlencode({
        "client_id": c["client_id"], "client_secret": c["client_secret"],
        "refresh_token": c["refresh_token"], "grant_type": "refresh_token"}).encode()
    try:
        return json.load(urllib.request.urlopen(TOKEN_URL, data=body, timeout=60))["access_token"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Google OAuth {e.code}: {e.read().decode()[:200]}")

def _search(gaql):
    """Roda um GAQL na conta filha e devolve todas as linhas (searchStream)."""
    c = _cfg()
    if not c["refresh_token"]: raise RuntimeError("Faltam credenciais Google (env GOOGLE_* ou yaml)")
    at = _access_token(c)
    cust = (c["customer_id"] or "").replace("-", "")
    url = f"https://googleads.googleapis.com/{VER}/customers/{cust}/googleAds:searchStream"
    hdr = {"Authorization": "Bearer " + at, "developer-token": c["developer_token"],
           "Content-Type": "application/json"}
    login = (c["login_customer_id"] or "").replace("-", "")
    if login: hdr["login-customer-id"] = login
    req = urllib.request.Request(url, data=json.dumps({"query": gaql}).encode(), headers=hdr)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Google Ads {e.code}: {e.read().decode()[:300]}")
    rows = []
    for chunk in (data if isinstance(data, list) else [data]):
        rows += chunk.get("results", [])
    return rows

def _dstr(d):  # date -> 'YYYY-MM-DD'
    return d if isinstance(d, str) else d.strftime("%Y-%m-%d")

def campanhas_resumo(desde=None, ate=None):
    """Por campanha ENABLED: leads(conversões), gasto(BRL), impressões, cliques.
    Sem data => últimos 30 dias (DURING LAST_30_DAYS)."""
    where = "campaign.status = 'ENABLED'"
    if desde and ate:
        where += f" AND segments.date BETWEEN '{_dstr(desde)}' AND '{_dstr(ate)}'"
    else:
        where += " AND segments.date DURING LAST_30_DAYS"
    gaql = ("SELECT campaign.id, campaign.name, metrics.impressions, metrics.clicks, "
            "metrics.cost_micros, metrics.conversions FROM campaign WHERE " + where)
    agg = {}
    for r in _search(gaql):
        camp = r.get("campaign", {}); m = r.get("metrics", {})
        cid = str(camp.get("id"))
        a = agg.setdefault(cid, {"id": cid, "nome": camp.get("name", ""),
                                 "impressoes": 0, "cliques": 0, "gasto": 0.0, "leads": 0.0})
        a["impressoes"] += int(m.get("impressions", 0) or 0)
        a["cliques"] += int(m.get("clicks", 0) or 0)
        a["gasto"] += (int(m.get("costMicros", 0) or 0)) / 1e6
        a["leads"] += float(m.get("conversions", 0) or 0)
    out = []
    for a in agg.values():
        a["gasto"] = round(a["gasto"], 2); a["leads"] = round(a["leads"])
        a["cpl"] = round(a["gasto"] / a["leads"], 2) if a["leads"] else 0.0
        out.append(a)
    return sorted(out, key=lambda x: -x["leads"])

def conversoes_por_acao(desde=None, ate=None):
    """Quebra conversões por nome da ação (p/ separar WhatsApp x Formulário), por campanha."""
    where = "campaign.status = 'ENABLED'"
    if desde and ate:
        where += f" AND segments.date BETWEEN '{_dstr(desde)}' AND '{_dstr(ate)}'"
    else:
        where += " AND segments.date DURING LAST_30_DAYS"
    gaql = ("SELECT campaign.id, campaign.name, segments.conversion_action_name, "
            "metrics.conversions FROM campaign WHERE " + where)
    out = {}
    for r in _search(gaql):
        camp = r.get("campaign", {}); seg = r.get("segments", {}); m = r.get("metrics", {})
        cid = str(camp.get("id"))
        acao = seg.get("conversionActionName", "—")
        out.setdefault(cid, {"nome": camp.get("name", ""), "acoes": {}})
        out[cid]["acoes"][acao] = round(out[cid]["acoes"].get(acao, 0) + float(m.get("conversions", 0) or 0))
    return out

def _canal(nome_acao):
    a = (nome_acao or "").lower()
    if "whats" in a or "zap" in a: return "wpp"
    if "form" in a: return "form"
    return "outro"

def leads_diarios(desde, ate):
    """Conversões por campanha/dia/canal (wpp|form) no intervalo — p/ filtro de data e gráfico diário."""
    gaql = ("SELECT campaign.name, segments.date, segments.conversion_action_name, "
            f"metrics.conversions FROM campaign WHERE campaign.status = 'ENABLED' "
            f"AND segments.date BETWEEN '{_dstr(desde)}' AND '{_dstr(ate)}'")
    out = []
    for r in _search(gaql):
        camp = r.get("campaign", {}); seg = r.get("segments", {}); m = r.get("metrics", {})
        n = round(float(m.get("conversions", 0) or 0), 2)
        if not n: continue
        out.append({"c": camp.get("name", ""), "dt": seg.get("date", ""),
                    "ch": _canal(seg.get("conversionActionName")), "n": n})
    return out

if __name__ == "__main__":
    import datetime
    ate = datetime.date.today(); desde = ate - datetime.timedelta(days=29)
    print(json.dumps({"resumo": campanhas_resumo(), "acoes": conversoes_por_acao(),
                      "diario_amostra": leads_diarios(desde, ate)[:5]},
                     ensure_ascii=False, indent=2))
