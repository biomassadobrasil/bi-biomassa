# -*- coding: utf-8 -*-
"""Conector Tiny API v2 (token simples). Token lido de env TINY_TOKEN."""
import os, json, urllib.parse, urllib.request

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
