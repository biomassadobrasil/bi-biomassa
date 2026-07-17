# -*- coding: utf-8 -*-
"""Puxa o Bitrix, remonta os números e injeta no template -> index.html.
Webhook lido de env BI_WEBHOOK (mantém o segredo fora do código)."""
import os, json, unicodedata, datetime, urllib.request
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
B = os.environ.get("BI_WEBHOOK", "").rstrip("/")
CATS = {"0":"Vendas | B2B","20":"Vendas | PF","16":"Prospecção Ativa","2":"LightWall"}
ORDER = ["0","2","20","16"]
F_ATIV="UF_CRM_6930463B0F0DE"; F_PROD="UF_CRM_1765205924"
PERFIL_FIELDS=["UF_CRM_68124F377432A","UF_CRM_67E591EFC1321","UF_CRM_1780594237","UF_CRM_6930463B0F0DE"]
VEND_NOMES={"948":"Patrícia","890":"Thauany","38":"Luiz Gomes","14":"Luis Araujo"}

def call(method, payload):
    req=urllib.request.Request(f"{B}/{method}.json", data=json.dumps(payload).encode(),
                               headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=90) as r: return json.load(r)

def norm(s):
    s=(s or "").strip().lower()
    return "".join(c for c in unicodedata.normalize("NFD",s) if unicodedata.category(c)!="Mn")

def fetch_all():
    # etapas
    stages={}
    for c in ORDER:
        stages[c]=call("crm.dealcategory.stage.list",{"id":int(c)})["result"]
    # fontes
    sources={}
    for s in call("crm.status.list",{"filter":{"ENTITY_ID":"SOURCE"}})["result"]:
        sources[str(s["STATUS_ID"])]=s["NAME"]
    # enum maps p/ perfil/tipocli/area
    f=call("crm.deal.fields",{})["result"]
    def items(uf):
        it=f.get(uf,{}).get("items")
        return {str(i["ID"]):i["VALUE"] for i in it} if it else None
    enum_by_uf={"UF_CRM_68124F377432A":items("UF_CRM_68124F377432A"),
                "UF_CRM_67E591EFC1321":items("UF_CRM_67E591EFC1321"),
                "UF_CRM_1780594237":items("UF_CRM_1780594237")}
    # negócios
    SELECT=["ID","CATEGORY_ID","STAGE_ID","STAGE_SEMANTIC_ID","OPPORTUNITY","DATE_CREATE",
            "DATE_MODIFY","CLOSEDATE","ASSIGNED_BY_ID","SOURCE_ID","COMPANY_ID","CONTACT_ID",
            F_ATIV,F_PROD,"UF_CRM_68124F377432A","UF_CRM_67E591EFC1321","UF_CRM_1780594237"]
    deals=[]
    for c in ORDER:
        start=0
        while True:
            res=call("crm.deal.list",{"filter":{"CATEGORY_ID":int(c)},"select":SELECT,"start":start,"order":{"ID":"ASC"}})
            deals.extend(res.get("result",[]))
            if res.get("next") is None: break
            start=res["next"]
    # clientes (empresa/contato)
    coIds=sorted({str(d["COMPANY_ID"]) for d in deals if str(d.get("COMPANY_ID") or "0")!="0"})
    ctIds=sorted({str(d["CONTACT_ID"]) for d in deals if str(d.get("CONTACT_ID") or "0")!="0"})
    def names(method, ids, fields, fmt):
        m={}
        for i in range(0,len(ids),50):
            res=call(method,{"filter":{"ID":ids[i:i+50]},"select":["ID"]+fields})
            for x in res.get("result",[]): m[str(x["ID"])]=fmt(x)
        return m
    companies=names("crm.company.list",coIds,["TITLE"],lambda x:(x.get("TITLE") or "").strip() or f"Empresa #{x['ID']}")
    contacts=names("crm.contact.list",ctIds,["NAME","LAST_NAME"],
                   lambda x:(" ".join(t for t in [x.get("NAME"),x.get("LAST_NAME")] if t)).strip() or f"Contato #{x['ID']}")
    for d in deals:
        co=str(d.get("COMPANY_ID") or "0"); ct=str(d.get("CONTACT_ID") or "0")
        d["_CLI"]= companies.get(co) if (co!="0" and co in companies) else (contacts.get(ct) if (ct!="0" and ct in contacts) else "— sem cliente")
    return stages, sources, enum_by_uf, deals

def build(stages, sources, enum_by_uf, deals):
    def resolve_perfil(d):
        for uf in PERFIL_FIELDS:
            raw=str(d.get(uf) or "").strip()
            if not raw: continue
            m=enum_by_uf.get(uf); lbl=m.get(raw) if m else raw
            if lbl: return lbl
        return None
    def vend(uid): return VEND_NOMES.get(str(uid),"Outros vendedores")
    def fonte(sid):
        n=norm(sources.get(str(sid),(sid or "")))
        if not n: return "Sem fonte"
        if "feicon" in n: return "Feicon"
        if "google ads" in n: return "Google Ads"
        if "prospec" in n: return "Prospecção Ativa"
        if "expo" in n: return "Expo Offsite"
        if "recorrent" in n: return "Vendas Recorrentes"
        if "cross" in n: return "Cross-selling"
        if "loja biomassa" in n: return "Loja Biomassa"
        if n=="site": return "Site"
        if any(x in n for x in ["whats","zap","biomassito","botconversa","instagram"]): return "WhatsApp"
        if "existente" in n: return "Cliente Existente"
        if "tiny" in n: return "Propostas Tiny"
        if "metaads" in n or "meta ads" in n or "formulario de crm" in n: return "Meta Ads"
        if "chamada" in n: return "Chamada"
        return "Outro"
    def tipo_bucket(raw):
        t=norm(raw)
        if not t: return None
        if "empresa de aplica" in t: return "Empresa de Aplicação"
        if "aplica" in t: return "Aplicador"
        if "incorporad" in t: return "Incorporadora"
        if "empreiteir" in t: return "Empreiteira"
        if "amplia" in t: return "CNPJ (Ampliação)"
        if any(x in t for x in ["material","loja","matcon","homecenter","revenda","distribuidora","varejista"]): return "Matcon"
        if "industri" in t or "fabric" in t: return "Indústria/Fábrica"
        if "arquitet" in t or "designer" in t or "engenheir" in t: return "Arquiteto"
        if "constr" in t: return "Construtora"
        if "reforma" in t: return "CNPJ"
        if any(x in t for x in ["cnpj","pessoa juridica","juridic"," pj"]) or t=="pj": return "CNPJ"
        if any(x in t for x in ["pessoa fisica","fisica","consumidor final"]): return "Pessoa Física"
        return "Outro"
    def prod_bucket(raw):
        t=norm(raw)
        if not t: return None
        if "cimento queimado" in t or "kit cimento" in t or "piso cimento" in t: return "Cimento Queimado"
        if "reboco" in t: return "Reboco Pronto"
        if "tinta emborrachada" in t: return "Tinta Emborrachada"
        if "biotherm" in t: return "Biotherm (tinta térmica)"
        if "borracha l" in t: return "Borracha Líquida"
        if "biotop" in t or "impermeab" in t or "aditivo" in t: return "Biotop / Impermeabilizante"
        if "textura" in t or "biorevest" in t or "acabamento" in t: return "Texturas / Acabamentos"
        if any(x in t for x in ["argamassa","polimer","massa pronta","massa polim","assentamento","bisnaga"]): return "Argamassa Polimérica"
        if "biomassa" in t: return "Biomassa (genérico)"
        if any(x in t for x in ["interesse","oferta","disparo","feicon","re-engaj","qualificac","respondeu","format"]): return None
        return "Outro"
    stg_sort={}
    for cat,lst in stages.items():
        for i,s in enumerate(lst): stg_sort[(str(cat),s["NAME"])]=int(s.get("SORT") or i*10)
    def wlo(d):
        sem=d.get("STAGE_SEMANTIC_ID"); cat=str(d["CATEGORY_ID"])
        if cat=="2":
            if sem=="S": return "lost"
            if sem=="F": return "won"
        return {"S":"won","F":"lost"}.get(sem,"open")
    def stage_name(d):
        for s in stages.get(str(d["CATEGORY_ID"])) or []:
            if s["STATUS_ID"]==d["STAGE_ID"]: return s["NAME"]
        return d["STAGE_ID"]
    # canon cliente
    freq=Counter(d.get("_CLI") or "" for d in deals); grp=defaultdict(list)
    for nome in freq:
        if nome: grp[norm(nome)].append(nome)
    def score(v):
        return (1 if (any(c.islower() for c in v) and any(c.isupper() for c in v)) else 0,
                1 if any(ord(c)>127 for c in v) else 0, freq[v])
    canon={k:max(vs,key=score) for k,vs in grp.items()}
    def cli_canon(nome): return canon.get(norm(nome),nome) if nome else "— sem cliente"

    recs=[]
    for d in deals:
        cat=str(d["CATEGORY_ID"])
        if cat not in CATS: continue
        try: opp=float(d.get("OPPORTUNITY") or 0)
        except: opp=0.0
        dc=d.get("DATE_CREATE","") or ""; cd=d.get("CLOSEDATE","") or ""; dm=d.get("DATE_MODIFY","") or ""
        st=wlo(d)
        recs.append({"c":cat,"st":stage_name(d),"w":st,"o":round(opp,2),
            "dt":dc[:10],"mt":dm[:10],
            "wd":cd[:7] if (st=="won" and len(cd)>=7) else "",
            "cld":cd[:10] if (st=="won" and len(cd)>=10) else "",
            "src":fonte(d.get("SOURCE_ID")),"vd":vend(d.get("ASSIGNED_BY_ID")),
            "cli":cli_canon(d.get("_CLI")),
            "pr":prod_bucket(d.get(F_PROD)) or "— não informado",
            "tp":tipo_bucket(resolve_perfil(d)) or "— não informado"})
    def opts(key):
        c=Counter(r[key] for r in recs)
        return [k for k,_ in sorted(c.items(), key=lambda x:(-x[1],x[0]))]
    stg_global=[]
    for c in ORDER:
        for n in sorted(set(r["st"] for r in recs if r["c"]==c), key=lambda n:stg_sort.get((c,n),999)):
            if n not in stg_global: stg_global.append(n)
    datas=sorted([r["dt"] for r in recs if r["dt"]]+[r["mt"] for r in recs if r["mt"]])
    return {"catNames":CATS,"order":ORDER,
        "stgOrder":{c:sorted(set(r["st"] for r in recs if r["c"]==c),key=lambda n:stg_sort.get((c,n),999)) for c in ORDER},
        "recs":recs,
        "opt":{"src":opts("src"),"vd":opts("vd"),"pr":opts("pr"),"tp":opts("tp"),"st":stg_global},
        "dmin":datas[0] if datas else "","dmax":datas[-1] if datas else ""}

def build_tiny():
    """Puxa pedidos do Tiny (v2) e agrega. Retorna None se não houver TINY_TOKEN/erro."""
    if not os.environ.get("TINY_TOKEN"): return None
    import tiny
    desde=os.environ.get("TINY_DESDE","01/01/2026")
    ate=datetime.datetime.now().strftime("%d/%m/%Y")
    pedidos=[]; pagina=1
    while True:
        res=tiny.pesquisa_pedidos(pagina=pagina, data_inicial=desde, data_final=ate)
        ret=res.get("retorno",{})
        if ret.get("status")!="OK": break
        for p in ret.get("pedidos",[]): pedidos.append(p["pedido"])
        npag=int(ret.get("numero_paginas") or 1)
        if pagina>=npag or pagina>=300: break
        pagina+=1
    def val(p):
        try: return float(p.get("valor") or 0)
        except: return 0.0
    # pedidos em formato filtrável no front (SEM juntar clientes — cada cadastro fica separado)
    peds=[]
    for p in pedidos:
        d=p.get("data_pedido","")  # DD/MM/AAAA
        peds.append({
            "cli":(p.get("nome") or "").strip() or "— sem cliente",
            "v":round(val(p),2),
            "st":(p.get("situacao") or "—").strip(),
            "vd":(p.get("nome_vendedor") or "").strip() or "— sem vendedor",
            "ym": d[6:10]+"-"+d[3:5] if len(d)==10 else "",
            "canc": 1 if "cancel" in norm(p.get("situacao")) else 0,
            # região preenchida na Etapa B (detalhe do pedido)
            "uf_fat":"", "uf_ent":"",
        })
    vends=sorted({p["vd"] for p in peds})
    return {"desde":desde,"ate":ate,"peds":peds,"vendedores":vends}

def run():
    if not B: raise SystemExit("Falta a variável de ambiente BI_WEBHOOK")
    stages,sources,enum_by_uf,deals=fetch_all()
    payload=build(stages,sources,enum_by_uf,deals)
    try:
        payload["tiny"]=build_tiny()
    except Exception as e:
        import traceback; print("[BI] Tiny falhou (segue sem):\n"+traceback.format_exc()); payload["tiny"]=None
    tpl=open(os.path.join(HERE,"template.html"),encoding="utf-8").read()
    hoje=datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    html=tpl.replace("__DATA__", json.dumps(payload,ensure_ascii=False)).replace("__GENDATE__", hoje)
    with open(os.path.join(HERE,"index.html"),"w",encoding="utf-8") as fp: fp.write(html)
    print(f"[BI] gerado {hoje} — {len(payload['recs'])} negócios")

if __name__=="__main__":
    run()
