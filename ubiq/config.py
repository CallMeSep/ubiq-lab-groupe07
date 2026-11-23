"""Chargement des scénarios et des expériences (YAML).

Un *scénario* décrit le monde (routes, AP, Edge, UAV, pannes).
Une *expérience* référence un scénario, le surcharge éventuellement,
et définit les variantes de politiques, un balayage de paramètre et
le nombre de répétitions.
"""
from __future__ import annotations

import copy
import os
from typing import Any

import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve(path: str) -> str:
    """Chemin relatif -> absolu (relatif à la racine du dépôt)."""
    if os.path.isabs(path):
        return path
    return os.path.join(REPO_ROOT, path)


def load_yaml(path: str) -> dict:
    with open(resolve(path), encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def deep_merge(base: dict, extra: dict) -> dict:
    """Fusion récursive : `extra` écrase `base`. Renvoie une copie."""
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def set_dotted(d: dict, key: str, value: Any) -> None:
    """set_dotted(d, 'tasks.rate_hz', 8) ; crée les niveaux manquants."""
    parts = key.split(".")
    cur = d
    for p in parts[:-1]:
        if not isinstance(cur.get(p), dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = copy.deepcopy(value)


def get_dotted(d: dict, key: str, default: Any = None) -> Any:
    cur: Any = d
    for p in key.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur


def apply_overrides(scenario: dict, overrides: dict | None) -> dict:
    """Applique des surcharges ; les clés peuvent être pointées ('a.b.c')."""
    sc = copy.deepcopy(scenario)
    for k, v in (overrides or {}).items():
        if "." in k:
            set_dotted(sc, k, v)
        elif isinstance(v, dict) and isinstance(sc.get(k), dict):
            sc[k] = deep_merge(sc[k], v)
        else:
            sc[k] = copy.deepcopy(v)
    return sc


def load_experiment(path: str) -> tuple[dict, dict]:
    """Renvoie (expérience, scénario de base déjà surchargé)."""
    exp = load_yaml(path)
    exp.setdefault("name", os.path.splitext(os.path.basename(path))[0])
    exp.setdefault("reps", 1)
    exp.setdefault("seed", 1)
    exp.setdefault("variants", {"default": {}})
    if "scenario" not in exp:
        raise ValueError(f"{path}: clé 'scenario' manquante")
    scenario = load_yaml(exp["scenario"])
    scenario = apply_overrides(scenario, exp.get("overrides"))
    return exp, scenario


def expand_runs(exp: dict, scenario: dict) -> list[dict]:
    """Liste des runs : variantes x valeurs du balayage x répétitions."""
    runs = []
    sweep = exp.get("sweep")
    values = sweep["values"] if sweep else [None]
    for vname, vover in exp["variants"].items():
        for val in values:
            sc = apply_overrides(scenario, vover or {})
            if sweep:
                set_dotted(sc, sweep["param"], val)
            for rep in range(int(exp["reps"])):
                runs.append({
                    "variant": vname,
                    "sweep_param": sweep["param"] if sweep else None,
                    "sweep_value": val,
                    "rep": rep,
                    "seed": int(exp["seed"]) * 1000 + rep,
                    "scenario": sc,
                })
    return runs
