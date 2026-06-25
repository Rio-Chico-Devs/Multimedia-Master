"""
Starter glossary for English-source agricultural/tractor manuals (BCS-style
walking tractors and implements), translating to Italian.

These are forced term -> translation overrides (see translate_engine.py's
_protect_glossary): a small offline MT model routinely mistranslates or
garbles compound technical nouns it never saw much of in training data
("POWER UNITS" -> "POTENZAUNITI" instead of "unità di potenza"). Pinning the
sector vocabulary up front is the offline-friendly fix. This is a starting
point, not a finished glossary — the Glossario dialog lets the user edit,
remove, or add to whatever gets loaded here.
"""
from __future__ import annotations

AGRICULTURAL_EN_IT: dict[str, str] = {
    "power unit": "unità di potenza",
    "power take-off": "presa di forza",
    "PTO": "presa di forza",
    "walking tractor": "motocoltivatore",
    "two-wheel tractor": "motocoltivatore",
    "rotary tiller": "fresa rotante",
    "tiller": "fresa",
    "tine": "dente",
    "drawbar": "barra di traino",
    "hitch": "attacco",
    "implement": "attrezzo",
    "attachment": "accessorio",
    "gearbox": "cambio",
    "differential lock": "bloccaggio del differenziale",
    "clutch lever": "leva della frizione",
    "throttle lever": "leva dell'accelerazione",
    "brake lever": "leva del freno",
    "chassis": "telaio",
    "axle": "assale",
    "mower": "falciatrice",
    "snow blower": "fresaneve",
    "snow thrower": "fresaneve",
    "fuel tank": "serbatoio del carburante",
    "spark plug": "candela",
    "air filter": "filtro dell'aria",
    "oil filter": "filtro dell'olio",
    "safety guard": "protezione di sicurezza",
    "warning": "avvertenza",
    "caution": "attenzione",
    "danger": "pericolo",
    "maintenance": "manutenzione",
    "lubrication": "lubrificazione",
    "spare parts": "ricambi",
    "instruction manual": "manuale di istruzioni",
    "owner's manual": "manuale dell'utente",
}
