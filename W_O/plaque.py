from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import textwrap
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
#  Dépendances optionnelles
# --------------------------------------------------------------------------
try:
    import requests
    from requests.adapters import HTTPAdapter
    try:
        from urllib3.util.retry import Retry as _Retry
    except Exception:                                    # urllib3 très ancien
        _Retry = None
    _HAS_REQUESTS = True
except Exception:
    _HAS_REQUESTS = False
    _Retry = None

try:
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    _HAS_RICH = True
except Exception:
    _HAS_RICH = False


VERSION = "2.0"
USER_AGENT = f"PlaqueOSINT/{VERSION} (+https://vpic.nhtsa.dot.gov)"


# ==========================================================================
#  Utilitaires
# ==========================================================================
_MARKUP_RE = re.compile(r"\[/?[a-zA-Z0-9_ .#=]{1,32}\]")


def _strip_markup(s: Any) -> str:
    return _MARKUP_RE.sub("", str(s))


def _slug(s: Optional[str]) -> str:
    """'C5 Aircross' -> 'c5aircross' (insensible aux accents/casse/ponctuation)."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _clean(v: Any) -> bool:
    """Filtre les valeurs vides renvoyées par les API."""
    if v is None:
        return False
    s = str(v).strip().lower()
    return s not in ("", "null", "none", "n/a", "not applicable", "0", "0.0", "-1")


def _wrap(s: Any, width: int = 96, max_lines: int = 6) -> str:
    lines = textwrap.wrap(" ".join(str(s).split()), width=width)
    if len(lines) > max_lines:
        lines = lines[:max_lines] + ["[…]"]
    return "\n".join(lines)


# ==========================================================================
#  Départements / régions (pour l'analyse de plaque FNI et territoriale SIV)
# ==========================================================================
_DEPTS: List[Tuple[str, str, str]] = [
    ("01", "Ain", "Auvergne-Rhône-Alpes"),
    ("02", "Aisne", "Hauts-de-France"),
    ("03", "Allier", "Auvergne-Rhône-Alpes"),
    ("04", "Alpes-de-Haute-Provence", "Provence-Alpes-Côte d'Azur"),
    ("05", "Hautes-Alpes", "Provence-Alpes-Côte d'Azur"),
    ("06", "Alpes-Maritimes", "Provence-Alpes-Côte d'Azur"),
    ("07", "Ardèche", "Auvergne-Rhône-Alpes"),
    ("08", "Ardennes", "Grand Est"),
    ("09", "Ariège", "Occitanie"),
    ("10", "Aube", "Grand Est"),
    ("11", "Aude", "Occitanie"),
    ("12", "Aveyron", "Occitanie"),
    ("13", "Bouches-du-Rhône", "Provence-Alpes-Côte d'Azur"),
    ("14", "Calvados", "Normandie"),
    ("15", "Cantal", "Auvergne-Rhône-Alpes"),
    ("16", "Charente", "Nouvelle-Aquitaine"),
    ("17", "Charente-Maritime", "Nouvelle-Aquitaine"),
    ("18", "Cher", "Centre-Val de Loire"),
    ("19", "Corrèze", "Nouvelle-Aquitaine"),
    ("2A", "Corse-du-Sud", "Corse"),
    ("2B", "Haute-Corse", "Corse"),
    ("21", "Côte-d'Or", "Bourgogne-Franche-Comté"),
    ("22", "Côtes-d'Armor", "Bretagne"),
    ("23", "Creuse", "Nouvelle-Aquitaine"),
    ("24", "Dordogne", "Nouvelle-Aquitaine"),
    ("25", "Doubs", "Bourgogne-Franche-Comté"),
    ("26", "Drôme", "Auvergne-Rhône-Alpes"),
    ("27", "Eure", "Normandie"),
    ("28", "Eure-et-Loir", "Centre-Val de Loire"),
    ("29", "Finistère", "Bretagne"),
    ("30", "Gard", "Occitanie"),
    ("31", "Haute-Garonne", "Occitanie"),
    ("32", "Gers", "Occitanie"),
    ("33", "Gironde", "Nouvelle-Aquitaine"),
    ("34", "Hérault", "Occitanie"),
    ("35", "Ille-et-Vilaine", "Bretagne"),
    ("36", "Indre", "Centre-Val de Loire"),
    ("37", "Indre-et-Loire", "Centre-Val de Loire"),
    ("38", "Isère", "Auvergne-Rhône-Alpes"),
    ("39", "Jura", "Bourgogne-Franche-Comté"),
    ("40", "Landes", "Nouvelle-Aquitaine"),
    ("41", "Loir-et-Cher", "Centre-Val de Loire"),
    ("42", "Loire", "Auvergne-Rhône-Alpes"),
    ("43", "Haute-Loire", "Auvergne-Rhône-Alpes"),
    ("44", "Loire-Atlantique", "Pays de la Loire"),
    ("45", "Loiret", "Centre-Val de Loire"),
    ("46", "Lot", "Occitanie"),
    ("47", "Lot-et-Garonne", "Nouvelle-Aquitaine"),
    ("48", "Lozère", "Occitanie"),
    ("49", "Maine-et-Loire", "Pays de la Loire"),
    ("50", "Manche", "Normandie"),
    ("51", "Marne", "Grand Est"),
    ("52", "Haute-Marne", "Grand Est"),
    ("53", "Mayenne", "Pays de la Loire"),
    ("54", "Meurthe-et-Moselle", "Grand Est"),
    ("55", "Meuse", "Grand Est"),
    ("56", "Morbihan", "Bretagne"),
    ("57", "Moselle", "Grand Est"),
    ("58", "Nièvre", "Bourgogne-Franche-Comté"),
    ("59", "Nord", "Hauts-de-France"),
    ("60", "Oise", "Hauts-de-France"),
    ("61", "Orne", "Normandie"),
    ("62", "Pas-de-Calais", "Hauts-de-France"),
    ("63", "Puy-de-Dôme", "Auvergne-Rhône-Alpes"),
    ("64", "Pyrénées-Atlantiques", "Nouvelle-Aquitaine"),
    ("65", "Hautes-Pyrénées", "Occitanie"),
    ("66", "Pyrénées-Orientales", "Occitanie"),
    ("67", "Bas-Rhin", "Grand Est"),
    ("68", "Haut-Rhin", "Grand Est"),
    ("69", "Rhône", "Auvergne-Rhône-Alpes"),
    ("70", "Haute-Saône", "Bourgogne-Franche-Comté"),
    ("71", "Saône-et-Loire", "Bourgogne-Franche-Comté"),
    ("72", "Sarthe", "Pays de la Loire"),
    ("73", "Savoie", "Auvergne-Rhône-Alpes"),
    ("74", "Haute-Savoie", "Auvergne-Rhône-Alpes"),
    ("75", "Paris", "Île-de-France"),
    ("76", "Seine-Maritime", "Normandie"),
    ("77", "Seine-et-Marne", "Île-de-France"),
    ("78", "Yvelines", "Île-de-France"),
    ("79", "Deux-Sèvres", "Nouvelle-Aquitaine"),
    ("80", "Somme", "Hauts-de-France"),
    ("81", "Tarn", "Occitanie"),
    ("82", "Tarn-et-Garonne", "Occitanie"),
    ("83", "Var", "Provence-Alpes-Côte d'Azur"),
    ("84", "Vaucluse", "Provence-Alpes-Côte d'Azur"),
    ("85", "Vendée", "Pays de la Loire"),
    ("86", "Vienne", "Nouvelle-Aquitaine"),
    ("87", "Haute-Vienne", "Nouvelle-Aquitaine"),
    ("88", "Vosges", "Grand Est"),
    ("89", "Yonne", "Bourgogne-Franche-Comté"),
    ("90", "Territoire de Belfort", "Bourgogne-Franche-Comté"),
    ("91", "Essonne", "Île-de-France"),
    ("92", "Hauts-de-Seine", "Île-de-France"),
    ("93", "Seine-Saint-Denis", "Île-de-France"),
    ("94", "Val-de-Marne", "Île-de-France"),
    ("95", "Val-d'Oise", "Île-de-France"),
    ("971", "Guadeloupe", "Guadeloupe"),
    ("972", "Martinique", "Martinique"),
    ("973", "Guyane", "Guyane"),
    ("974", "La Réunion", "La Réunion"),
    ("976", "Mayotte", "Mayotte"),
]
_DEPT_MAP = {code: (nom, region) for code, nom, region in _DEPTS}
_DEPT_ORDRE = [code for code, _, _ in _DEPTS]


# ==========================================================================
#  Base locale (repli hors-ligne) — segments et caractéristiques
# ==========================================================================
_SEGMENTS: Dict[str, Dict[str, Any]] = {
    "Citadine":   {"places": 5, "portes": 5, "coffre": "250-350 L", "l100": (4.0, 6.0),  "kwh": (14, 18)},
    "Mini":       {"places": 4, "portes": 3, "coffre": "160-220 L", "l100": (4.5, 6.5),  "kwh": (13, 17)},
    "Compacte":   {"places": 5, "portes": 5, "coffre": "380-450 L", "l100": (5.0, 7.0),  "kwh": (16, 22)},
    "Berline":    {"places": 5, "portes": 4, "coffre": "480-550 L", "l100": (5.5, 8.0),  "kwh": (18, 24)},
    "Break":      {"places": 5, "portes": 5, "coffre": "550-650 L", "l100": (5.5, 8.0),  "kwh": (18, 25)},
    "Coupé":      {"places": 4, "portes": 3, "coffre": "300-400 L", "l100": (6.5, 11.0), "kwh": (19, 26)},
    "Cabriolet":  {"places": 4, "portes": 2, "coffre": "200-300 L", "l100": (6.5, 11.0), "kwh": (19, 26)},
    "Sportive":   {"places": 4, "portes": 3, "coffre": "250-350 L", "l100": (9.0, 15.0), "kwh": (22, 30)},
    "SUV":        {"places": 5, "portes": 5, "coffre": "450-550 L", "l100": (5.5, 8.0),  "kwh": (18, 25)},
    "SUV Coupé":  {"places": 5, "portes": 5, "coffre": "400-500 L", "l100": (5.5, 8.0),  "kwh": (18, 25)},
    "Monospace":  {"places": 7, "portes": 5, "coffre": "200-700 L", "l100": (6.0, 9.0),  "kwh": (20, 28)},
    "Ludospace":  {"places": 7, "portes": 5, "coffre": "650-3000 L", "l100": (5.5, 8.0), "kwh": (20, 26)},
    "Utilitaire": {"places": 3, "portes": 4, "coffre": "3000-6000 L", "l100": (6.0, 9.0), "kwh": (22, 30)},
    "Pick-up":    {"places": 5, "portes": 4, "coffre": "1000-1500 L", "l100": (8.0, 12.0), "kwh": (25, 32)},
}

VEHICULES_FR: Dict[str, Dict[str, Any]] = {
    "renault": {"nom": "Renault", "modeles": {
        "clio": {"nom": "Clio", "segment": "Citadine", "carburants": ["Essence", "Diesel"], "puissances": [75, 90, 110, 130]},
        "megane": {"nom": "Mégane", "segment": "Compacte", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [115, 140, 160, 200]},
        "captur": {"nom": "Captur", "segment": "SUV", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [90, 130, 160]},
        "talisman": {"nom": "Talisman", "segment": "Berline", "carburants": ["Essence", "Diesel"], "puissances": [150, 200]},
        "scenic": {"nom": "Scénic", "segment": "Monospace", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [115, 140, 160]},
        "zoe": {"nom": "Zoe", "segment": "Citadine", "carburants": ["Électrique"], "puissances": [110, 135]},
        "arkana": {"nom": "Arkana", "segment": "SUV Coupé", "carburants": ["Hybride", "Essence"], "puissances": [140, 160]},
        "austral": {"nom": "Austral", "segment": "SUV", "carburants": ["Essence", "Hybride"], "puissances": [140, 160, 200]},
        "kangoo": {"nom": "Kangoo", "segment": "Ludospace", "carburants": ["Essence", "Diesel", "Électrique"], "puissances": [100, 130]},
        "trafic": {"nom": "Trafic", "segment": "Utilitaire", "carburants": ["Diesel", "Électrique"], "puissances": [110, 150, 170]},
    }},
    "peugeot": {"nom": "Peugeot", "modeles": {
        "108": {"nom": "108", "segment": "Mini", "carburants": ["Essence"], "puissances": [68, 82]},
        "208": {"nom": "208", "segment": "Citadine", "carburants": ["Essence", "Diesel", "Électrique"], "puissances": [75, 100, 136, 156]},
        "308": {"nom": "308", "segment": "Compacte", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [130, 180, 225]},
        "3008": {"nom": "3008", "segment": "SUV", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [130, 180, 300]},
        "5008": {"nom": "5008", "segment": "SUV", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [130, 180, 300]},
        "2008": {"nom": "2008", "segment": "SUV", "carburants": ["Essence", "Diesel", "Électrique"], "puissances": [100, 130, 156]},
        "508": {"nom": "508", "segment": "Berline", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [130, 180, 360]},
        "partner": {"nom": "Partner", "segment": "Ludospace", "carburants": ["Essence", "Diesel"], "puissances": [100, 130]},
    }},
    "citroen": {"nom": "Citroën", "modeles": {
        "c1": {"nom": "C1", "segment": "Mini", "carburants": ["Essence"], "puissances": [68, 82]},
        "c3": {"nom": "C3", "segment": "Citadine", "carburants": ["Essence", "Diesel"], "puissances": [83, 110]},
        "c4": {"nom": "C4", "segment": "Compacte", "carburants": ["Essence", "Diesel", "Électrique"], "puissances": [100, 130, 156]},
        "c5 aircross": {"nom": "C5 Aircross", "segment": "SUV", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [130, 180, 225]},
        "berlingo": {"nom": "Berlingo", "segment": "Ludospace", "carburants": ["Essence", "Diesel", "Électrique"], "puissances": [110, 130]},
        "c5x": {"nom": "C5 X", "segment": "Break", "carburants": ["Essence", "Hybride"], "puissances": [130, 180, 225]},
    }},
    "ds": {"nom": "DS", "modeles": {
        "ds3": {"nom": "DS 3", "segment": "Citadine", "carburants": ["Essence", "Électrique"], "puissances": [100, 155]},
        "ds4": {"nom": "DS 4", "segment": "Compacte", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [130, 180, 225]},
        "ds7": {"nom": "DS 7", "segment": "SUV", "carburants": ["Essence", "Hybride"], "puissances": [130, 225, 300]},
    }},
    "volkswagen": {"nom": "Volkswagen", "modeles": {
        "up": {"nom": "Up!", "segment": "Mini", "carburants": ["Essence"], "puissances": [60, 75]},
        "golf": {"nom": "Golf", "segment": "Compacte", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [115, 150, 245]},
        "polo": {"nom": "Polo", "segment": "Citadine", "carburants": ["Essence", "Diesel"], "puissances": [80, 95, 115]},
        "tiguan": {"nom": "Tiguan", "segment": "SUV", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [130, 150, 245]},
        "passat": {"nom": "Passat", "segment": "Berline", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [150, 200, 280]},
        "t-roc": {"nom": "T-Roc", "segment": "SUV", "carburants": ["Essence", "Diesel"], "puissances": [115, 150, 190]},
        "id.3": {"nom": "ID.3", "segment": "Compacte", "carburants": ["Électrique"], "puissances": [150, 204]},
        "id.4": {"nom": "ID.4", "segment": "SUV", "carburants": ["Électrique"], "puissances": [170, 204, 299]},
    }},
    "audi": {"nom": "Audi", "modeles": {
        "a1": {"nom": "A1", "segment": "Citadine", "carburants": ["Essence"], "puissances": [95, 150, 200]},
        "a3": {"nom": "A3", "segment": "Compacte", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [116, 150, 245]},
        "a4": {"nom": "A4", "segment": "Berline", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [150, 204, 349]},
        "q3": {"nom": "Q3", "segment": "SUV", "carburants": ["Essence", "Diesel"], "puissances": [150, 200]},
        "q5": {"nom": "Q5", "segment": "SUV", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [190, 286, 367]},
        "e-tron": {"nom": "e-tron", "segment": "SUV", "carburants": ["Électrique"], "puissances": [313, 408]},
    }},
    "bmw": {"nom": "BMW", "modeles": {
        "serie 1": {"nom": "Série 1", "segment": "Compacte", "carburants": ["Essence", "Diesel"], "puissances": [116, 150, 306]},
        "serie 3": {"nom": "Série 3", "segment": "Berline", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [150, 190, 374]},
        "serie 5": {"nom": "Série 5", "segment": "Berline", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [190, 286, 394]},
        "x1": {"nom": "X1", "segment": "SUV", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [150, 204]},
        "x3": {"nom": "X3", "segment": "SUV", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [190, 286]},
        "x5": {"nom": "X5", "segment": "SUV", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [286, 394, 625]},
    }},
    "mercedes": {"nom": "Mercedes-Benz", "modeles": {
        "classe a": {"nom": "Classe A", "segment": "Compacte", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [116, 150, 190]},
        "classe c": {"nom": "Classe C", "segment": "Berline", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [170, 200, 390]},
        "classe e": {"nom": "Classe E", "segment": "Berline", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [197, 265, 442]},
        "glc": {"nom": "GLC", "segment": "SUV", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [197, 265]},
        "classe b": {"nom": "Classe B", "segment": "Monospace", "carburants": ["Essence", "Diesel"], "puissances": [116, 150]},
    }},
    "toyota": {"nom": "Toyota", "modeles": {
        "aygo": {"nom": "Aygo", "segment": "Mini", "carburants": ["Essence"], "puissances": [72]},
        "yaris": {"nom": "Yaris", "segment": "Citadine", "carburants": ["Essence", "Hybride"], "puissances": [72, 116, 125]},
        "corolla": {"nom": "Corolla", "segment": "Compacte", "carburants": ["Hybride"], "puissances": [122, 180]},
        "rav4": {"nom": "RAV4", "segment": "SUV", "carburants": ["Hybride", "Hybride rechargeable"], "puissances": [218, 306]},
        "chr": {"nom": "C-HR", "segment": "SUV", "carburants": ["Hybride"], "puissances": [122, 184]},
        "prius": {"nom": "Prius", "segment": "Compacte", "carburants": ["Hybride"], "puissances": [122, 223]},
    }},
    "dacia": {"nom": "Dacia", "modeles": {
        "sandero": {"nom": "Sandero", "segment": "Citadine", "carburants": ["Essence", "GPL"], "puissances": [65, 90, 100]},
        "duster": {"nom": "Duster", "segment": "SUV", "carburants": ["Essence", "Diesel", "GPL"], "puissances": [90, 115, 150]},
        "logan": {"nom": "Logan", "segment": "Berline", "carburants": ["Essence", "GPL", "Diesel"], "puissances": [75, 95]},
        "spring": {"nom": "Spring", "segment": "Citadine", "carburants": ["Électrique"], "puissances": [45]},
        "jogger": {"nom": "Jogger", "segment": "Break", "carburants": ["Essence", "Hybride", "GPL"], "puissances": [110, 140]},
    }},
    "ford": {"nom": "Ford", "modeles": {
        "fiesta": {"nom": "Fiesta", "segment": "Citadine", "carburants": ["Essence", "Diesel"], "puissances": [95, 125, 200]},
        "focus": {"nom": "Focus", "segment": "Compacte", "carburants": ["Essence", "Diesel"], "puissances": [100, 150, 280]},
        "puma": {"nom": "Puma", "segment": "SUV", "carburants": ["Essence", "Hybride"], "puissances": [125, 155]},
        "kuga": {"nom": "Kuga", "segment": "SUV", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [150, 190, 243]},
        "mustang": {"nom": "Mustang", "segment": "Sportive", "carburants": ["Essence"], "puissances": [450, 466]},
    }},
    "fiat": {"nom": "Fiat", "modeles": {
        "500": {"nom": "500", "segment": "Mini", "carburants": ["Essence", "Électrique", "Hybride"], "puissances": [70, 95, 118]},
        "panda": {"nom": "Panda", "segment": "Citadine", "carburants": ["Essence", "GPL", "Hybride"], "puissances": [70, 85]},
        "tipo": {"nom": "Tipo", "segment": "Compacte", "carburants": ["Essence", "Diesel"], "puissances": [100, 130]},
    }},
    "hyundai": {"nom": "Hyundai", "modeles": {
        "i10": {"nom": "i10", "segment": "Mini", "carburants": ["Essence"], "puissances": [67, 84]},
        "i20": {"nom": "i20", "segment": "Citadine", "carburants": ["Essence", "Hybride"], "puissances": [84, 100]},
        "i30": {"nom": "i30", "segment": "Compacte", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [120, 159]},
        "tucson": {"nom": "Tucson", "segment": "SUV", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [150, 265]},
        "kona": {"nom": "Kona", "segment": "SUV", "carburants": ["Essence", "Hybride", "Électrique"], "puissances": [120, 204]},
    }},
    "kia": {"nom": "Kia", "modeles": {
        "picanto": {"nom": "Picanto", "segment": "Mini", "carburants": ["Essence"], "puissances": [67, 84]},
        "rio": {"nom": "Rio", "segment": "Citadine", "carburants": ["Essence"], "puissances": [84, 120]},
        "ceed": {"nom": "Ceed", "segment": "Compacte", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [120, 160]},
        "sportage": {"nom": "Sportage", "segment": "SUV", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [150, 265]},
        "ev6": {"nom": "EV6", "segment": "SUV", "carburants": ["Électrique"], "puissances": [229, 585]},
    }},
    "nissan": {"nom": "Nissan", "modeles": {
        "micra": {"nom": "Micra", "segment": "Citadine", "carburants": ["Essence"], "puissances": [92, 117]},
        "juke": {"nom": "Juke", "segment": "SUV", "carburants": ["Essence", "Hybride"], "puissances": [117, 143]},
        "qashqai": {"nom": "Qashqai", "segment": "SUV", "carburants": ["Essence", "Hybride"], "puissances": [140, 158]},
        "leaf": {"nom": "Leaf", "segment": "Compacte", "carburants": ["Électrique"], "puissances": [150]},
    }},
    "seat": {"nom": "Seat", "modeles": {
        "ibiza": {"nom": "Ibiza", "segment": "Citadine", "carburants": ["Essence"], "puissances": [80, 110, 150]},
        "leon": {"nom": "León", "segment": "Compacte", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [110, 150, 300]},
        "ateca": {"nom": "Ateca", "segment": "SUV", "carburants": ["Essence", "Diesel"], "puissances": [115, 150, 190]},
    }},
    "skoda": {"nom": "Škoda", "modeles": {
        "fabia": {"nom": "Fabia", "segment": "Citadine", "carburants": ["Essence"], "puissances": [80, 95, 110]},
        "octavia": {"nom": "Octavia", "segment": "Berline", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [115, 150, 245]},
        "kodiaq": {"nom": "Kodiaq", "segment": "SUV", "carburants": ["Essence", "Diesel"], "puissances": [150, 190, 245]},
        "enyaq": {"nom": "Enyaq", "segment": "SUV", "carburants": ["Électrique"], "puissances": [180, 265]},
    }},
    "opel": {"nom": "Opel", "modeles": {
        "corsa": {"nom": "Corsa", "segment": "Citadine", "carburants": ["Essence", "Diesel", "Électrique"], "puissances": [75, 100, 136]},
        "astra": {"nom": "Astra", "segment": "Compacte", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [110, 130, 180]},
        "mokka": {"nom": "Mokka", "segment": "SUV", "carburants": ["Essence", "Diesel", "Électrique"], "puissances": [100, 130, 156]},
    }},
    "volvo": {"nom": "Volvo", "modeles": {
        "xc40": {"nom": "XC40", "segment": "SUV", "carburants": ["Essence", "Hybride", "Électrique"], "puissances": [129, 197, 408]},
        "xc60": {"nom": "XC60", "segment": "SUV", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [197, 250, 455]},
        "v60": {"nom": "V60", "segment": "Break", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [150, 197, 455]},
    }},
    "mini": {"nom": "Mini", "modeles": {
        "mini": {"nom": "Mini", "segment": "Mini", "carburants": ["Essence", "Électrique"], "puissances": [102, 136, 184]},
        "countryman": {"nom": "Countryman", "segment": "SUV", "carburants": ["Essence", "Hybride"], "puissances": [136, 178, 306]},
    }},
    "tesla": {"nom": "Tesla", "modeles": {
        "model 3": {"nom": "Model 3", "segment": "Berline", "carburants": ["Électrique"], "puissances": [283, 498]},
        "model y": {"nom": "Model Y", "segment": "SUV", "carburants": ["Électrique"], "puissances": [299, 456]},
        "model s": {"nom": "Model S", "segment": "Berline", "carburants": ["Électrique"], "puissances": [670, 1020]},
        "model x": {"nom": "Model X", "segment": "SUV", "carburants": ["Électrique"], "puissances": [670, 1020]},
    }},
    "mazda": {"nom": "Mazda", "modeles": {
        "mazda2": {"nom": "Mazda2", "segment": "Citadine", "carburants": ["Essence", "Hybride"], "puissances": [75, 90]},
        "mazda3": {"nom": "Mazda3", "segment": "Compacte", "carburants": ["Essence", "Hybride"], "puissances": [122, 186]},
        "cx-5": {"nom": "CX-5", "segment": "SUV", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [165, 194]},
        "mx-5": {"nom": "MX-5", "segment": "Cabriolet", "carburants": ["Essence"], "puissances": [132, 184]},
    }},
    "suzuki": {"nom": "Suzuki", "modeles": {
        "swift": {"nom": "Swift", "segment": "Citadine", "carburants": ["Essence", "Hybride"], "puissances": [83, 129]},
        "vitara": {"nom": "Vitara", "segment": "SUV", "carburants": ["Essence", "Hybride"], "puissances": [115, 129]},
        "jimny": {"nom": "Jimny", "segment": "SUV", "carburants": ["Essence"], "puissances": [102]},
    }},
    "honda": {"nom": "Honda", "modeles": {
        "civic": {"nom": "Civic", "segment": "Compacte", "carburants": ["Essence", "Hybride"], "puissances": [129, 184]},
        "jazz": {"nom": "Jazz", "segment": "Citadine", "carburants": ["Hybride"], "puissances": [109, 122]},
        "cr-v": {"nom": "CR-V", "segment": "SUV", "carburants": ["Hybride"], "puissances": [184, 204]},
    }},
    "cupra": {"nom": "Cupra", "modeles": {
        "formentor": {"nom": "Formentor", "segment": "SUV Coupé", "carburants": ["Essence", "Hybride"], "puissances": [150, 310, 390]},
        "born": {"nom": "Born", "segment": "Compacte", "carburants": ["Électrique"], "puissances": [204, 231]},
    }},
    "mg": {"nom": "MG", "modeles": {
        "mg4": {"nom": "MG4", "segment": "Compacte", "carburants": ["Électrique"], "puissances": [170, 204, 435]},
        "zs": {"nom": "ZS", "segment": "SUV", "carburants": ["Essence", "Hybride"], "puissances": [106, 197]},
    }},
    "alfa romeo": {"nom": "Alfa Romeo", "modeles": {
        "giulietta": {"nom": "Giulietta", "segment": "Compacte", "carburants": ["Essence", "Diesel"], "puissances": [120, 150, 175]},
        "stelvio": {"nom": "Stelvio", "segment": "SUV", "carburants": ["Essence", "Diesel"], "puissances": [160, 210, 510]},
        "tonale": {"nom": "Tonale", "segment": "SUV", "carburants": ["Essence", "Hybride"], "puissances": [130, 160, 280]},
    }},
    "porsche": {"nom": "Porsche", "modeles": {
        "911": {"nom": "911", "segment": "Sportive", "carburants": ["Essence"], "puissances": [385, 525, 650]},
        "cayenne": {"nom": "Cayenne", "segment": "SUV", "carburants": ["Essence", "Hybride"], "puissances": [353, 470, 680]},
        "macan": {"nom": "Macan", "segment": "SUV", "carburants": ["Essence", "Électrique"], "puissances": [265, 360, 639]},
        "taycan": {"nom": "Taycan", "segment": "Berline", "carburants": ["Électrique"], "puissances": [408, 761]},
    }},
    "land rover": {"nom": "Land Rover", "modeles": {
        "defender": {"nom": "Defender", "segment": "SUV", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [200, 300, 404]},
        "discovery": {"nom": "Discovery", "segment": "SUV", "carburants": ["Essence", "Diesel"], "puissances": [249, 300]},
        "range rover evoque": {"nom": "Range Rover Evoque", "segment": "SUV", "carburants": ["Essence", "Diesel", "Hybride"], "puissances": [160, 249, 300]},
    }},
    "jeep": {"nom": "Jeep", "modeles": {
        "renegade": {"nom": "Renegade", "segment": "SUV", "carburants": ["Essence", "Hybride"], "puissances": [120, 190]},
        "compass": {"nom": "Compass", "segment": "SUV", "carburants": ["Essence", "Hybride"], "puissances": [130, 190]},
        "wrangler": {"nom": "Wrangler", "segment": "SUV", "carburants": ["Essence", "Hybride"], "puissances": [272, 380]},
    }},
    "lexus": {"nom": "Lexus", "modeles": {
        "ct": {"nom": "CT", "segment": "Compacte", "carburants": ["Hybride"], "puissances": [136]},
        "nx": {"nom": "NX", "segment": "SUV", "carburants": ["Hybride"], "puissances": [244, 309]},
        "ux": {"nom": "UX", "segment": "SUV", "carburants": ["Hybride", "Électrique"], "puissances": [184, 204]},
    }},
    "smart": {"nom": "Smart", "modeles": {
        "fortwo": {"nom": "Fortwo", "segment": "Mini", "carburants": ["Essence", "Électrique"], "puissances": [71, 82]},
        "forfour": {"nom": "Forfour", "segment": "Mini", "carburants": ["Essence", "Électrique"], "puissances": [71, 82]},
    }},
}

MAKE_ALIASES = {
    "vw": "volkswagen", "v.w.": "volkswagen", "mercedes-benz": "mercedes",
    "mercedes benz": "mercedes", "citroën": "citroen", "skoda": "skoda",
    "land-rover": "land rover", "rangerover": "land rover",
    "alfa": "alfa romeo", "ds automobiles": "ds", "chevrolet": "chevrolet",
}


# ==========================================================================
#  Décodage VIN — tables ISO 3779
# ==========================================================================
_VIN_TRANSLIT = {str(d): d for d in range(10)}
_VIN_TRANSLIT.update({c: v for c, v in zip("ABCDEFGH", range(1, 9))})
_VIN_TRANSLIT.update({c: v for c, v in zip("JKLMN", (1, 2, 3, 4, 5))})
_VIN_TRANSLIT.update({"P": 7, "R": 9})
_VIN_TRANSLIT.update({c: v for c, v in zip("STUVWXYZ", (2, 3, 4, 5, 6, 7, 8, 9))})
_VIN_WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]

# position 10 : code année (cycle de 30 ans)
_YEAR_CODES = "ABCDEFGHJKLMNPRSTVWXY123456789"


def vin_check_digit(vin: str) -> Optional[str]:
    """Calcule le digit de contrôle (position 9) selon ISO 3779."""
    vin = vin.upper()
    if len(vin) != 17:
        return None
    total = 0
    for i, ch in enumerate(vin):
        val = _VIN_TRANSLIT.get(ch)
        if val is None:
            return None
        total += val * _VIN_WEIGHTS[i]
    r = total % 11
    return "X" if r == 10 else str(r)


def vin_model_year(vin: str) -> List[int]:
    """Années plausibles d'après le caractère 10 (cycle de 30 ans)."""
    if len(vin) < 10:
        return []
    ch = vin[9].upper()
    if ch not in _YEAR_CODES:
        return []
    base = _YEAR_CODES.index(ch)
    now = datetime.now().year
    annees = []
    for cycle in (1980, 2010, 2040):
        y = cycle + base
        if y <= now + 1:
            annees.append(y)
    return annees


# ==========================================================================
#  Module principal
# ==========================================================================
class PlaqueOSINT:
    """Recherche véhicule : plaque française, VIN, ou marque/modèle."""

    NHTSA_VPIC = "https://vpic.nhtsa.dot.gov/api/vehicles"
    NHTSA_SAFETY = "https://api.nhtsa.gov/SafetyRatings"
    NHTSA_RECALLS = "https://api.nhtsa.gov/recalls/recallsByVehicle"
    CARQUERY = "https://www.carqueryapi.com/api/0.3/"

    # 24 lettres autorisées sur les plaques SIV (I et O exclues)
    ALPHA_PLAQUE = "ABCDEFGHJKLMNPQRSTUVWXYZ"

    RE_SIV = re.compile(r"^([A-HJ-NP-Z]{2})(\d{3})([A-HJ-NP-Z]{2})$")
    RE_FNI = re.compile(r"^(\d{1,4})([A-Z]{2,3})(2[AB]|\d{2})?$")
    RE_VIN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")

    TRIM_MAP = {
        "model_trim": "Finition", "model_year": "Année",
        "model_engine_cc": "Cylindrée (cm³)", "model_engine_cyl": "Cylindres",
        "model_engine_type": "Architecture moteur", "model_engine_power_ps": "Puissance (ch)",
        "model_engine_power_rpm": "Régime Pmax (tr/min)", "model_fuel_cap_l": "Réservoir (L)",
        "model_transmission_type": "Boîte", "model_drive": "Roues motrices",
        "model_seats": "Places", "model_doors": "Portes", "model_weight_kg": "Poids (kg)",
        "model_length_mm": "Longueur (mm)", "model_width_mm": "Largeur (mm)",
        "model_height_mm": "Hauteur (mm)", "model_wheelbase_mm": "Empattement (mm)",
        "model_0_to_100_kph": "0-100 km/h (s)", "model_top_speed_kph": "Vitesse max (km/h)",
        "model_lkm_city": "Conso ville (L/100)", "model_lkm_hwy": "Conso route (L/100)",
        "model_lkm_mixed": "Conso mixte (L/100)", "model_co2": "CO₂ (g/km)",
    }

    NHTSA_FIELDS = {
        "Make": "Marque", "Model": "Modèle", "Series": "Série", "Trim": "Finition",
        "ModelYear": "Année", "VehicleType": "Type", "BodyClass": "Carrosserie",
        "Doors": "Portes", "Seats": "Places", "EngineCylinders": "Cylindres",
        "DisplacementCC": "Cylindrée (cm³)", "DisplacementL": "Cylindrée (L)",
        "EngineModel": "Code moteur", "EngineHP": "Puissance (ch)",
        "FuelTypePrimary": "Carburant", "FuelTypeSecondary": "Carburant secondaire",
        "TransmissionStyle": "Transmission", "TransmissionSpeeds": "Rapports",
        "DriveType": "Transmission (roues)", "CurbWeightKG": "Poids (kg)",
        "GVWR": "PTAC", "PlantCity": "Ville d'assemblage",
        "PlantCountry": "Pays d'assemblage", "Manufacturer": "Constructeur",
        "Note": "Note", "SuggestedVIN": "VIN suggéré", "ErrorText": "Erreur NHTSA",
    }

    def __init__(self, target: Optional[str] = None, console: Any = None,
                 timeout: float = 15.0, cache_dir: Optional[str] = None,
                 use_cache: bool = True, offline: bool = False):
        self.target = target
        self.console = console
        self.timeout = timeout
        self.offline = offline
        self.vehicules_fr = VEHICULES_FR

        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._cache_dir = cache_dir or os.path.join(
            os.path.expanduser("~"), ".cache", "plaque_osint")
        self._cache_file = os.path.join(self._cache_dir, "cache.json")
        self._cache_dirty = False
        self._min_interval = 0.12
        self._last_call = 0.0
        self._stats = {"api_calls": 0, "cache_hits": 0, "errors": 0}
        self._last_error: Optional[str] = None
        self._session = None

        if use_cache:
            self._load_cache()
        if _HAS_REQUESTS and not offline:
            self._session = self._build_session()

    # ------------------------------------------------------------------
    #  Infrastructure HTTP
    # ------------------------------------------------------------------
    def _build_session(self):
        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        if _Retry is not None:
            try:
                retry = _Retry(total=3, backoff_factor=0.6,
                               status_forcelist=(429, 500, 502, 503, 504),
                               allowed_methods=frozenset(["GET"]))
            except TypeError:                             # urllib3 < 1.26
                retry = _Retry(total=3, backoff_factor=0.6,
                               status_forcelist=(429, 500, 502, 503, 504),
                               method_whitelist=frozenset(["GET"]))
            adapter = HTTPAdapter(max_retries=retry)
            s.mount("https://", adapter)
            s.mount("http://", adapter)
        return s

    def _load_cache(self):
        try:
            with open(self._cache_file, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            now = time.time()
            self._cache = {k: (v[0], v[1]) for k, v in raw.items()
                           if isinstance(v, list) and len(v) == 2
                           and now - v[0] < 30 * 86400}
        except Exception:
            self._cache = {}

    def save_cache(self):
        if not self._cache_dirty:
            return
        try:
            os.makedirs(self._cache_dir, exist_ok=True)
            items = dict(list(self._cache.items())[-400:])
            with open(self._cache_file, "w", encoding="utf-8") as fh:
                json.dump(items, fh)
            self._cache_dirty = False
        except Exception:
            pass

    def _http_get(self, url: str, params: Optional[dict] = None) -> Any:
        params = params or {}
        delta = time.time() - self._last_call
        if delta < self._min_interval:
            time.sleep(self._min_interval - delta)
        self._last_call = time.time()

        if self._session is not None:
            r = self._session.get(url, params=params, timeout=self.timeout)
            r.raise_for_status()
            return r.json()

        qs = urllib.parse.urlencode(params)
        full = url + ("?" + qs if qs else "")
        req = urllib.request.Request(
            full, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))

    def _get_json(self, url: str, params: Optional[dict] = None,
                  ttl: int = 86400, label: str = "") -> Optional[Any]:
        if self.offline:
            return None
        key = url + "|" + urllib.parse.urlencode(sorted((params or {}).items()))
        hit = self._cache.get(key)
        if hit and (time.time() - hit[0]) < ttl:
            self._stats["cache_hits"] += 1
            return hit[1]
        try:
            data = self._http_get(url, params)
            self._cache[key] = (time.time(), data)
            self._cache_dirty = True
            self._stats["api_calls"] += 1
            return data
        except Exception as exc:
            self._stats["errors"] += 1
            self._last_error = f"{label or url} : {exc}"
            return None

    # ------------------------------------------------------------------
    #  Console / saisie
    # ------------------------------------------------------------------
    def set_console(self, console):
        self.console = console
        return self

    def _print(self, message: Any = "", style: str = ""):
        if self.console is None:
            print(_strip_markup(message if isinstance(message, str) else str(message)))
            return
        if not isinstance(message, str):
            self.console.print(message)
            return
        if _HAS_RICH:
            try:
                txt = Text.from_markup(message)
            except Exception:
                txt = Text(message)
            if style:
                txt.stylize(style)
            self.console.print(txt)
        else:
            self.console.print(message)

    def _input(self, prompt: str = "") -> str:
        if self.console is not None:
            try:
                return self.console.input(prompt)
            except Exception:
                pass
        return input(_strip_markup(prompt))

    def _pause(self, texte: str = "Entrée pour continuer"):
        self._input(f"\n[dim]{texte}…[/dim]")

    # ------------------------------------------------------------------
    #  Validation / analyse de plaque
    # ------------------------------------------------------------------
    @staticmethod
    def _compact(v: str) -> str:
        return re.sub(r"[\s.\-_/]", "", (v or "").upper())

    def analyser_plaque(self, plaque: str) -> Optional[Dict[str, Any]]:
        c = self._compact(plaque)
        m_siv = self.RE_SIV.match(c)
        m_fni = self.RE_FNI.match(c)

        if m_siv:
            l1, num, l2 = m_siv.groups()
            res = {
                "Plaque": f"{l1}-{num}-{l2}",
                "Format": "SIV (depuis octobre 2009)",
                "Type": "Séquentielle nationale",
            }
            dept = self._dept_territorial(l2)
            if dept:
                nom, region = _DEPT_MAP.get(dept, ("?", "?"))
                res["Département encodé"] = f"{dept} — {nom} ({region})"
                res["Note"] = ("Renseigné uniquement si le titulaire a choisi son "
                               "département (plaque territoriale).")
            return res

        if m_fni:
            num, lettres, dept = m_fni.groups()
            res = {
                "Plaque": f"{num} {lettres} {dept or ''}".strip(),
                "Format": "FNI (avant octobre 2009)",
                "Type": "Immatriculation départementale",
                "Immatriculation d'origine": "Antérieure à octobre 2009",
            }
            if dept:
                code = dept.upper()
                if code in _DEPT_MAP:
                    nom, region = _DEPT_MAP[code]
                    res["Département"] = f"{code} — {nom}"
                    res["Région"] = region
                elif code == "20":
                    res["Département"] = "20 — Corse (2A/2B avant scission)"
                    res["Région"] = "Corse"
            return res

        return None

    def _dept_territorial(self, lettres: str) -> Optional[str]:
        """Département probable depuis les 2 dernières lettres d'une SIV territoriale."""
        try:
            n = (self.ALPHA_PLAQUE.index(lettres[0]) * 24
                 + self.ALPHA_PLAQUE.index(lettres[1]))
        except (ValueError, IndexError):
            return None
        idx = min(n * len(_DEPT_ORDRE) // 576, len(_DEPT_ORDRE) - 1)
        return _DEPT_ORDRE[idx]

    # ------------------------------------------------------------------
    #  VIN
    # ------------------------------------------------------------------
    def verifier_vin(self, vin: str) -> bool:
        return bool(self.RE_VIN.match((vin or "").strip().upper()))

    def analyser_vin(self, vin: str) -> Dict[str, Any]:
        vin = vin.strip().upper()
        cd = vin_check_digit(vin)
        annees = vin_model_year(vin)
        return {
            "WMI (1-3)": vin[:3],
            "VDS (4-8)": vin[3:8],
            "Digit de contrôle (9)": vin[8],
            "Digit attendu": cd or "n/a",
            "Digit conforme": "oui" if cd == vin[8] else "non",
            "Code année (10)": vin[9],
            "Année(s) plausible(s)": ", ".join(map(str, annees)) or "inconnue",
            "Plant (11)": vin[10],
            "N° de série (12-17)": vin[11:],
        }

    def decode_wmi(self, wmi: str) -> Optional[Dict[str, Any]]:
        data = self._get_json(f"{self.NHTSA_VPIC}/DecodeWMI/{wmi[:3].upper()}",
                              {"format": "json"}, label="WMI")
        results = (data or {}).get("Results") or []
        return results[0] if results else None

    def decode_vin(self, vin: str, year: Optional[int] = None) -> Optional[Dict[str, Any]]:
        params = {"format": "json"}
        if year:
            params["modelyear"] = year
        data = self._get_json(
            f"{self.NHTSA_VPIC}/DecodeVinValuesExtended/{vin.upper()}",
            params, label="NHTSA VIN")
        results = (data or {}).get("Results") or []
        return results[0] if results else None

    # ------------------------------------------------------------------
    #  Rappels & sécurité
    # ------------------------------------------------------------------
    def recalls(self, make: str, model: str, year: Any) -> List[Dict[str, Any]]:
        data = self._get_json(self.NHTSA_RECALLS,
                              {"make": make, "model": model, "modelYear": year},
                              label="NHTSA rappels")
        return (data or {}).get("results") or []

    def safety_ratings(self, year: Any, make: str, model: str) -> List[Dict[str, Any]]:
        url = (f"{self.NHTSA_SAFETY}/modelyear/{year}/make/"
               f"{urllib.parse.quote(str(make))}/model/{urllib.parse.quote(str(model))}")
        data = self._get_json(url, {"format": "json"}, label="NHTSA NCAP")
        return (data or {}).get("Results") or []

    # ------------------------------------------------------------------
    #  Modèles & fiches techniques
    # ------------------------------------------------------------------
    def get_models_for_make(self, make: str, year: Optional[int] = None) -> List[Dict[str, Any]]:
        if year:
            url = (f"{self.NHTSA_VPIC}/GetModelsForMakeYear/make/{urllib.parse.quote(make)}"
                   f"/modelyear/{year}")
        else:
            url = f"{self.NHTSA_VPIC}/GetModelsForMake/{urllib.parse.quote(make)}"
        data = self._get_json(url, {"format": "json"}, label="NHTSA modèles")
        return (data or {}).get("Results") or []

    def carquery_trims(self, make: str, model: Optional[str] = None,
                       year: Optional[int] = None) -> List[Dict[str, Any]]:
        params = {"cmd": "getTrims", "make": _slug(make), "sold_in_us": 0,
                  "format": "json"}
        if model:
            params["model"] = _slug(model)
        if year:
            params["year"] = year
        data = self._get_json(self.CARQUERY, params, label="CarQuery")
        return (data or {}).get("Trims") or []

    def fiche_carquery(self, make: str, model: str, year: Optional[int] = None) -> Optional[Dict[str, Any]]:
        trims = self.carquery_trims(make, model, year)
        if not trims:
            return None
        trim = trims[0]
        fiche = {}
        for cle, libelle in self.TRIM_MAP.items():
            val = trim.get(cle)
            if _clean(val):
                fiche[libelle] = val
        fiche["Source"] = "CarQuery API (fiche constructeur)"
        return fiche or None

    # ------------------------------------------------------------------
    #  Base locale
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_make(marque: str) -> Optional[str]:
        s = _slug(marque)
        if s in VEHICULES_FR:
            return s
        for alias, cible in MAKE_ALIASES.items():
            if _slug(alias) == s:
                return cible
        for cle in VEHICULES_FR:
            if s and (s in _slug(cle) or _slug(cle) in s):
                return cle
        return None

    def rechercher_vehicule_local(self, marque: str, modele: Optional[str] = None):
        make = self._resolve_make(marque)
        if not make:
            return None
        data = VEHICULES_FR[make]

        if not modele:
            return {"marque": data["nom"], "modeles": list(data["modeles"].keys()),
                    "data": data["modeles"]}

        cible = _slug(modele)
        modeles = data["modeles"]
        for cle, val in modeles.items():
            if _slug(cle) == cible:
                return {"marque": data["nom"], "modele": val["nom"], "data": val}
        for cle, val in modeles.items():
            if cible and cible in _slug(cle):
                return {"marque": data["nom"], "modele": val["nom"], "data": val}
        return None

    def lister_marques(self) -> List[Tuple[str, str, int]]:
        return sorted(((k, v["nom"], len(v["modeles"])) for k, v in VEHICULES_FR.items()))

    # ------------------------------------------------------------------
    #  Fiche estimée (déterministe)
    # ------------------------------------------------------------------
    def generer_fiche_estimee(self, marque: str, modele: str,
                              annee: Optional[Any] = None) -> Optional[Dict[str, Any]]:
        vehicule = self.rechercher_vehicule_local(marque, modele)
        if not vehicule or "data" not in vehicule:
            return None

        data = vehicule["data"]
        rnd = random.Random(f"{_slug(marque)}|{_slug(modele)}|{annee}")
        carburant = rnd.choice(data["carburants"])
        puissance = rnd.choice(data["puissances"])
        segment = data["segment"]
        est = _SEGMENTS.get(segment, _SEGMENTS["Berline"])

        if carburant.lower().startswith("élect"):
            conso = f"{est['kwh'][0]}-{est['kwh'][1]} kWh/100 km"
        else:
            conso = f"{est['l100'][0]:.1f}-{est['l100'][1]:.1f} L/100 km"

        prix = "Non disponible"
        if annee and str(annee).isdigit():
            age = datetime.now().year - int(annee)
            bareme = [(1, "22 000 - 50 000 €"), (3, "15 000 - 35 000 €"),
                      (5, "10 000 - 25 000 €"), (10, "5 000 - 15 000 €")]
            for limite, valeur in bareme:
                if age <= limite:
                    prix = valeur
                    break
            else:
                prix = "Moins de 8 000 €"

        return {
            "Marque": vehicule["marque"],
            "Modèle": vehicule.get("modele", modele),
            "Segment": segment,
            "Année": annee or "non spécifiée",
            "Carburant": carburant,
            "Puissance": f"{puissance} ch",
            "Places": est["places"],
            "Portes": est["portes"],
            "Volume de coffre": est["coffre"],
            "Consommation estimée": conso,
            "Prix estimé (occasion)": prix,
            "Source": "Base locale — estimation",
        }

    # ------------------------------------------------------------------
    #  Affichage
    # ------------------------------------------------------------------
    def afficher_fiche(self, data: Dict[str, Any], titre: str = "Fiche technique"):
        if not self.console or not _HAS_RICH:
            for k, v in data.items():
                print(f"{k}: {v}")
            return
        table = Table(title=titre, header_style="bold magenta", show_lines=False)
        table.add_column("Caractéristique", style="cyan", no_wrap=True)
        table.add_column("Valeur", style="green")
        for k, v in data.items():
            style = "dim italic" if str(k).startswith("Source") else "green"
            table.add_row(str(k), str(v), style=style)
        self.console.print(table)

    def afficher_vin(self, data: Dict[str, Any]):
        self.afficher_fiche(data, "Structure du VIN (ISO 3779)")

    def afficher_nhtsa(self, data: Dict[str, Any]):
        if not self.console or not _HAS_RICH:
            self.afficher_fiche(data)
            return
        table = Table(title="Décodage VIN — NHTSA vPIC", header_style="bold blue")
        table.add_column("Attribut", style="cyan", no_wrap=True)
        table.add_column("Valeur", style="green")
        for champ, libelle in self.NHTSA_FIELDS.items():
            val = data.get(champ)
            if _clean(val):
                table.add_row(libelle, str(val))
        self.console.print(table)

    def afficher_recalls(self, rappels: List[Dict[str, Any]], limite: int = 10):
        if not rappels:
            self._print("  Aucun rappel enregistré (NHTSA, marché US).", "dim")
            return
        self._print(f"\n[bold red]⚠ {len(rappels)} campagne(s) de rappel[/bold red]")
        for r in rappels[:limite]:
            self._print(Panel(
                f"[bold]{r.get('Component', 'Composant inconnu')}[/bold]\n"
                f"[dim]Campagne {r.get('NHTSACampaignNumber', '?')} — "
                f"{r.get('ReportReceivedDate', '?')}[/dim]\n\n"
                f"{_wrap(r.get('Summary', ''))}\n\n"
                f"[italic]Remède : {_wrap(r.get('Remedy', 'non précisé'), max_lines=3)}[/italic]",
                border_style="red", title_align="left"))
        if len(rappels) > limite:
            self._print(f"  … et {len(rappels) - limite} autres.", "dim")

    # ------------------------------------------------------------------
    #  Détection automatique de cible
    # ------------------------------------------------------------------
    def detecter(self, valeur: str) -> Optional[Tuple[str, str]]:
        v = (valeur or "").strip()
        if not v:
            return None
        c = self._compact(v)
        if self.RE_SIV.match(c) or self.RE_FNI.match(c):
            return ("plaque", v)
        if self.verifier_vin(v):
            return ("vin", v.upper())
        return ("texte", v)

    # ------------------------------------------------------------------
    #  Export
    # ------------------------------------------------------------------
    @staticmethod
    def exporter(data: Any, prefixe: str = "vehicule") -> str:
        nom = re.sub(r"[^A-Za-z0-9_-]", "", prefixe)[:40] or "vehicule"
        chemin = f"{nom}_{datetime.now():%Y%m%d_%H%M%S}.json"
        with open(chemin, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        return chemin

    # ------------------------------------------------------------------
    #  Actions du menu
    # ------------------------------------------------------------------
    def action_plaque(self, plaque: str):
        info = self.analyser_plaque(plaque)
        if not info:
            self._print(f"❌ '{plaque}' n'est pas une plaque française reconnue.", "red")
            return None
        self._print(Panel.fit("[bold blue]Analyse de plaque[/bold blue]",
                              border_style="blue"))
        self.afficher_fiche(info, "Immatriculation")
        return info

    def action_vin(self, vin: str, annee: Optional[int] = None):
        vin = vin.strip().upper()
        if not self.verifier_vin(vin):
            self._print("❌ VIN invalide (17 caractères, sans I, O, Q).", "red")
            return None
        self.afficher_vin(self.analyser_vin(vin))

        self._print("\n⏳ Décodage NHTSA…", "blue")
        data = self.decode_vin(vin, annee)
        if not data:
            self._print(f"❌ Aucune réponse NHTSA. {self._last_error or ''}", "red")
            return None

        if _clean(data.get("Make")):
            self.afficher_nhtsa(data)

            wmi = self.decode_wmi(vin[:3])
            if wmi and _clean(wmi.get("Make")):
                self._print(f"\n[cyan]WMI {vin[:3]}[/cyan] → "
                            f"{wmi.get('Make')} / {wmi.get('VehicleType', '?')} "
                            f"({wmi.get('Country', 'pays inconnu')})")

            make, model = data.get("Make"), data.get("Model")
            yr = data.get("ModelYear") or annee
            if make and model and yr:
                rappels = self.recalls(make, model, yr)
                self.afficher_recalls(rappels)
                notes = self.safety_ratings(yr, make, model)
                if notes:
                    self.afficher_fiche(notes[0], "Sécurité NCAP (US)")
            return data

        err = data.get("ErrorText") or "VIN non reconnu"
        self._print(f"❌ {err}", "red")
        self._print("Note : l'API NHTSA couvre en priorité le marché nord-américain.",
                    "dim")
        return data

    def action_marque(self, marque: str, modele: Optional[str] = None,
                      annee: Optional[int] = None):
        res = self.rechercher_vehicule_local(marque, modele)
        if not res:
            self._print(f"❌ Marque/modèle '{marque} {modele or ''}' absent de la base locale.",
                        "red")
            self._print("   Essayez la recherche NHTSA (option 4) pour les marques étrangères.",
                        "dim")
            return None

        if "modeles" in res:
            self._print(f"\n✅ {len(res['modeles'])} modèles pour {res['marque']} :", "green")
            cles = sorted(res["modeles"])
            for i, cle in enumerate(cles, 1):
                self._print(f"  {i:2}. {res['modeles'][cle]['nom']}")
            choix = self._input("\n[bold yellow]➤ Numéro à détailler (Entrée pour quitter) : [/bold yellow]").strip()
            if not choix.isdigit() or not (1 <= int(choix) <= len(cles)):
                return res
            modele = cles[int(choix) - 1]

        fiche = self.fiche_carquery(res["marque"], res.get("modele") or modele, annee)
        if fiche:
            self.afficher_fiche(fiche, f"Fiche réelle — {res['marque']} {res.get('modele', '')}")
        else:
            self._print("  (CarQuery indisponible, fiche estimée uniquement)", "dim")

        estimee = self.generer_fiche_estimee(marque, modele or res.get("modele", ""), annee)
        if estimee:
            self.afficher_fiche(estimee, "Estimation base locale")
        return estimee or fiche

    # ------------------------------------------------------------------
    #  Menu
    # ------------------------------------------------------------------
    def menu(self) -> str:
        self._print("\n[bold cyan]─── PlaqueOSINT ───[/bold cyan]")
        options = [
            ("1", "🔎 Analyser une PLAQUE française (département / région)"),
            ("2", "🚗 Recherche marque + modèle (base locale + fiche réelle)"),
            ("3", "🔖 Décoder un VIN (structure + NHTSA + rappels + NCAP)"),
            ("4", "🌍 Modèles d'un constructeur via NHTSA (marques étrangères)"),
            ("5", "📋 Lister les marques de la base locale"),
            ("6", "🎯 Analyser la cible fournie au module"),
            ("7", "📊 Statistiques / cache"),
            ("0", "🔙 Retour"),
        ]
        for num, libelle in options:
            couleur = "red" if num == "0" else "bold cyan"
            self._print(f"[{couleur}]{num}.[/{couleur}] {libelle}")
        return self._input("[bold yellow]➤ Choix : [/bold yellow]").strip()

    def run_scan(self):
        try:
            from utile.display import console as main_console
            self.set_console(main_console)
        except Exception:
            pass

        if _HAS_RICH and self.console:
            self._print(Panel.fit(
                f"[bold blue]Recherche Véhicule[/bold blue]  [dim]v{VERSION}[/dim]\n"
                "[dim]NHTSA · CarQuery · base locale — aucune clé API requise[/dim]",
                border_style="blue"))

        if self.target:
            self._traiter_cible(self.target)

        while True:
            choix = self.menu()

            if choix == "0":
                break
            if choix == "1":
                self.action_plaque(self._input("[bold yellow]➤ Plaque (ex: AB-123-CD) : [/bold yellow]"))
            elif choix == "2":
                marque = self._input("[bold yellow]➤ Marque (ex: Renault) : [/bold yellow]").strip()
                if not marque:
                    self._print("❌ Marque requise.", "red")
                    continue
                modele = self._input("[bold yellow]➤ Modèle (Entrée = liste) : [/bold yellow]").strip() or None
                annee = self._input("[bold yellow]➤ Année (optionnel) : [/bold yellow]").strip()
                self.action_marque(marque, modele, int(annee) if annee.isdigit() else None)
            elif choix == "3":
                vin = self._input("[bold yellow]➤ VIN (17 caractères) : [/bold yellow]").strip().upper()
                annee = self._input("[bold yellow]➤ Année modèle (optionnel) : [/bold yellow]").strip()
                data = self.action_vin(vin, int(annee) if annee.isdigit() else None)
                if data and self._input("[bold yellow]➤ Exporter en JSON ? (o/n) : [/bold yellow]").lower().startswith("o"):
                    self._print(f"💾 {self.exporter(data, 'vin_' + vin)}", "green")
            elif choix == "4":
                marque = self._input("[bold yellow]➤ Marque (en anglais, ex: Honda) : [/bold yellow]").strip()
                if not marque:
                    continue
                annee = self._input("[bold yellow]➤ Année (optionnel) : [/bold yellow]").strip()
                self._print(f"\n⏳ Recherche {marque}…", "blue")
                modeles = self.get_models_for_make(marque, int(annee) if annee.isdigit() else None)
                if modeles:
                    self._print(f"✅ {len(modeles)} modèles :", "green")
                    for i, m in enumerate(modeles[:40], 1):
                        self._print(f"  {i:2}. {m.get('Make_Name', marque)} {m.get('Model_Name', '?')}")
                    if len(modeles) > 40:
                        self._print(f"  … et {len(modeles) - 40} autres.", "dim")
                else:
                    self._print("❌ Aucun résultat.", "red")
            elif choix == "5":
                marques = self.lister_marques()
                for i, (_, nom, nb) in enumerate(marques, 1):
                    self._print(f"  {i:2}. {nom:<22} ({nb} modèles)")
                self._print(f"\nTotal : {len(marques)} marques.", "dim")
            elif choix == "6":
                cible = self._input("[bold yellow]➤ Cible (plaque / VIN / texte) : [/bold yellow]")
                self._traiter_cible(cible)
            elif choix == "7":
                self._print(json.dumps(self._stats, indent=2))
                self._print(f"Cache : {len(self._cache)} entrées — {self._cache_file}", "dim")
                if self._last_error:
                    self._print(f"Dernière erreur : {self._last_error}", "dim")
            else:
                self._print("❌ Choix invalide.", "red")

            self._pause()

        self.save_cache()

    def _traiter_cible(self, cible: str):
        det = self.detecter(cible)
        if not det:
            return
        type_, valeur = det
        self._print(f"\n[bold]Cible détectée :[/bold] {type_} → {valeur}")
        if type_ == "plaque":
            self.action_plaque(valeur)
        elif type_ == "vin":
            self.action_vin(valeur)
        else:
            self.action_marque(valeur)

    def run(self):
        """Alias de run_scan (nom attendu par certains lanceurs)."""
        return self.run_scan()


PlaqueAnalyzer = PlaqueOSINT
VehicleOSINT = PlaqueOSINT


# ==========================================================================
#  Points d'entrée
# ==========================================================================
def run(target: Optional[str] = None):
    """Point d'entrée Fox_app : run(target)."""
    module = PlaqueOSINT(target)
    try:
        module.run_scan()
    finally:
        module.save_cache()


def main(argv: Optional[List[str]] = None):
    p = argparse.ArgumentParser(
        prog="plaque_osint",
        description="PlaqueOSINT v2 — OSINT véhicule (plaque FR, VIN, marque/modèle)",
        formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("target", nargs="?", help="plaque, VIN ou marque")
    p.add_argument("--vin", help="décoder directement un VIN")
    p.add_argument("--plaque", help="analyser directement une plaque")
    p.add_argument("--marque", help="recherche par marque")
    p.add_argument("--modele", help="modèle associé à --marque")
    p.add_argument("--annee", type=int, help="année du modèle")
    p.add_argument("--json", action="store_true", help="sortie JSON brute")
    p.add_argument("--no-cache", action="store_true", help="désactiver le cache disque")
    p.add_argument("--offline", action="store_true", help="base locale uniquement")
    p.add_argument("--timeout", type=float, default=15.0)
    args = p.parse_args(argv)

    mod = PlaqueOSINT(args.target, timeout=args.timeout,
                      use_cache=not args.no_cache, offline=args.offline)

    if args.vin:
        data = mod.action_vin(args.vin, args.annee)
    elif args.plaque:
        data = mod.action_plaque(args.plaque)
    elif args.marque:
        data = mod.action_marque(args.marque, args.modele, args.annee)
    elif args.target:
        det = mod.detecter(args.target)
        if not det:
            print("Cible vide.")
            return
        type_, valeur = det
        data = {"plaque": mod.action_plaque, "vin": mod.action_vin,
                "texte": mod.action_marque}[type_](valeur)
    else:
        mod.run_scan()
        mod.save_cache()
        return

    if args.json and data:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    mod.save_cache()


if __name__ == "__main__":
    main()