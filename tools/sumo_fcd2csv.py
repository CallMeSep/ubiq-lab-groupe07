#!/usr/bin/env python3
"""(Optionnel, enseignant) Convertit une sortie FCD de SUMO en trace CSV t,id,x,y.

  sumo -c ville.sumocfg --fcd-output fcd.xml --step-length 0.1
  python3 tools/sumo_fcd2csv.py fcd.xml scenarios/traces/ville.csv --max 8

SUMO n'est PAS nécessaire pour le cours : il sert seulement à produire, une fois,
une trace plus réaliste. Les étudiants ne voient que le CSV.
"""
import csv
import sys
import xml.etree.ElementTree as ET


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    src, dst = sys.argv[1], sys.argv[2]
    max_n = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 10**9
    ids, rows = {}, []
    for _, el in ET.iterparse(src, events=("end",)):
        if el.tag == "timestep":
            t = float(el.get("time"))
            for v in el.findall("vehicle"):
                vid = v.get("id")
                if vid not in ids and len(ids) < max_n:
                    ids[vid] = f"V{len(ids) + 1}"
                if vid in ids:
                    rows.append({"t": round(t, 2), "id": ids[vid], "x": float(v.get("x")), "y": float(v.get("y"))})
            el.clear()
    with open(dst, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["t", "id", "x", "y"])
        w.writeheader()
        w.writerows(rows)
    print(f"{dst} : {len(rows)} lignes, {len(ids)} véhicules")


if __name__ == "__main__":
    main()
