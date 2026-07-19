"""
Pre-deploy importcontrole.

Vergelijkt elke `from <lokale module> import <naam>` in de projectbestanden met de
namen die de bronmodule daadwerkelijk op module-niveau exporteert. Vangt een
ontbrekende naam (zoals een tijdens refactoring weggevallen constante) lokaal af,
in plaats van pas bij het opstarten op Streamlit Cloud.

Gebruik:
    python check_imports.py

Exitcode 0 = alles resolvet, 1 = er ontbreekt minstens één geïmporteerde naam.
"""
import ast
import importlib
import os
import sys

# Eigen modules (geen externe pakketten meecontroleren).
LOKALE_MODULES = {"database", "constraints", "toewijzing"}
TE_CONTROLEREN = ["app.py", "constraints.py", "toewijzing.py", "database.py"]


def _exports(modnaam, cache):
    if modnaam not in cache:
        cache[modnaam] = set(dir(importlib.import_module(modnaam)))
    return cache[modnaam]


def main():
    hier = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, hier)
    cache = {}
    ontbrekend = []
    gecontroleerd = 0

    for bestand in TE_CONTROLEREN:
        pad = os.path.join(hier, bestand)
        if not os.path.exists(pad):
            continue
        tree = ast.parse(open(pad, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in LOKALE_MODULES:
                beschikbaar = _exports(node.module, cache)
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    gecontroleerd += 1
                    if alias.name not in beschikbaar:
                        ontbrekend.append(f"{bestand}: from {node.module} import {alias.name}")

    print(f"{gecontroleerd} imports gecontroleerd over {len(TE_CONTROLEREN)} bestanden.")
    if ontbrekend:
        print("ONTBREKENDE IMPORTS:")
        for regel in ontbrekend:
            print(f"  - {regel}")
        return 1
    print("OK: alle imports resolven tegen de echte module-exports.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
