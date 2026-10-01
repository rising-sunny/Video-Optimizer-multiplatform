# -*- coding: utf-8 -*-
"""Diagnostico de acceso a Facebook/Instagram ANTES de intentar publicar.

    .venv\\Scripts\\python.exe check_facebook_access.py

Responde las tres preguntas que importan y que el error 190 de Facebook no
contesta (su texto enumera permisos faltantes que el token si tiene):

  1. El page token, .funciona y es de la pagina correcta?
  2. .Cuando vence cada token?
  3. Los permisos `pages_*` del user token, .alcanzan a ESTA pagina?

La (3) es la que nos costo un ciclo entero el 2026-08-19: Meta congela en el
token a que paginas aplica cada permiso, segun lo tildado al autorizar la app.
Tener rol de administrador en el Business NO alcanza y el token ya emitido no
se actualiza solo.

Sale con codigo 0 si todo esta bien, 1 si hay algo que arreglar.
"""

from __future__ import annotations

import datetime
import sys

import requests

from publish import facebook_uploader as fb


def _fmt_expiry(data: dict) -> str:
    expires_at = data.get("expires_at") or 0
    if not expires_at:
        return "nunca vence"
    when = datetime.datetime.fromtimestamp(expires_at)
    days = (when - datetime.datetime.now()).total_seconds() / 86400.0
    if days < 0:
        return "VENCIDO el %s" % when.strftime("%Y-%m-%d %H:%M")
    if days < 3:
        return "vence el %s (en %.1f dias -- MUY PRONTO)" % (when.strftime("%Y-%m-%d %H:%M"), days)
    return "vence el %s (en %.0f dias)" % (when.strftime("%Y-%m-%d %H:%M"), days)


def _debug_token(token: str, ref_token: str, api_version: str) -> dict:
    url = "https://graph.facebook.com/%s/debug_token" % api_version
    resp = requests.get(url, params={"input_token": token, "access_token": ref_token}, timeout=25)
    return (resp.json() or {}).get("data", {}) or {}


def main() -> int:
    api_version = fb._env("FACEBOOK_GRAPH_API_VERSION", "v23.0")
    page_id = fb._env("FACEBOOK_PAGE_ID")
    user_token = fb._env("FACEBOOK_USER_ACCESS_TOKEN")
    problemas = []

    print("=" * 66)
    print("ACCESO A FACEBOOK / INSTAGRAM")
    print("=" * 66)
    print("Pagina objetivo (FACEBOOK_PAGE_ID): %s" % (page_id or "(sin definir)"))

    # 1. El page token sirve y es de la pagina que corresponde.
    print("\n1) Page token")
    try:
        token, resolved_id = fb._resolve_page_access_token(api_version=api_version)
        identity = fb._get_page_identity(token, api_version=api_version)
        nombre, real_id = identity.get("name"), str(identity.get("id"))
        if page_id and real_id != str(page_id):
            problemas.append("el page token es de la pagina %s, no de %s" % (real_id, page_id))
            print("   [FAIL] el token es de %r (id=%s), pero se espera %s"
                  % (nombre, real_id, page_id))
        else:
            print("   [OK] Facebook lo acepta y es de %r (id=%s)" % (nombre, real_id))
    except Exception as exc:
        problemas.append("no hay page token utilizable")
        print("   [FAIL] %s" % exc)

    if not user_token:
        print("\n(sin FACEBOOK_USER_ACCESS_TOKEN: no se puede chequear vencimiento ni alcance)")
        return 1 if problemas else 0

    # 2. Vencimientos.
    print("\n2) Vencimientos")
    user_data = {}
    for nombre_var in ("FACEBOOK_PAGE_ACCESS_TOKEN", "FACEBOOK_USER_ACCESS_TOKEN",
                       "INSTAGRAM_USER_ACCESS_TOKEN"):
        valor = fb._env(nombre_var)
        if not valor:
            print("   [--] %-28s vacio" % nombre_var)
            continue
        try:
            data = _debug_token(valor, user_token, api_version)
        except Exception as exc:
            print("   [??] %-28s no se pudo consultar (%s)" % (nombre_var, exc))
            continue
        if nombre_var == "FACEBOOK_USER_ACCESS_TOKEN":
            user_data = data
        vencimiento = _fmt_expiry(data)
        valido = data.get("is_valid")
        if not valido:
            problemas.append("%s no es valido" % nombre_var)
        elif "MUY PRONTO" in vencimiento or "VENCIDO" in vencimiento:
            problemas.append("%s %s" % (nombre_var, vencimiento))
        marca = "OK" if valido and "MUY PRONTO" not in vencimiento else "FAIL"
        print("   [%s] %-28s tipo=%-6s %s" % (marca, nombre_var, data.get("type"), vencimiento))

    # 3. Alcance de los permisos: la parte que el error 190 esconde.
    print("\n3) Alcance de los permisos pages_* del user token")
    scopes = user_data.get("granular_scopes") or []
    pages_scopes = [g for g in scopes if str(g.get("scope", "")).startswith("pages_")]
    if not pages_scopes:
        print("   [??] el token no reporta granular_scopes de paginas")
    else:
        cubren = False
        for grant in pages_scopes:
            targets = grant.get("target_ids")
            if targets is None:
                alcance, ok = "todas las paginas", True
            else:
                ids = [str(t) for t in targets]
                alcance = ", ".join(ids)
                ok = page_id is not None and str(page_id) in ids
            cubren = cubren or ok
            print("   [%s] %-28s -> %s" % ("OK" if ok else "FAIL", grant.get("scope"), alcance))
        if not cubren:
            problemas.append(
                "los permisos pages_* NO alcanzan a la pagina %s: reautorizar la app "
                "incluyendo esa pagina y emitir un token NUEVO (el ya emitido no se "
                "actualiza al cambiar roles)" % page_id
            )

    print("\n" + "-" * 66)
    if problemas:
        print("HAY QUE ARREGLAR:")
        for p in problemas:
            print("  - %s" % p)
        return 1
    print("=> Todo OK: se puede publicar en Facebook.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
