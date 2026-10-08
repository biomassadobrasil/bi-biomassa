# -*- coding: utf-8 -*-
"""Tráfego Pago (Meta Ads + Google Ads) -> trafego.json. Roda de hora em hora (server.py).
Só dados das plataformas (sem Bitrix). Cada bloco guarda o último resultado bom (Redis + disco):
se uma plataforma falhar, o painel mostra o último dado E avisa desde quando está parado."""
import os, re, json, datetime, threading, traceback, unicodedata
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "trafego.json")
DIAS = 90                     # histórico diário guardado (filtro personalizado vai até aqui)
SP = ZoneInfo("America/Sao_Paulo")
_LOCK = threading.Lock()

try:
    from generate import _RDS  # mesmo Redis do resto do BI (opcional)
except Exception:
    _RDS = None

def _agora():
    return datetime.datetime.now(SP)

def _norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[\s_]+", " ", s).strip()

def _ultimo_bom(key):
    if _RDS:
        try:
            c = _RDS.get("trafego:" + key)
            if c: return json.loads(c)
        except Exception: pass
    try:
        with open(OUT, encoding="utf-8") as fp: return json.load(fp).get(key)
    except Exception: return None

def _guardar(key, val):
    if _RDS:
        try: _RDS.set("trafego:" + key, json.dumps(val, ensure_ascii=False))
        except Exception: pass

def _bloco(key, fn):
    """Roda fn(). OK -> marca ok/atualizado_em e guarda. Falhou -> último bom com ok=False + erro."""
    try:
        val = fn()
        val["ok"] = True; val["atualizado_em"] = _agora().isoformat(timespec="minutes")
        _guardar(key, val)
        return val
    except Exception as e:
        print(f"[TRAFEGO] {key} falhou:\n" + traceback.format_exc())
        old = _ultimo_bom(key) or {}
        old["ok"] = False; old["erro"] = _erro_amigavel(key, e)
        return old

def _erro_amigavel(key, e):
    s = str(e)
    if "invalid_grant" in s: return "O acesso ao Google Ads expirou (token revogado/vencido). Precisa gerar um novo GOOGLE_REFRESH_TOKEN."
    if "Falta" in s or "Faltam" in s: return s
    if key == "meta" and ("190" in s or "OAuthException" in s): return "O token da Meta expirou ou perdeu permissão. Precisa gerar um novo META_TOKEN."
    return s[:220]

# =====================================================================================
# META
# =====================================================================================
PERFIL_META = {
    "pessoa fisica": "Pessoa Física", "construtora": "Construtora", "incorporadora": "Incorporadora",
    "empreiteira": "Empreiteira", "empresa de reforma": "Empresa de Reforma",
    "cnpj (ampliacao ou reforma)": "CNPJ (ampliação/reforma)",
    "loja de material de construcao": "Loja de Material de Construção", "outro": "Outro",
}
NAO_B2B = {"Pessoa Física", "Outro", "Sem resposta"}

def perfil_meta(raw):
    t = _norm(raw)
    if not t: return "Sem resposta"
    if t in PERFIL_META: return PERFIL_META[t]
    if "fisica" in t: return "Pessoa Física"
    if "loja" in t: return "Loja de Material de Construção"
    if "reforma" in t: return "Empresa de Reforma"
    return str(raw).replace("_", " ").strip().capitalize()

def porte_meta(raw):
    t = _norm(raw)
    if not t: return ""
    if "pequen" in t or t in ("peq", "mei"): return "Pequeno"
    if "medi" in t: return "Médio"
    if "grand" in t: return "Grande"
    return ""

def metragem_meta(raw):
    t = _norm(raw).replace("m2", "").replace("m²", "")
    if not t: return ""
    nums = [float(n.replace(".", "")) for n in re.findall(r"\d[\d.]*", t) if n.replace(".", "")]
    if not nums: return ""
    n = max(nums) if (" a " in t or "ate" in t) else nums[0]
    if n <= 100: return "Até 100 m²"
    if n <= 500: return "100 a 500 m²"
    if n <= 1000: return "500 a 1.000 m²"
    return "Acima de 1.000 m²"

def obra_meta(raw):
    t = _norm(raw)
    if not t: return ""
    if t == "sim": return "Obra em andamento"
    if t.startswith("nao"): return "Sem obra no momento"
    for n in ("30", "60", "90"):
        if n in t: return f"Começa em {n} dias" + ("+" if n == "90" else "")
    return ""

OTIM = {"LEAD_GENERATION": "Leads (formulário instantâneo)", "QUALITY_LEAD": "Leads de maior qualidade",
        "LINK_CLICKS": "Cliques no link", "OFFSITE_CONVERSIONS": "Conversões no site",
        "CONVERSATIONS": "Conversas (mensagens)", "REACH": "Alcance", "IMPRESSIONS": "Impressões",
        "LANDING_PAGE_VIEWS": "Visualizações da página"}
LANCE = {"LOWEST_COST_WITHOUT_CAP": "Menor custo (sem limite)", "LOWEST_COST_WITH_BID_CAP": "Limite de lance",
         "COST_CAP": "Limite de custo por resultado", "LOWEST_COST_WITH_MIN_ROAS": "ROAS mínimo"}
OBJETIVO = {"OUTCOME_LEADS": "Geração de leads", "OUTCOME_TRAFFIC": "Tráfego", "OUTCOME_SALES": "Vendas",
            "OUTCOME_ENGAGEMENT": "Engajamento", "OUTCOME_AWARENESS": "Reconhecimento"}
CTA = {"LEARN_MORE": "Saiba mais", "SIGN_UP": "Cadastre-se", "CONTACT_US": "Fale conosco",
       "GET_QUOTE": "Solicitar orçamento", "APPLY_NOW": "Inscreva-se", "SEND_MESSAGE": "Enviar mensagem",
       "WHATSAPP_MESSAGE": "Enviar WhatsApp", "SHOP_NOW": "Comprar agora", "SUBSCRIBE": "Assinar"}
POS = {"feed": "Feed", "story": "Stories", "facebook_reels": "Reels", "reels": "Reels", "stream": "Feed",
       "profile_feed": "Feed do perfil", "explore": "Explorar", "explore_home": "Explorar",
       "marketplace": "Marketplace", "video_feeds": "Vídeos", "search": "Pesquisa", "right_hand_column": "Coluna direita",
       "instream_video": "Vídeos in-stream", "ig_search": "Pesquisa", "profile_reels": "Reels do perfil"}

def _cents(v):
    try: return round(int(v or 0) / 100, 2)
    except Exception: return 0.0

def _publico(t):
    """targeting da Meta -> resumo legível."""
    t = t or {}
    auto = (t.get("targeting_automation") or {}).get("advantage_audience") == 1
    idade = f"{t.get('age_min', 18)}–{t.get('age_max', 65)}{'+' if t.get('age_max') == 65 else ''} anos"
    if t.get("age_range"): idade += f" (sugestão {t['age_range'][0]}–{t['age_range'][1]})"
    gen = {(1,): "Homens", (2,): "Mulheres"}.get(tuple(t.get("genders") or []), "Todos")
    geo = t.get("geo_locations") or {}
    locais = [re.sub(r"\s*\(state\)", "", r.get("name", "")) for r in geo.get("regions", [])]
    locais += [c.get("name", "") for c in geo.get("cities", [])]
    if not locais and geo.get("countries"): locais = ["Brasil" if c == "BR" else c for c in geo["countries"]]
    seg = {"Interesses": [], "Cargos": [], "Empregadores": [], "Setores": [], "Comportamentos": []}
    for spec in (t.get("flexible_spec") or [{}]) + [t]:
        for k, lbl in (("interests", "Interesses"), ("work_positions", "Cargos"), ("work_employers", "Empregadores"),
                       ("industries", "Setores"), ("behaviors", "Comportamentos")):
            for x in spec.get(k, []) or []:
                if x.get("name") and x["name"] not in seg[lbl]: seg[lbl].append(x["name"])
    plats = t.get("publisher_platforms")
    if plats:
        pos = []
        for k in ("facebook_positions", "instagram_positions"):
            for p in t.get(k, []) or []:
                nm = ("FB " if k.startswith("facebook") else "IG ") + POS.get(p, p)
                if nm not in pos: pos.append(nm)
        posic = ", ".join(pos) or ", ".join(p.capitalize() for p in plats)
    else:
        posic = "Advantage+ (automático)"
    return {"advantage": auto, "idade": idade, "genero": gen, "locais": locais,
            "segmentacao": {k: v for k, v in seg.items() if v}, "posicionamentos": posic}

def _leads_n(actions):
    acts = {a.get("action_type"): float(a.get("value") or 0) for a in (actions or [])}
    return int(acts.get("lead") or acts.get("onsite_conversion.lead_grouped") or 0)

def _paginar(meta, path, params):
    out, after = [], None
    while True:
        p = dict(params)
        if after: p["after"] = after
        res = meta._get(path, p)
        out += res.get("data", [])
        after = (res.get("paging", {}).get("cursors", {}) or {}).get("after")
        if not after or not res.get("data") or not res.get("paging", {}).get("next"): break
    return out

def periodos(hoje):
    """Presets do filtro (mesma regra no painel). 7 dias = hoje e os 6 anteriores."""
    d = lambda n: (hoje - datetime.timedelta(days=n)).isoformat()
    return {"hoje": (d(0), d(0)), "hoje_prev": (d(1), d(1)),
            "ontem": (d(1), d(1)), "ontem_prev": (d(2), d(2)),
            "7d": (d(6), d(0)), "7d_prev": (d(13), d(7)),
            "30d": (d(29), d(0)), "30d_prev": (d(59), d(30))}

def build_meta():
    import meta
    if not os.environ.get("META_TOKEN"): raise RuntimeError("Falta META_TOKEN")
    acct = meta._acct()
    info = meta._get(acct, {"fields": "name,timezone_name,currency"})
    tz = ZoneInfo(info.get("timezone_name") or "America/Sao_Paulo")
    hoje = datetime.datetime.now(tz).date()

    camps = [c for c in _paginar(meta, f"{acct}/campaigns", {
        "fields": "id,name,effective_status,objective,daily_budget,lifetime_budget,bid_strategy,start_time",
        "limit": 200}) if c.get("effective_status") == "ACTIVE"]
    ids = [c["id"] for c in camps]
    filt = json.dumps([{"field": "campaign.id", "operator": "IN", "value": ids}])

    campanhas, ad_camp = [], {}
    for c in camps:
        adsets = [a for a in meta._get(f"{c['id']}/adsets", {
            "fields": "id,name,effective_status,daily_budget,lifetime_budget,optimization_goal,bid_strategy,targeting,destination_type",
            "limit": 50}).get("data", []) if a.get("effective_status") == "ACTIVE"]
        ads_all = meta._get(f"{c['id']}/ads", {
            "fields": "id,name,effective_status,preview_shareable_link,"
                      "creative.thumbnail_width(720).thumbnail_height(720){title,body,thumbnail_url,object_type,call_to_action_type,instagram_permalink_url}",
            "limit": 100}).get("data", [])
        for a in ads_all: ad_camp[a["id"]] = c["id"]
        orc = _cents(c.get("daily_budget")) or sum(_cents(a.get("daily_budget")) for a in adsets)
        orc_total = _cents(c.get("lifetime_budget")) or sum(_cents(a.get("lifetime_budget")) for a in adsets)
        aset0 = adsets[0] if adsets else {}
        campanhas.append({
            "id": c["id"], "nome": c["name"], "objetivo": OBJETIVO.get(c.get("objective"), c.get("objective")),
            "inicio": (c.get("start_time") or "")[:10],
            "orcamento_dia": orc, "orcamento_total": orc_total,
            "orcamento_nivel": "campanha" if (c.get("daily_budget") or c.get("lifetime_budget")) else "conjunto",
            "lance": LANCE.get(c.get("bid_strategy") or aset0.get("bid_strategy"), c.get("bid_strategy") or aset0.get("bid_strategy") or "—"),
            "otimizacao": OTIM.get(aset0.get("optimization_goal"), aset0.get("optimization_goal") or "—"),
            "conjuntos": [{"id": a["id"], "nome": a["name"], "orcamento_dia": _cents(a.get("daily_budget")),
                           "publico": _publico(a.get("targeting"))} for a in adsets],
            "anuncios": [{
                "id": a["id"], "nome": a["name"], "ativo": a.get("effective_status") == "ACTIVE",
                "preview": a.get("preview_shareable_link"),
                "instagram": (a.get("creative") or {}).get("instagram_permalink_url"),
                "thumb": (a.get("creative") or {}).get("thumbnail_url"),
                "tipo": {"VIDEO": "Vídeo", "PHOTO": "Imagem", "SHARE": "Carrossel/Link"}.get((a.get("creative") or {}).get("object_type"), (a.get("creative") or {}).get("object_type")),
                "titulo": (a.get("creative") or {}).get("title"),
                "texto": (a.get("creative") or {}).get("body"),
                "cta": CTA.get((a.get("creative") or {}).get("call_to_action_type"), (a.get("creative") or {}).get("call_to_action_type")),
            } for a in ads_all if a.get("effective_status") == "ACTIVE"],
        })

    # ---- diário por campanha (gasto, impressões, cliques, leads) ----
    since = (hoje - datetime.timedelta(days=DIAS - 1)).isoformat()
    diario = []
    if ids:
        for i in _paginar(meta, f"{acct}/insights", {
                "level": "campaign", "time_increment": 1, "filtering": filt,
                "time_range": json.dumps({"since": since, "until": hoje.isoformat()}),
                "fields": "campaign_id,spend,impressions,reach,clicks,inline_link_clicks,actions", "limit": 500}):
            diario.append({"c": i["campaign_id"], "d": i["date_start"], "g": round(float(i.get("spend") or 0), 2),
                            "i": int(i.get("impressions") or 0), "k": int(i.get("inline_link_clicks") or 0),
                            "r": int(i.get("reach") or 0),   # alcance do dia: só p/ tendência (não se soma)
                            "l": _leads_n(i.get("actions"))})

    # ---- alcance por período (não dá pra somar dia a dia: pergunta pronto à Meta) ----
    per = periodos(hoje)
    chave = {}                      # (ini, fim) -> presets (ontem e hoje_prev são o mesmo intervalo)
    for k, v in per.items(): chave.setdefault(v, []).append(k)
    tr = json.dumps([{"since": a, "until": b} for a, b in chave])
    alcance = {k: {"total": 0, "camp": {}} for k in per}
    if ids:
        for lvl in ("campaign", "account"):
            for i in _paginar(meta, f"{acct}/insights", {"level": lvl, "filtering": filt, "time_ranges": tr,
                                                         "fields": "campaign_id,reach,frequency", "limit": 500}):
                for k in chave.get((i["date_start"], i["date_stop"]), []):
                    if lvl == "campaign": alcance[k]["camp"][i["campaign_id"]] = int(i.get("reach") or 0)
                    else: alcance[k]["total"] = int(i.get("reach") or 0)

    # ---- leads do formulário (sem dados pessoais: só respostas de qualificação) ----
    desde_ts = int((datetime.datetime.now(tz) - datetime.timedelta(days=DIAS + 1)).timestamp())
    leads = []
    for ad_id, cid in ad_camp.items():
        for L in _paginar(meta, f"{ad_id}/leads", {
                "fields": "created_time,platform,field_data", "limit": 200,
                "filtering": json.dumps([{"field": "time_created", "operator": "GREATER_THAN", "value": desde_ts}])}):
            f = {}
            for fd in L.get("field_data", []):
                f[_norm(fd.get("name"))] = (fd.get("values") or [""])[0]
            get = lambda *ks: next((v for k, v in f.items() if any(x in k for x in ks) and v), "")
            perfil = perfil_meta(get("perfil"))
            dt = datetime.datetime.strptime(L["created_time"], "%Y-%m-%dT%H:%M:%S%z").astimezone(tz)
            leads.append({"d": dt.date().isoformat(), "c": cid, "a": ad_id,
                          "pl": {"ig": "Instagram", "fb": "Facebook"}.get(L.get("platform"), "Outros"),
                          "pf": perfil, "b2b": perfil not in NAO_B2B,
                          "po": porte_meta(get("porte")),
                          "m": metragem_meta(get("metragem")),
                          "ob": obra_meta(get("andamento"))})

    return {"conta": info.get("name"), "fuso": info.get("timezone_name"), "hoje": hoje.isoformat(),
            "campanhas": campanhas, "diario": diario, "alcance": alcance, "leads": leads}

def alcance_meta(ini, fim, camps=None):
    """Alcance de um intervalo personalizado (chamado ao vivo pelo painel)."""
    import meta
    acct = meta._acct()
    p = {"level": "account", "time_range": json.dumps({"since": ini, "until": fim}), "fields": "reach,frequency"}
    if camps: p["filtering"] = json.dumps([{"field": "campaign.id", "operator": "IN", "value": camps}])
    d = meta._get(f"{acct}/insights", p).get("data", [])
    return {"reach": int(d[0].get("reach") or 0) if d else 0, "freq": float(d[0].get("frequency") or 0) if d else 0}

# =====================================================================================
# GOOGLE
# =====================================================================================
CANAL_G = {"SEARCH": "Pesquisa", "PERFORMANCE_MAX": "Performance Max", "DISPLAY": "Display",
           "VIDEO": "YouTube", "DEMAND_GEN": "Demand Gen", "SHOPPING": "Shopping"}
LANCE_G = {"MAXIMIZE_CONVERSIONS": "Maximizar conversões", "MAXIMIZE_CONVERSION_VALUE": "Maximizar valor de conversão",
           "TARGET_CPA": "CPA desejado", "TARGET_ROAS": "ROAS desejado", "MANUAL_CPC": "CPC manual",
           "TARGET_SPEND": "Maximizar cliques", "TARGET_IMPRESSION_SHARE": "Parcela de impressões desejada"}
MATCH = {"EXACT": "Exata", "PHRASE": "Frase", "BROAD": "Ampla"}

GEO_PT = {"Brazil": "Brasil", "Sao Paulo": "São Paulo", "Parana": "Paraná", "Goias": "Goiás", "Para": "Pará",
          "Ceara": "Ceará", "Maranhao": "Maranhão", "Piaui": "Piauí", "Paraiba": "Paraíba", "Amapa": "Amapá",
          "Rondonia": "Rondônia", "Espirito Santo": "Espírito Santo", "Federal District": "Distrito Federal"}

def _geo_pt(nome):
    n = re.sub(r"^State of ", "", nome or "")
    return GEO_PT.get(n, n)

def _canal_g(nome):
    a = (nome or "").lower()
    if "whats" in a or "zap" in a: return "wpp"
    if "form" in a: return "form"
    return "outro"

def build_google():
    import google_ads as g
    cfg = g._cfg()
    if not cfg.get("refresh_token"): raise RuntimeError("Faltam credenciais Google (GOOGLE_*)")
    tzname = (g._search("SELECT customer.time_zone FROM customer")[0].get("customer", {}) or {}).get("timeZone") or "America/Sao_Paulo"
    tz = ZoneInfo(tzname)
    hoje = datetime.datetime.now(tz).date()
    since = (hoje - datetime.timedelta(days=DIAS - 1)).isoformat()

    camps = {}
    for r in g._search("""SELECT campaign.id, campaign.name, campaign.advertising_channel_type, campaign.bidding_strategy_type,
            campaign.start_date_time, campaign.target_cpa.target_cpa_micros, campaign.maximize_conversions.target_cpa_micros,
            campaign.network_settings.target_search_network, campaign.network_settings.target_content_network,
            campaign_budget.amount_micros FROM campaign WHERE campaign.status = 'ENABLED'"""):
        c = r.get("campaign", {}); b = r.get("campaignBudget", {})
        cpa = (c.get("targetCpa") or {}).get("targetCpaMicros") or (c.get("maximizeConversions") or {}).get("targetCpaMicros")
        ns = c.get("networkSettings") or {}
        camps[str(c["id"])] = {"id": str(c["id"]), "nome": c.get("name"),
            "tipo": CANAL_G.get(c.get("advertisingChannelType"), c.get("advertisingChannelType")),
            "lance": LANCE_G.get(c.get("biddingStrategyType"), c.get("biddingStrategyType")),
            "cpa_alvo": round(int(cpa) / 1e6, 2) if cpa else None,
            "orcamento_dia": round(int(b.get("amountMicros") or 0) / 1e6, 2),
            "inicio": (c.get("startDateTime") or c.get("startDate") or "")[:10],
            "redes": ", ".join(x for x, on in (("Pesquisa Google", True), ("Parceiros de pesquisa", ns.get("targetSearchNetwork")),
                                                ("Display", ns.get("targetContentNetwork"))) if on),
            "locais": [], "palavras": [], "negativas": 0, "anuncios": []}

    # locais (geo target -> nome)
    geo = {}
    for r in g._search("""SELECT campaign.id, campaign_criterion.location.geo_target_constant, campaign_criterion.negative
            FROM campaign_criterion WHERE campaign.status = 'ENABLED' AND campaign_criterion.type = 'LOCATION'"""):
        cid = str(r["campaign"]["id"]); cc = r.get("campaignCriterion", {})
        rn = (cc.get("location") or {}).get("geoTargetConstant")
        if rn and cid in camps: geo.setdefault(rn, []).append((cid, bool(cc.get("negative"))))
    if geo:
        lst = ", ".join(f"'{x}'" for x in geo)
        for r in g._search(f"SELECT geo_target_constant.resource_name, geo_target_constant.name FROM geo_target_constant WHERE geo_target_constant.resource_name IN ({lst})"):
            gt = r.get("geoTargetConstant", {})
            nome = _geo_pt(gt.get("name"))
            for cid, neg in geo.get(gt.get("resourceName"), []):
                camps[cid]["locais"].append(("Exceto " if neg else "") + nome)
        for c in camps.values(): c["locais"].sort(key=lambda x: x.startswith("Exceto"))

    # palavras-chave (config) + desempenho 30d
    kw = {}
    for r in g._search("""SELECT campaign.id, ad_group_criterion.criterion_id, ad_group_criterion.keyword.text,
            ad_group_criterion.keyword.match_type, ad_group_criterion.negative
            FROM ad_group_criterion WHERE campaign.status = 'ENABLED' AND ad_group.status = 'ENABLED'
            AND ad_group_criterion.status = 'ENABLED' AND ad_group_criterion.type = 'KEYWORD'"""):
        cid = str(r["campaign"]["id"]); a = r.get("adGroupCriterion", {})
        if cid not in camps: continue
        if a.get("negative"): camps[cid]["negativas"] += 1; continue
        k = (a.get("keyword") or {})
        kw[(cid, str(a.get("criterionId")))] = {"t": k.get("text"), "m": MATCH.get(k.get("matchType"), k.get("matchType")),
                                                "cl": 0, "cv": 0, "g": 0.0, "qs": None}
    for r in g._search(f"""SELECT campaign.id, ad_group_criterion.criterion_id, ad_group_criterion.quality_info.quality_score,
            metrics.clicks, metrics.conversions, metrics.cost_micros FROM keyword_view
            WHERE campaign.status = 'ENABLED' AND segments.date BETWEEN '{(hoje - datetime.timedelta(days=29)).isoformat()}' AND '{hoje.isoformat()}'"""):
        key = (str(r["campaign"]["id"]), str(r.get("adGroupCriterion", {}).get("criterionId")))
        if key not in kw: continue
        m = r.get("metrics", {}); k = kw[key]
        k["cl"] += int(m.get("clicks") or 0); k["cv"] += float(m.get("conversions") or 0)
        k["g"] += int(m.get("costMicros") or 0) / 1e6
        k["qs"] = (r.get("adGroupCriterion", {}).get("qualityInfo") or {}).get("qualityScore") or k["qs"]
    for (cid, _), k in kw.items():
        k["g"] = round(k["g"], 2); k["cv"] = round(k["cv"], 1); camps[cid]["palavras"].append(k)
    for c in camps.values(): c["palavras"].sort(key=lambda x: (-x["cl"], x["t"] or ""))

    # anúncios responsivos de pesquisa (pra prévia)
    for r in g._search("""SELECT campaign.id, ad_group.name, ad_group_ad.ad.id, ad_group_ad.ad.final_urls,
            ad_group_ad.ad.responsive_search_ad.headlines, ad_group_ad.ad.responsive_search_ad.descriptions,
            ad_group_ad.ad.responsive_search_ad.path1, ad_group_ad.ad.responsive_search_ad.path2, ad_group_ad.ad_strength
            FROM ad_group_ad WHERE campaign.status = 'ENABLED' AND ad_group.status = 'ENABLED' AND ad_group_ad.status = 'ENABLED'"""):
        cid = str(r["campaign"]["id"])
        if cid not in camps: continue
        ad = (r.get("adGroupAd") or {}).get("ad") or {}; rsa = ad.get("responsiveSearchAd") or {}
        if not rsa: continue
        camps[cid]["anuncios"].append({"grupo": (r.get("adGroup") or {}).get("name"),
            "url": (ad.get("finalUrls") or [""])[0], "p1": rsa.get("path1"), "p2": rsa.get("path2"),
            "titulos": [h.get("text") for h in rsa.get("headlines", [])],
            "descricoes": [d.get("text") for d in rsa.get("descriptions", [])],
            "forca": {"EXCELLENT": "Excelente", "GOOD": "Boa", "AVERAGE": "Média", "POOR": "Fraca"}.get(
                (r.get("adGroupAd") or {}).get("adStrength"), (r.get("adGroupAd") or {}).get("adStrength"))})

    # diário por campanha
    rng = f"segments.date BETWEEN '{since}' AND '{hoje.isoformat()}'"
    diario = {}
    for r in g._search(f"""SELECT campaign.id, segments.date, metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions
            FROM campaign WHERE campaign.status = 'ENABLED' AND {rng}"""):
        cid = str(r["campaign"]["id"]); d = r["segments"]["date"]; m = r.get("metrics", {})
        diario[(cid, d)] = {"c": cid, "d": d, "i": int(m.get("impressions") or 0), "k": int(m.get("clicks") or 0),
                            "g": round(int(m.get("costMicros") or 0) / 1e6, 2), "cv": round(float(m.get("conversions") or 0), 2),
                            "w": 0.0, "f": 0.0}
    acoes = {}
    for r in g._search(f"""SELECT campaign.id, segments.date, segments.conversion_action_name, metrics.conversions
            FROM campaign WHERE campaign.status = 'ENABLED' AND {rng}"""):
        cid = str(r["campaign"]["id"]); d = r["segments"]["date"]; nome = r["segments"].get("conversionActionName")
        n = float((r.get("metrics") or {}).get("conversions") or 0)
        acoes[nome] = _canal_g(nome)
        row = diario.get((cid, d))
        if not row or not n: continue
        ch = _canal_g(nome)
        if ch == "wpp": row["w"] = round(row["w"] + n, 2)
        elif ch == "form": row["f"] = round(row["f"] + n, 2)

    # termos de pesquisa (7 e 30 dias)
    termos = {}
    for k, n in (("7d", 6), ("30d", 29)):
        termos[k] = [{"t": (r.get("searchTermView") or {}).get("searchTerm"), "c": str(r["campaign"]["id"]),
                      "i": int(r["metrics"].get("impressions") or 0), "k": int(r["metrics"].get("clicks") or 0),
                      "cv": round(float(r["metrics"].get("conversions") or 0), 1),
                      "g": round(int(r["metrics"].get("costMicros") or 0) / 1e6, 2)}
                     for r in g._search(f"""SELECT campaign.id, search_term_view.search_term, metrics.impressions, metrics.clicks,
                            metrics.conversions, metrics.cost_micros FROM search_term_view WHERE campaign.status = 'ENABLED'
                            AND segments.date BETWEEN '{(hoje - datetime.timedelta(days=n)).isoformat()}' AND '{hoje.isoformat()}'
                            ORDER BY metrics.clicks DESC LIMIT 60""")]

    return {"fuso": tzname, "hoje": hoje.isoformat(), "campanhas": list(camps.values()),
            "diario": list(diario.values()), "acoes": acoes, "termos": termos}

# =====================================================================================
def atualizar():
    """Puxa Meta e Google, roda as análises e grava trafego.json. Seguro contra execução dupla."""
    if not _LOCK.acquire(blocking=False):
        print("[TRAFEGO] já está atualizando, pulando"); return
    try:
        dados = {"gerado_em": _agora().isoformat(timespec="minutes"),
                 "meta": _bloco("meta", build_meta), "google": _bloco("google", build_google)}
        try:
            import analise
            dados["analises"] = analise.obter(dados)
        except Exception:
            print("[TRAFEGO] análises falharam:\n" + traceback.format_exc())
            dados["analises"] = _ultimo_bom("analises")
        tmp = OUT + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fp: json.dump(dados, fp, ensure_ascii=False)
        os.replace(tmp, OUT)
        m, g = dados["meta"], dados["google"]
        print(f"[TRAFEGO] gerado {dados['gerado_em']} — Meta ok={m.get('ok')} ({len(m.get('leads', []))} leads) · Google ok={g.get('ok')}")
    finally:
        _LOCK.release()

if __name__ == "__main__":
    atualizar()
