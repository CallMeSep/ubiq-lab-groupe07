"""Protocole applicatif minimal (TCP) entre véhicules et nœuds de calcul.

Requête  : une ligne JSON (en-tête) terminée par '\\n', puis `size` octets.
Réponse  : une ligne JSON, puis `size` octets (résultat).

Les fichiers d'état partagés (Mininet partage le système de fichiers
entre tous les nœuds) sont écrits de façon atomique (tmp + rename).
"""
from __future__ import annotations

import json
import os
import socket
import time

PORT = 9000
CHUNK = 65536


def send_msg(sock: socket.socket, header: dict, size: int) -> None:
    header = dict(header, size=int(size))
    sock.sendall((json.dumps(header) + "\n").encode())
    pad = b"\0" * min(CHUNK, max(size, 1))
    left = size
    while left > 0:
        n = min(left, CHUNK)
        sock.sendall(pad[:n])
        left -= n


def recv_line(f) -> dict | None:
    line = f.readline()
    if not line:
        return None
    return json.loads(line.decode())


def recv_payload(f, size: int) -> None:
    left = size
    while left > 0:
        chunk = f.read(min(CHUNK, left))
        if not chunk:
            raise ConnectionError("connexion fermée pendant la réception")
        left -= len(chunk)


def write_json_atomic(path: str, obj) -> None:
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def read_json(path: str, default=None):
    for _ in range(3):
        try:
            with open(path) as f:
                return json.load(f)
        except FileNotFoundError:
            return default
        except (json.JSONDecodeError, OSError):
            time.sleep(0.005)
    return default
