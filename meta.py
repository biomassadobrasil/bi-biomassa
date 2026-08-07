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

def amostra_leads():
    """Inspeção leads_retrieval: 1 campanha ativa -> ads -> leads com field_data (perfil)."""
    ativas=[c for c in campanhas() if c.get("effective_status")=="ACTIVE"]
    if not ativas: return {"erro":"sem campanhas ativas"}
    cid=ativas[0]["id"]; nome=ativas[0]["name"]
    ads=_get(f"{cid}/ads", {"fields":"id,name","limit":10}).get("data",[])
    out={"campanha":nome,"qtd_ads":len(ads)}
    for a in ads:
        try:
            leads=_get(f"{a['id']}/leads", {"fields":"created_time,campaign_name,ad_name,field_data","limit":3})
            d=leads.get("data",[])
            if d:
                out["ad_com_leads"]=a["name"]
                out["campos_form"]=[f.get("name") for f in d[0].get("field_data",[])]
                out["exemplos"]=[{fd.get("name"):(fd.get("values") or [None])[0] for fd in x.get("field_data",[])}|{"quando":x.get("created_time"),"campanha":x.get("campaign_name")} for x in d]
                return out
        except Exception as e:
            out.setdefault("erros",[]).append(str(e)[:180])
    out["obs"]="nenhum ad retornou leads (ou sem permissão)"
    return out

def leads_diag():
    """Diagnóstico SEM PII: prova se leads_retrieval funciona.
    Retorna nomes dos campos do formulário e a distribuição do campo de PERFIL
    (categorias PF/B2B/segmento — não são dados pessoais). Nenhum nome/telefone/e-mail."""
    ativas=[c for c in campanhas() if c.get("effective_status")=="ACTIVE"]
    if not ativas: return {"ok":False,"erro":"sem campanhas ativas"}
    out={"ok":False,"campanhas":[]}
    campos_perfil=("perfil","segmento","atividade","porte","voce_e","você_é","qual")
    for c in ativas[:3]:
        info={"campanha":c["name"],"leads_lidos":0}
        try:
            ads=_get(f"{c['id']}/ads", {"fields":"id","limit":25}).get("data",[])
        except Exception as e:
            info["erro"]=str(e)[:200]; out["campanhas"].append(info); continue
        campos=set(); dist={}
        for a in ads:
            try:
                after=None
                while True:
                    p={"fields":"field_data","limit":100}
                    if after: p["after"]=after
                    res=_get(f"{a['id']}/leads", p)
                    for lead in res.get("data",[]):
                        info["leads_lidos"]+=1
                        for fd in lead.get("field_data",[]):
                            nm=(fd.get("name") or "").lower(); campos.add(nm)
                            if any(k in nm for k in campos_perfil):
                                v=(fd.get("values") or [None])[0]
                                dist.setdefault(nm,{}); dist[nm][v]=dist[nm].get(v,0)+1
                    after=(res.get("paging",{}).get("cursors",{}) or {}).get("after")
                    if not after or not res.get("data"): break
            except Exception as e:
                info.setdefault("erros",[]).append(str(e)[:160])
        info["campos_form"]=sorted(campos)
        info["distribuicao_perfil"]=dist
        if info["leads_lidos"]>0: out["ok"]=True
        out["campanhas"].append(info)
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
