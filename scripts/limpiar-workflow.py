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
  credentials       el id y el nombre de tu credencial en cada nodo; el secreto
                    nunca está aquí, pero la referencia sobra y el README ya
                    promete que las credenciales se conectan a mano

Qué NO toca: name, nodes, connections, settings. O sea, el workflow.

Si encuentra pinData con datos dentro, aborta: ahí se queda pegado lo que
capturaste probando, que puede incluir tu chat de Telegram y transcripciones.
"""
import json
import sys

FUERA_RAIZ = ("id", "versionId", "active", "tags", "nodeGroups", "meta")
FUERA_NODO = ("credentials", "webhookId")


def limpiar(ruta):
    with open(ruta, encoding="utf-8") as f:
        wf = json.load(f)

    pin = wf.get("pinData") or {}
    if pin:
        print("  ABORTADO: pinData trae datos de " + ", ".join(pin))
        print("  Vacíalo en n8n (clic derecho en el nodo, Unpin) y vuelve a exportar.")
        return False

    quitados = []

    for clave in FUERA_RAIZ:
        if clave in wf:
            quitados.append(clave)
            del wf[clave]

    for nodo in wf.get("nodes", []):
        for clave in FUERA_NODO:
            if clave in nodo:
                quitados.append(nodo["name"] + "." + clave)
                del nodo[clave]

    wf.setdefault("pinData", {})

    with open(ruta, "w", encoding="utf-8", newline="\n") as f:
        # ensure_ascii deja el fichero en ASCII puro: acentos y emojis viajan
        # como \uXXXX y ningún reencodado los puede estropear.
        json.dump(wf, f, ensure_ascii=True, indent=2)
        f.write("\n")

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
