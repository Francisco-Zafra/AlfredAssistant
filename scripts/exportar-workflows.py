#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Baja los workflows de tu n8n al repo, ya limpios, para versionarlos con git.

    python3 scripts/exportar-workflows.py
    git diff workflows/          # qué ha cambiado en n8n desde el último commit

Lee N8N_API_URL y N8N_API_KEY del .env. La key es la de la API pública
(Settings > n8n API), no el token del MCP: son dos cosas distintas y el MCP
solo ve los workflows que tienen el acceso MCP activado.

Cada workflow va al fichero de workflows/ cuyo "name" coincide. Si no hay
ninguno, se crea uno nuevo con el nombre en minúsculas y guiones. Los ficheros
que no están en n8n, como 01-libreta.json, no se tocan.

Además de lo que quita limpiar-workflow.py:
  staticData       el offset de Telegram y la confirmación pendiente, o sea,
                   restos de tus mensajes
  ids de workflow  los Execute Workflow que apuntan a otro workflow de esta
                   instancia vuelven a llevar PEGA_AQUI_EL_ID_DE_..., que es lo
                   que el README dice que hay que rellenar al importar

Y aborta sin escribir nada si algún valor del .env aparece dentro de un
workflow, o algo con pinta de token (JWT, "Bearer ...", token de bot): un
secreto pegado a mano en un nodo no debería llegar nunca a git.
"""
import importlib.util
import json
import os
import re
import sys
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARPETA = os.path.join(RAIZ, "workflows")

# El nombre con guion no se puede importar con un import normal.
_spec = importlib.util.spec_from_file_location(
    "limpiar", os.path.join(RAIZ, "scripts", "limpiar-workflow.py"))
limpiar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(limpiar)

# Pinta de secreto aunque no esté en el .env: un JWT, un "Bearer xxx" literal
# o un token de bot de Telegram. Lo normal es que vayan en una credencial de n8n.
PINTA_SECRETO = re.compile(
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}|Bearer [A-Za-z0-9._-]{16,}|(?<![0-9])\d{8,10}:[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])")

# Lo único que va al repo, y en este orden, que es el de los ficheros que ya hay.
CLAVES = ("name", "nodes", "connections", "settings", "pinData")


def leer_env():
    env = {}
    with open(os.path.join(RAIZ, ".env"), encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, valor = linea.split("=", 1)
            # Tolera "CLAVE = valor" y comillas, que el .env se edita a mano.
            env[clave.strip()] = valor.strip().strip("'\"")
    return env


def pedir(url, key):
    req = urllib.request.Request(url, headers={"X-N8N-API-KEY": key, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def bajar_todos(base, key):
    workflows, cursor = [], None
    while True:
        url = base + "/api/v1/workflows?limit=100"
        if cursor:
            url += "&cursor=" + cursor
        pagina = pedir(url, key)
        workflows += pagina["data"]
        cursor = pagina.get("nextCursor")
        if not cursor:
            return workflows


def slug(nombre):
    s = nombre.lower()
    for a, b in zip("áéíóúüñ", "aeiouun"):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def marcador(nombre):
    # "02a - Escucha" -> PEGA_AQUI_EL_ID_DE_02a_ESCUCHA, como los que ya había.
    prefijo, _, resto = nombre.partition(" - ")
    return "PEGA_AQUI_EL_ID_DE_" + prefijo + "_" + slug(resto).replace("-", "_").upper()


def ficheros_por_nombre():
    mapa = {}
    for f in sorted(os.listdir(CARPETA)):
        if f.endswith(".json") and not f.endswith(".local.json"):
            with open(os.path.join(CARPETA, f), encoding="utf-8") as fh:
                mapa[json.load(fh)["name"]] = f
    return mapa


def poner_marcadores(wf, ids):
    for nodo in wf["nodes"]:
        ref = nodo.get("parameters", {}).get("workflowId")
        if isinstance(ref, dict) and ref.get("value") in ids:
            nodo["parameters"]["workflowId"] = {
                "__rl": True, "value": marcador(ids[ref["value"]]), "mode": "id"}


def main():
    env = leer_env()
    base = env.get("N8N_API_URL", "").rstrip("/")
    key = env.get("N8N_API_KEY", "")
    if not base or not key:
        print("Faltan N8N_API_URL o N8N_API_KEY en el .env")
        return 1

    vivos = [w for w in bajar_todos(base, key) if not w.get("isArchived")]
    ids = {w["id"]: w["name"] for w in vivos}
    existentes = ficheros_por_nombre()
    # Valores cortos como "info" darian falsos positivos; el user id de
    # Telegram ya pasa de 8 cifras.
    secretos = {k: v for k, v in env.items() if len(v) >= 8 and k != "N8N_API_URL"}

    listos, fallos = [], 0
    for w in sorted(vivos, key=lambda w: w["name"]):
        wf = {k: w[k] for k in CLAVES if k in w}
        fichero = existentes.get(w["name"]) or slug(w["name"]) + ".json"
        print(fichero + "  <-  " + w["name"])

        # Antes de limpiar, que es quien ordena las claves.
        poner_marcadores(wf, ids)
        if limpiar.limpiar_wf(wf) is None:
            fallos += 1
            continue

        texto = json.dumps(wf, ensure_ascii=False)
        fugas = [k for k, v in secretos.items() if v in texto]
        if fugas:
            print("  ABORTADO: el workflow contiene el valor de " + ", ".join(fugas))
            fallos += 1
            continue
        sospecha = PINTA_SECRETO.search(texto)
        if sospecha:
            print("  ABORTADO: parece un token pegado a mano: " + sospecha.group(0)[:12] + "...")
            print("  Muévelo a una credencial de n8n o a una variable de entorno.")
            fallos += 1
            continue
        listos.append((fichero, wf))

    # Todo o nada: si uno falla no se escribe ninguno, para no dejar el repo a
    # medias entre dos versiones de n8n.
    if fallos:
        print("\nNo se ha escrito nada: %d workflow(s) con problemas." % fallos)
        return 1
    for fichero, wf in listos:
        limpiar.escribir(os.path.join(CARPETA, fichero), wf)

    sin_n8n = sorted(set(existentes) - set(ids.values()))
    if sin_n8n:
        print("\nEn el repo pero no en n8n (no se tocan): " + ", ".join(existentes[n] for n in sin_n8n))
    print("\nListo. Revisa con: git diff workflows/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
