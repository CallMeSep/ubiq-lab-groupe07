#!/usr/bin/env bash
# Vérifie l'environnement : make check
#   - coeur obligatoire (backend sim) : python3 >= 3.10, PyYAML, matplotlib
#   - complément facultatif (backend mininet) : Mininet-WiFi, mac80211_hwsim, Open vSwitch, iw
say() { printf "  %-40s %s\n" "$1" "$2"; }

echo "Coeur du TP et du projet (backend sim) -- OBLIGATOIRE"
core=1
if command -v python3 >/dev/null; then
  v=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
  if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    say "python3" "OK ($v)"
  else
    say "python3" "trop ancien ($v) : 3.10 ou plus requis"; core=0
  fi
else
  say "python3" "ABSENT"; core=0
fi
if python3 -c "import yaml" 2>/dev/null; then say "PyYAML" "OK"; else say "PyYAML" "ABSENT"; core=0; fi
if python3 -c "import matplotlib" 2>/dev/null; then say "matplotlib" "OK"; else say "matplotlib" "ABSENT"; core=0; fi

echo "Validation complementaire (backend mininet) -- FACULTATIF"
mn=1
if python3 -c "import mn_wifi" 2>/dev/null; then say "Mininet-WiFi (module mn_wifi)" "OK"; else say "Mininet-WiFi (module mn_wifi)" "absent"; mn=0; fi
if modinfo mac80211_hwsim >/dev/null 2>&1; then say "module noyau mac80211_hwsim" "OK"; else say "module noyau mac80211_hwsim" "absent"; mn=0; fi
if command -v ovs-vsctl >/dev/null; then say "Open vSwitch" "OK"; else say "Open vSwitch" "absent"; mn=0; fi
if command -v iw >/dev/null; then say "iw" "OK"; else say "iw" "absent"; mn=0; fi

echo
if [ "$core" = 1 ]; then
  echo "=> coeur sim : OK. Le TP est realisable avec le backend sim."
else
  echo "=> coeur sim : A INSTALLER. Lancer : make install"
fi
if [ "$mn" = 1 ]; then
  echo "=> Mininet-WiFi : disponible (validation facultative : sudo make smoke-mn)."
else
  echo "=> Mininet-WiFi : non disponible. C'est facultatif ; pour l'installer : make install-mn (voir README)."
fi
[ "$core" = 1 ]
