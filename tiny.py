# -*- coding: utf-8 -*-
"""Conector Tiny API v2 (token simples) + módulo do B.I Tiny (vendas) -> tiny.json.
Token lido de env TINY_TOKEN. Roda de hora em hora (server.py)."""
import os, json, urllib.parse, urllib.request, datetime, threading, traceback, unicodedata, time
from zoneinfo import ZoneInfo

BASE = "https://api.tiny.com.br/api2"

def _get(endpoint, params):
    token = os.environ.get("TINY_TOKEN", "")
    if not token:
        raise RuntimeError("Falta a variável de ambiente TINY_TOKEN")
    q = {"token": token, "formato": "json", **params}
    url = f"{BASE}/{endpoint}?{urllib.parse.urlencode(q)}"
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)

def pesquisa_pedidos(pagina=1, data_inicial=None, data_final=None, extra=None):
    """pedidos.pesquisa.php — lista de pedidos (100/página)."""
    params = {"pagina": pagina}
    if data_inicial: params["dataInicial"] = data_inicial   # DD/MM/AAAA
    if data_final:   params["dataFinal"]   = data_final
    if extra: params.update(extra)
    return _get("pedidos.pesquisa.php", params)

def pedido_obter(pedido_id):
    """pedido.obter.php — detalhe do pedido, com itens/produtos."""
    return _get("pedido.obter.php", {"id": pedido_id})

def raw(endpoint, params=None):
    """Chamada crua a um endpoint da API v2 (diagnóstico)."""
    return _get(endpoint, params or {})

def amostra_item():
    """Pega 1 pedido e mostra os campos dos itens (p/ montar produtos/ABC)."""
    res = pesquisa_pedidos(pagina=1)
    peds = res.get("retorno",{}).get("pedidos",[])
    if not peds: return {"erro":"sem pedidos"}
    pid = peds[0]["pedido"]["id"]
    det = pedido_obter(pid).get("retorno",{})
    ped = det.get("pedido",{})
    itens = ped.get("itens",[])
    campos = sorted(itens[0]["item"].keys()) if itens else []
    return {"status":det.get("status"),"pedido_id":pid,"qtd_itens":len(itens),
            "campos_item":campos,"exemplos":[i.get("item") for i in itens[:3]]}

def amostra():
    """Retorna a 1ª página + os nomes dos campos de um pedido (p/ inspeção)."""
    res = pesquisa_pedidos(pagina=1)
    ret = res.get("retorno", {})
    pedidos = ret.get("pedidos", [])
    campos = sorted(pedidos[0]["pedido"].keys()) if pedidos else []
    return {
        "status": ret.get("status"),
        "status_processamento": ret.get("status_processamento"),
        "erros": ret.get("erros"),
        "numero_paginas": ret.get("numero_paginas"),
        "qtd_na_pagina": len(pedidos),
        "campos_de_um_pedido": campos,
        "exemplos": [p["pedido"] for p in pedidos[:3]],
    }

# ====================== B.I Tiny (vendas) → tiny.json ======================
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "tiny.json")
SP = ZoneInfo("America/Sao_Paulo")
DESDE = "2026-01-01"                        # janela de histórico (cobre todos os presets de data)
_LOCK = threading.Lock()

# equipes (segmentação pedida pelo Alex): Vendas Internas × LightWall × Outros.
# "Outros" mantém o nome real do vendedor (o Alex quer enxergar quem são).
EQUIPES = {"Vendas Internas": "Vendas Internas", "LightWall": "LightWall", "Outros": "Outros"}

def _norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(s.split())

def _classifica_vendedor(nome):
    """nome do Tiny -> (rótulo curto, equipe). Os 5 nomeados; o resto fica com o nome real em 'Outros'."""
    n = _norm(nome)
    if "vanessa" in n: return "Vanessa", "Vendas Internas"
    if "thauany" in n: return "Thauany", "Vendas Internas"
    if "ingrid" in n: return "Ingrid", "Vendas Internas"
    if "gualdiano" in n or "patricia" in n: return "Patrícia", "LightWall"
    if "luiz" in n or "gomes" in n: return "Luiz", "LightWall"
    return (nome or "—").strip(), "Outros"

def _grupo_situacao(sit):
    """Agrupa a situação do Tiny. 'vendido' = regra do Alex: Aprovado, Faturado, Preparando envio,
    Pronto para envio, Enviado e Entregue (NÃO inclui Em aberto, Não entregue e Cancelado)."""
    n = _norm(sit)
    if "cancel" in n: return "cancelado"
    if "aberto" in n: return "aberto"
    if "nao entregue" in n: return "naoentregue"     # antes de 'entregue' (é substring)
    if "entregue" in n: return "vendido"
    if "enviado" in n: return "vendido"
    if "pronto" in n: return "vendido"
    if "preparando" in n: return "vendido"
    if "faturado" in n: return "vendido"
    if "aprovado" in n: return "vendido"
    return "outro"

def _categoria_natureza(nome):
    """Nome da natureza de operação -> categoria p/ a quebra do painel."""
    t = _norm(nome)
    if not t: return "Outros"
    if "devolu" in t: return "Devolução"
    if "bonifica" in t: return "Bonificação"
    if "transfer" in t: return "Transferência"
    if "venda" in t: return "Vendas"
    return "Outros"   # industrialização, remessa, simples faturamento, etc.

def _nota_natureza(nf_id):
    """Nome da natureza de operação a partir da nota fiscal (ou '' se não der)."""
    try:
        n = raw("nota.fiscal.obter.php", {"id": nf_id}).get("retorno", {}).get("nota_fiscal", {})
        return n.get("natureza_operacao") or ""
    except Exception:
        return ""

def _iso(data_br):
    """'DD/MM/AAAA' -> 'AAAA-MM-DD' (vazio se não der)."""
    try:
        d, m, a = str(data_br).split("/"); return f"{a}-{m.zfill(2)}-{d.zfill(2)}"
    except Exception:
        return ""

def _todos_pedidos(desde_br, ate_br):
    """Varre todas as páginas de pedidos.pesquisa no período (DD/MM/AAAA)."""
    out = []
    pag = 1
    while True:
        res = pesquisa_pedidos(pagina=pag, data_inicial=desde_br, data_final=ate_br)
        ret = res.get("retorno", {})
        if str(ret.get("status")) != "OK":
            break
        for p in ret.get("pedidos", []):
            out.append(p.get("pedido", {}))
        total = int(ret.get("numero_paginas") or 1)
        if pag >= total:
            break
        pag += 1
        time.sleep(0.15)                            # educado com a API
    return out

ENRICH_BUDGET_S = 1200  # tempo máx. (s) buscando detalhes NOVOS por execução (cobre o re-carimbo inicial da natureza numa rodada; depois do cache quente, fica rápido)

def _detalhe(ids):
    """Detalhe de cada pedido (UF/cidade + itens) via pedido.obter, com cache Redis `tiny:ped:<id>`.
    Só busca os que faltam, até estourar o orçamento de tempo — assim a 1ª carga é progressiva e sem travar."""
    import generate as G
    rds = getattr(G, "_RDS", None)
    out = {}; faltam = []
    for pid in ids:
        v = None
        if rds:
            try: v = rds.get(f"tiny:ped:{pid}")
            except Exception: pass
        if v:
            try:
                rec = json.loads(v if isinstance(v, str) else v.decode())
                if "nat_id" in rec: out[pid] = rec          # cache já tem natureza
                else: faltam.append(pid)                     # cache antigo (Fase 2) -> refaz p/ pegar natureza
            except Exception: faltam.append(pid)
        else:
            faltam.append(pid)
    deadline = time.time() + ENRICH_BUDGET_S
    buscados = 0
    for pid in faltam:
        if time.time() > deadline: break
        try:
            det = pedido_obter(pid).get("retorno", {}).get("pedido", {})
            cli = det.get("cliente", {}) or {}
            itens = []
            for it in det.get("itens", []):
                i = it.get("item", {}) or {}
                try: q = float(i.get("quantidade") or 0)
                except Exception: q = 0.0
                try: vu = float(i.get("valor_unitario") or 0)
                except Exception: vu = 0.0
                nm = (i.get("descricao") or "").strip()
                if nm: itens.append({"nm": nm, "q": round(q, 2), "o": round(q * vu, 2)})
            rec = {"uf": (cli.get("uf") or "").strip().upper(), "cid": (cli.get("cidade") or "").strip(),
                   "itens": itens, "nat_id": str(det.get("id_natureza_operacao") or ""),
                   "nf": str(det.get("id_nota_fiscal") or "")}
            out[pid] = rec
            if rds:
                try: rds.set(f"tiny:ped:{pid}", json.dumps(rec, ensure_ascii=False))
                except Exception: pass
            buscados += 1
            time.sleep(0.2)
        except Exception:
            continue
    print(f"[TINY] detalhe: {len(out)}/{len(ids)} com detalhe · {buscados} buscados nesta rodada")
    return out

def build():
    hoje = datetime.datetime.now(SP).date()
    desde_br = "01/01/2026"
    ate_br = hoje.strftime("%d/%m/%Y")
    peds = _todos_pedidos(desde_br, ate_br)
    vendas = []; ids = []
    for p in peds:
        lbl, eq = _classifica_vendedor(p.get("nome_vendedor"))
        try: val = round(float(p.get("valor") or 0), 2)
        except Exception: val = 0.0
        pid = str(p.get("id") or "")
        vendas.append({"d": _iso(p.get("data_pedido")), "v": lbl, "e": eq,
                       "s": p.get("situacao") or "—", "g": _grupo_situacao(p.get("situacao")),
                       "o": val, "n": p.get("numero"), "_id": pid})
        ids.append(pid)
    # enriquece com UF + produtos + natureza de operação (cache Redis; progressivo)
    try: det = _detalhe(ids)
    except Exception: import traceback; print("[TINY] detalhe falhou:\n" + traceback.format_exc()); det = {}
    # resolve nomes das naturezas (id -> nome) e guarda no Redis tiny:natmap
    import generate as G
    rds = getattr(G, "_RDS", None)
    natmap = {}
    if rds:
        try: natmap = json.loads((rds.get("tiny:natmap") or b"{}"))
        except Exception: natmap = {}
    precisa = {}
    for d in det.values():
        nid = d.get("nat_id")
        if nid and nid not in natmap and d.get("nf") and d["nf"] != "0":
            precisa.setdefault(nid, d["nf"])
    for nid, nf in precisa.items():
        nome = _nota_natureza(nf)
        if nome: natmap[nid] = nome
        time.sleep(0.1)
    if rds and precisa:
        try: rds.set("tiny:natmap", json.dumps(natmap, ensure_ascii=False))
        except Exception: pass
    itens = []; enriq = 0
    for idx, p in enumerate(vendas):
        d = det.get(p["_id"])
        if d:
            enriq += 1
            p["uf"] = d.get("uf", "")
            p["nat"] = _categoria_natureza(natmap.get(d.get("nat_id"), ""))
            for it in d.get("itens", []):
                itens.append({"i": idx, "nm": it["nm"], "q": it["q"], "o": it["o"]})
        else:
            p["uf"] = ""; p["nat"] = ""
        del p["_id"]
    # ordem das situações p/ a seção "Vendas por situação" (fluxo lógico do Tiny)
    ordem_sit = ["Em aberto", "Aprovado", "Faturado", "Preparando envio", "Pronto para envio",
                 "Enviado", "Entregue", "Não entregue", "Cancelado"]
    return {"gerado_em": datetime.datetime.now(SP).isoformat(timespec="minutes"),
            "hoje": hoje.isoformat(), "desde": DESDE,
            "equipes": {"Vendas Internas": ["Vanessa", "Thauany", "Ingrid"],
                        "LightWall": ["Patrícia", "Luiz"], "Outros": []},
            "ordem_situacoes": ordem_sit, "vendas": vendas,
            "itens": itens, "enriquecidos": enriq, "total_ped": len(vendas)}

def atualizar():
    if not _LOCK.acquire(blocking=False):
        print("[TINY] já está atualizando, pulando"); return
    try:
        import generate as G
        if not os.path.exists(OUT) and getattr(G, "_RDS", None):
            try:
                c = G._RDS.get("tiny:ultimo")
                if c:
                    with open(OUT, "w", encoding="utf-8") as fp: fp.write(c.decode() if isinstance(c, bytes) else c)
            except Exception: pass
        dados = build()
        tmp = OUT + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fp: json.dump(dados, fp, ensure_ascii=False)
        os.replace(tmp, OUT)
        if getattr(G, "_RDS", None):
            try: G._RDS.set("tiny:ultimo", json.dumps(dados, ensure_ascii=False))
            except Exception: pass
        print(f"[TINY] gerado {dados['gerado_em']} — {len(dados['vendas'])} pedidos")
    except Exception:
        print("[TINY] falhou:\n" + traceback.format_exc())
        try:
            import generate as G
            if not os.path.exists(OUT) and getattr(G, "_RDS", None):
                c = G._RDS.get("tiny:ultimo")
                if c:
                    with open(OUT, "w", encoding="utf-8") as fp: fp.write(c.decode() if isinstance(c, bytes) else c)
        except Exception: pass
    finally:
        _LOCK.release()

if __name__ == "__main__":
    atualizar()
