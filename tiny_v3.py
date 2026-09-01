# -*- coding: utf-8 -*-
"""Conector Tiny API v3 (OAuth2 Keycloak) — orçamentos = propostas comerciais.
Credenciais via env (TINY_V3_CLIENT_ID/SECRET/REFRESH_TOKEN) no Railway,
ou fallback ~/tiny-v3.yaml no local. Refresh token com scope offline_access
(idle 24h, renovado a cada uso — o gerador roda 2x/dia, então se mantém vivo)."""
import os, json, base64, time, urllib.parse, urllib.request, urllib.error

TOKEN_URL = "https://accounts.tiny.com.br/realms/tiny/protocol/openid-connect/token"
BASE = "https://api.tiny.com.br/public-api/v3"
# idVendedor do Tiny -> chave da vendedora no funil (948=Patrícia, 890=Thauany) — confirmado por dado real
TINY_VEND = {"1037643379": "948", "1035585430": "890"}

def _cfg():
    c = {"client_id": os.environ.get("TINY_V3_CLIENT_ID", ""),
         "client_secret": os.environ.get("TINY_V3_CLIENT_SECRET", ""),
         "refresh_token": os.environ.get("TINY_V3_REFRESH_TOKEN", "")}
    if not c["refresh_token"]:
        for p in ("/Users/macbookpro/tiny-v3.yaml", os.path.expanduser("~/tiny-v3.yaml")):
            if os.path.exists(p):
                for ln in open(p, encoding="utf-8"):
                    if ":" in ln:
                        k, _, v = ln.partition(":"); k = k.strip()
                        if k in c and not c[k]: c[k] = v.strip()
                break
    return c

def _access_token(c):
    data = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": c["refresh_token"]}).encode()
    basic = base64.b64encode(f"{c['client_id']}:{c['client_secret']}".encode()).decode()
    req = urllib.request.Request(TOKEN_URL, data=data,
        headers={"Authorization": "Basic " + basic, "Content-Type": "application/x-www-form-urlencoded"})
    return json.load(urllib.request.urlopen(req, timeout=60))["access_token"]

def _money(s):
    try: return round(float(str(s).replace(".", "").replace(",", ".")), 2) if s else 0.0
    except Exception: return 0.0

def _get(at, path):
    req = urllib.request.Request(BASE + path, headers={"Authorization": "Bearer " + at})
    last = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r: return json.load(r)
        except urllib.error.HTTPError as e:
            last = RuntimeError(f"Tiny v3 {e.code}: {e.read().decode()[:200]}")
            if e.code not in (429, 500, 502, 503, 504): raise last
        except Exception as e: last = e
        time.sleep(2)
    raise last

def propostas(desde="2025-01-01"):
    """Orçamentos (propostas comerciais) das 2 vendedoras -> [{vd,dt,valor,sit,num}].
    None se sem credenciais."""
    c = _cfg()
    if not c["refresh_token"]: return None
    at = _access_token(c)
    out = []
    for vid, vk in TINY_VEND.items():
        off = 0
        while True:
            q = {"idVendedor": vid, "limit": 100, "offset": off}
            if desde: q["dataInicio"] = desde
            res = _get(at, "/orcamentos?" + urllib.parse.urlencode(q))
            its = res.get("itens", [])
            for o in its:
                sit = o.get("situacao", "")
                if sit == "Modelo": continue   # modelos não são propostas reais
                out.append({"vd": vk, "dt": (o.get("data", "") or "")[:10],
                            "valor": _money(o.get("valorTotal")), "sit": sit,
                            "num": o.get("numeroProposta", "")})
            if len(its) < 100: break
            off += 100
    return out

if __name__ == "__main__":
    p = propostas()
    from collections import Counter
    print("total:", len(p) if p else p)
    if p:
        print("por vendedora:", Counter(x["vd"] for x in p))
        print("situações:", Counter(x["sit"] for x in p))
