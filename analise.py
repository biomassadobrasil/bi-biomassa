# -*- coding: utf-8 -*-
"""Análises automáticas do Tráfego Pago.
Com ANTHROPIC_API_KEY: Claude lê um resumo dos números e escreve o que está bom, o que é curioso
e o que melhorar (no máx. a cada HORAS_IA horas, pra manter o custo baixo).
Sem chave (ou se a IA falhar): regras fixas, grátis."""
import os, json, datetime, traceback
from zoneinfo import ZoneInfo

HORAS_IA = 6
MODELO = "claude-opus-5-5"
SP = ZoneInfo("America/Sao_Paulo")

def _d(s): return datetime.date.fromisoformat(s)

def _soma(rows, ini, fim, camp=None):
    t = {"g": 0.0, "i": 0, "k": 0, "l": 0.0, "cv": 0.0, "w": 0.0, "f": 0.0}
    for r in rows:
        if ini <= r["d"] <= fim and (camp is None or r["c"] == camp):
            for k in t: t[k] += r.get(k, 0) or 0
    return t

def _rng(hoje, a, b):
    h = _d(hoje)
    return (h - datetime.timedelta(days=a)).isoformat(), (h - datetime.timedelta(days=b)).isoformat()

def _div(a, b): return round(a / b, 2) if b else None

def resumo(dados):
    """Resumo compacto (sem dados pessoais) que vai pra IA e pras regras."""
    out = {}
    m = dados.get("meta") or {}
    if m.get("campanhas"):
        r7, p7, r30 = _rng(m["hoje"], 6, 0), _rng(m["hoje"], 13, 7), _rng(m["hoje"], 29, 0)
        camps = []
        for c in m["campanhas"]:
            linha = {"nome": c["nome"], "orcamento_dia": c["orcamento_dia"], "otimizacao": c["otimizacao"],
                     "publico": [{"advantage": s["publico"]["advantage"], "idade": s["publico"]["idade"],
                                  "locais": s["publico"]["locais"], "segmentacao": s["publico"]["segmentacao"]} for s in c["conjuntos"]],
                     "anuncios": [{"nome": a["nome"], "tipo": a["tipo"], "titulo": a["titulo"]} for a in c["anuncios"]]}
            for nome, (ini, fim) in (("ultimos_7d", r7), ("7d_anteriores", p7), ("ultimos_30d", r30)):
                s = _soma(m["diario"], ini, fim, c["id"])
                L = [x for x in m["leads"] if x["c"] == c["id"] and ini <= x["d"] <= fim]
                b2b = sum(1 for x in L if x["b2b"])
                linha[nome] = {"investimento": round(s["g"], 2), "leads": int(s["l"]), "cpl": _div(s["g"], s["l"]),
                               "leads_form": len(L), "leads_b2b": b2b, "pct_b2b": _div(100 * b2b, len(L)),
                               "cpl_b2b": _div(s["g"], b2b), "impressoes": s["i"], "cliques_link": s["k"],
                               "ctr_link_pct": _div(100 * s["k"], s["i"]),
                               "alcance": (m.get("alcance", {}).get("7d" if nome == "ultimos_7d" else "7d_prev" if nome == "7d_anteriores" else "30d", {}).get("camp", {}) or {}).get(c["id"])}
            camps.append(linha)
        L30 = [x for x in m["leads"] if r30[0] <= x["d"] <= r30[1]]
        cont = lambda k: dict(sorted(((v, sum(1 for x in L30 if x[k] == v)) for v in {x[k] for x in L30 if x[k]}), key=lambda kv: -kv[1]))
        plat = {}
        for p in ("Instagram", "Facebook"):
            Lp = [x for x in L30 if x["pl"] == p]
            plat[p] = {"leads": len(Lp), "b2b": sum(1 for x in Lp if x["b2b"])}
        out["meta"] = {"campanhas": camps, "ultimos_30d": {"perfil": cont("pf"), "porte_empresas": cont("po"),
                       "metragem": cont("m"), "obra": cont("ob"), "plataforma": plat},
                       "obs": "B2B = perfis empresa (construtora, incorporadora, empreiteira, empresa de reforma, CNPJ reforma, loja). Pessoa Física e Outro não contam como B2B."}
    g = dados.get("google") or {}
    if g.get("campanhas"):
        r7, p7, r30 = _rng(g["hoje"], 6, 0), _rng(g["hoje"], 13, 7), _rng(g["hoje"], 29, 0)
        camps = []
        for c in g["campanhas"]:
            linha = {"nome": c["nome"], "tipo": c["tipo"], "lance": c["lance"], "orcamento_dia": c["orcamento_dia"],
                     "locais": c["locais"], "qtd_palavras": len(c["palavras"]), "negativas": c["negativas"],
                     "top_palavras_30d": c["palavras"][:12]}
            for nome, (ini, fim) in (("ultimos_7d", r7), ("7d_anteriores", p7), ("ultimos_30d", r30)):
                s = _soma(g["diario"], ini, fim, c["id"])
                cv = round(s["cv"])   # Google divide conversões entre campanhas; painel usa número cheio
                linha[nome] = {"investimento": round(s["g"], 2), "conversoes": cv, "whatsapp": round(s["w"]),
                               "formulario": round(s["f"]), "cpl": _div(s["g"], cv), "impressoes": s["i"],
                               "cliques": s["k"], "ctr_pct": _div(100 * s["k"], s["i"]), "cpc": _div(s["g"], s["k"])}
            camps.append(linha)
        termos = (g.get("termos") or {}).get("30d", [])
        out["google"] = {"campanhas": camps,
                         "termos_30d_mais_clicados": termos[:20],
                         "termos_30d_gastando_sem_conversao": [t for t in termos if t["cv"] == 0 and t["g"] > 0][:12]}
    return out

SCHEMA_BLOCO = {"type": "object", "additionalProperties": False,
                "required": ["resumo", "bom", "curioso", "melhorar"],
                "properties": {"resumo": {"type": "string"},
                               "bom": {"type": "array", "items": {"type": "string"}},
                               "curioso": {"type": "array", "items": {"type": "string"}},
                               "melhorar": {"type": "array", "items": {"type": "string"}}}}
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["meta", "google"],
          "properties": {"meta": SCHEMA_BLOCO, "google": SCHEMA_BLOCO}}

SISTEMA = """Você é o analista de tráfego pago da Biomassa do Brasil (argamassa polimérica para alvenaria; o público-alvo é B2B: construtoras, incorporadoras, empreiteiras, empresas de reforma e lojas de material de construção).
Você recebe um resumo em JSON das campanhas ativas de Meta Ads e Google Ads e escreve a análise que aparece no painel para o time de marketing.

Como escrever:
- Português do Brasil, direto, sem jargão desnecessário. Cada item é uma ou duas frases e cita os números que sustentam a conclusão (R$, %, quantidades).
- "bom": o que está funcionando. "curioso": padrões que chamam atenção e merecem olhar (nem bom nem ruim). "melhorar": ações concretas e priorizadas (o que fazer, em qual campanha, por quê).
- Sempre diga qual campanha performa melhor e qual traz mais leads B2B, e compare custo por lead com custo por lead B2B.
- Compare os últimos 7 dias com os 7 dias anteriores quando a diferença for relevante.
- 2 a 4 itens por lista. "resumo" é uma frase de abertura com a principal conclusão.
- Use só os números recebidos. Se faltar dado para uma conclusão, não invente: diga o que falta. Se uma plataforma vier sem dados, preencha o bloco dela explicando isso em "resumo" e deixe as listas vazias."""

def _ia(res):
    import anthropic
    client = anthropic.Anthropic()
    r = client.beta.messages.create(
        model=MODELO, max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=SISTEMA,
        messages=[{"role": "user", "content": "Dados das campanhas (JSON):\n" + json.dumps(res, ensure_ascii=False)}])
    if r.stop_reason == "refusal": raise RuntimeError("IA recusou a análise")
    if r.stop_reason == "max_tokens": raise RuntimeError("IA cortada por max_tokens")
    txt = next((b.text for b in r.content if b.type == "text"), "")
    return json.loads(txt)

# ---------------- regras (grátis / fallback) ----------------
def _brl(v): return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def regras(res):
    out = {}
    m = res.get("meta")
    if m:
        bom, cur, mel = [], [], []
        cs = [c for c in m["campanhas"] if c["ultimos_7d"]["investimento"] > 0]
        if cs:
            best = min(cs, key=lambda c: c["ultimos_7d"]["cpl_b2b"] or 9e9)
            if best["ultimos_7d"]["cpl_b2b"]:
                bom.append(f"{best['nome']} tem o menor custo por lead B2B nos últimos 7 dias: {_brl(best['ultimos_7d']['cpl_b2b'])} ({best['ultimos_7d']['leads_b2b']} leads B2B).")
            for c in cs:
                a, b = c["ultimos_7d"], c["7d_anteriores"]
                if a["cpl"] and b["cpl"] and a["cpl"] > b["cpl"] * 1.25:
                    mel.append(f"{c['nome']}: custo por lead subiu de {_brl(b['cpl'])} para {_brl(a['cpl'])} em relação aos 7 dias anteriores.")
                if a["pct_b2b"] is not None and a["pct_b2b"] < 25:
                    mel.append(f"{c['nome']}: só {a['pct_b2b']:.0f}% dos leads dos últimos 7 dias são B2B. Vale reforçar no formulário/criativo que o produto é para empresas e obras.")
        p = m["ultimos_30d"]["plataforma"]
        if p["Instagram"]["leads"] and p["Facebook"]["leads"]:
            ti, tf = p["Instagram"]["b2b"] / p["Instagram"]["leads"], p["Facebook"]["b2b"] / p["Facebook"]["leads"]
            cur.append(f"Nos últimos 30 dias, {ti*100:.0f}% dos leads do Instagram são B2B, contra {tf*100:.0f}% no Facebook.")
        out["meta"] = {"resumo": "Análise automática por regras (a análise com IA entra quando a chave da Anthropic for configurada).",
                       "bom": bom, "curioso": cur, "melhorar": mel}
    g = res.get("google")
    if g:
        mel = [f"Termo \"{t['t']}\" gastou {_brl(t['g'])} em 30 dias sem nenhuma conversão. Avalie negativar." for t in g["termos_30d_gastando_sem_conversao"][:3]]
        out["google"] = {"resumo": "Análise automática por regras.", "bom": [], "curioso": [], "melhorar": mel}
    return out

# ---------------- cache ----------------
def _ler_cache():
    try:
        from generate import _RDS
        if _RDS:
            c = _RDS.get("trafego:analises")
            if c: return json.loads(c)
    except Exception: pass
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "trafego.json"), encoding="utf-8") as fp:
            return json.load(fp).get("analises")
    except Exception: return None

def _gravar_cache(v):
    try:
        from generate import _RDS
        if _RDS: _RDS.set("trafego:analises", json.dumps(v, ensure_ascii=False))
    except Exception: pass

def obter(dados, forcar=False):
    agora = datetime.datetime.now(SP)
    res = resumo(dados)
    if os.environ.get("ANTHROPIC_API_KEY"):
        old = _ler_cache()
        if not forcar and old and old.get("fonte") == "ia":
            try:
                if agora - datetime.datetime.fromisoformat(old["em"]) < datetime.timedelta(hours=HORAS_IA): return old
            except Exception: pass
        try:
            v = {"fonte": "ia", "em": agora.isoformat(timespec="minutes"), **_ia(res)}
            _gravar_cache(v)
            return v
        except Exception:
            print("[TRAFEGO] IA falhou, usando regras:\n" + traceback.format_exc())
    return {"fonte": "regras", "em": agora.isoformat(timespec="minutes"), **regras(res)}
