#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Limpia un workflow exportado de n8n antes de subirlo al repo.

Un export de la interfaz arrastra metadatos de TU instalación que no pintan nada
en un repo público. No son contraseñas, pero identifican tu instancia y ensucian
la importación de cualquiera que se clone esto.

    python3 scripts/limpiar-workflow.py workflows/*.json

Qué quita:
  meta.instanceId   huella estable de tu instalación de n8n
  id, versionId     ids internos; al importar se generan otros
  active            para que nada se active solo al importarlo
  tags, nodeGroups  vacíos o locales, no aportan
  availableInMCP    si el MCP de n8n puede verlo; es cosa de tu instancia
  id de cada nodo   n8n lo regenera al importar
  credentials       el id y el nombre de tu credencial en cada nodo; el secreto
                    nunca está aquí, pero la referencia sobra y el README ya
                    promete que las credenciales se conectan a mano

Qué NO toca: name, nodes, connections, settings. O sea, el workflow.

Si encuentra pinData con datos dentro, aborta: ahí se queda pegado lo que
capturaste probando, que puede incluir tu chat de Telegram y transcripciones.

scripts/exportar-workflows.py importa limpiar_wf() y escribir() de aquí, para
que un export por API y uno a mano acaben exactamente igual.
"""
import json
import sys

FUERA_RAIZ = ("id", "versionId", "active", "tags", "nodeGroups", "meta")
FUERA_NODO = ("id", "credentials", "webhookId")
# Ajustes que dependen de tu instancia, no del workflow.
FUERA_AJUSTES = ("availableInMCP",)
ORDEN_NODO = ("parameters", "name", "type", "typeVersion", "position")


def ordenado(valor):
    """Ordena las claves de los dicts a cualquier profundidad. Las listas no:
    en una lista el orden sí significa algo."""
    if isinstance(valor, dict):
        return {k: ordenado(valor[k]) for k in sorted(valor)}
    if isinstance(valor, list):
        return [ordenado(v) for v in valor]
    return valor


def limpiar_wf(wf):
    """Limpia el dict en sitio. Devuelve la lista de lo quitado, o None si trae
    pinData con datos y no se debe guardar."""
    pin = wf.get("pinData") or {}
    if pin:
        print("  ABORTADO: pinData trae datos de " + ", ".join(pin))
        print("  Vacíalo en n8n (clic derecho en el nodo, Unpin) y vuelve a exportar.")
        return None

    quitados = []

    for clave in FUERA_RAIZ:
        if clave in wf:
            quitados.append(clave)
            del wf[clave]

    for clave in FUERA_AJUSTES:
        if clave in wf.get("settings", {}):
            quitados.append("settings." + clave)
            del wf["settings"][clave]

    for i, nodo in enumerate(wf.get("nodes", [])):
        for clave in FUERA_NODO:
            if clave in nodo:
                quitados.append(nodo["name"] + "." + clave)
                del nodo[clave]
        # La interfaz y la API sacan las claves en distinto orden, y n8n reordena
        # nodos, conexiones y parámetros según los tocas. Sin fijarlo, cada export
        # mueve medio fichero en el diff sin cambiar nada. A n8n el orden le da igual.
        if "parameters" in nodo:
            nodo["parameters"] = ordenado(nodo["parameters"])
        primero = {k: nodo[k] for k in ORDEN_NODO if k in nodo}
        wf["nodes"][i] = {**primero, **{k: v for k, v in nodo.items() if k not in primero}}

    if "nodes" in wf:
        wf["nodes"].sort(key=lambda n: n["name"])
    if "connections" in wf:
        wf["connections"] = dict(sorted(wf["connections"].items()))

    # La API devuelve [] cuando no hay nada; el repo siempre lleva {}.
    wf["pinData"] = {}
    return quitados


def escribir(ruta, wf):
    with open(ruta, "w", encoding="utf-8", newline="\n") as f:
        # ensure_ascii deja el fichero en ASCII puro: acentos y emojis viajan
        # como \uXXXX y ningún reencodado los puede estropear.
        json.dump(wf, f, ensure_ascii=True, indent=2)
        f.write("\n")


def limpiar(ruta):
    with open(ruta, encoding="utf-8") as f:
        wf = json.load(f)

    quitados = limpiar_wf(wf)
    if quitados is None:
        return False
    escribir(ruta, wf)

    print("  limpiado: " + (", ".join(quitados) if quitados else "no había nada que quitar"))
    return True


def main(rutas):
    if not rutas:
        print(__doc__)
        return 1
    fallos = 0
    for ruta in rutas:
        print(ruta)
        if not limpiar(ruta):
            fallos += 1
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
