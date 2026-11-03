from __future__ import annotations

import builtins
import glob
import importlib
import importlib.util
import inspect
import io
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

# ── Chemins ──────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
# sous-dossiers en repli (imports "à plat") : on couvre TOUTE l'arborescence
for p in (ROOT, ROOT / "core", ROOT / "utile", ROOT / "W_A", ROOT / "W_F", ROOT / "W_H",
          ROOT / "W_I", ROOT / "W_J", ROOT / "W_O", ROOT / "W_S"):
    if str(p) not in sys.path:
        sys.path.append(str(p))

# ── Dépendances ──────────────────────────────────────────────────
for dep in ("textual", "rich"):
    if importlib.util.find_spec(dep) is None:
        print(f"[ERREUR] '{dep}' manquant. Installez-le avec : pip install {dep}")
        sys.exit(1)

from rich import box
from rich.markup import escape
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import (
    Button, ContentSwitcher, DirectoryTree, Footer, Header, Input, Label,
    OptionList, ProgressBar, RichLog, Select, Static, Switch, TabbedContent,
    TabPane, TextArea,
)
from textual.widgets.option_list import Option

try:
    from utile.display import (build_banner_body, console as term_console,
                               get_hostname, get_public_ip)
except ModuleNotFoundError as exc:
    print(f"[ERREUR] utile/display.py introuvable ({exc}).")
    sys.exit(1)

# ── Imports W_I (page native) ────────────────────────────────────
AI_ERROR: Exception | None = None
STYLE_LABELS: dict = {}
try:
    from W_I.detecteur import analyze_text, AnalysisResult
    from W_I.anti_detecteur import MetadataCleaner
    from W_I.refile import TextReformatter, STYLE_LABELS
except Exception as exc:  # noqa: BLE001
    AI_ERROR = exc

# ── Imports W_J (page native) ────────────────────────────────────
VERIF_ERROR: Exception | None = None
STEM_AVAILABLE = False
try:
    from W_J.idee import TorSearchEngine, STEM_AVAILABLE
except Exception as exc:  # noqa: BLE001
    VERIF_ERROR = exc

# ── Imports W_F (page native Flipper Zero) ───────────────────────
FLIPPER_ERROR: Exception | None = None
try:
    from serial.tools import list_ports
    from W_F.flipper_ctl import FlipperUSB
except Exception as exc:  # noqa: BLE001
    FLIPPER_ERROR = exc

# ── Imports W_F (page native ESP32) ──────────────────────────────
ESP32_ERROR: Exception | None = None
try:
    import serial
    from W_F import esp32_app as esp   # constantes partagées avec le script autonome
except Exception as exc:  # noqa: BLE001
    ESP32_ERROR = exc

# ═════════════════════════════════════════════════════════════════
#  Couleurs / constantes
# ═════════════════════════════════════════════════════════════════
C_GREEN, C_LIME, C_ORANGE, C_AMBER, C_RED = "#2ECC71", "#A8E063", "#F39C12", "#FF8C42", "#FF6B6B"
C_MUTED = "#7A788A"

HUMANIZE_MODES = [
    "subtil", "fort", "extreme", "furtif", "etudiant", "pro", "academique",
    "journaliste", "technique", "scientifique", "juridique", "medical",
    "marketing", "historique", "philo", "educatif",
]
DIMENSIONS = [
    "Perplexité lex.", "Uniformité phrases", "Marqueurs IA", "Richesse ponctuation",
    "Diversité lexicale", "Structures IA", "Burstiness", "Ton assertif/prudent",
]
SUPPORTED_EXT = {".txt", ".md", ".pdf", ".docx"}

FLIPPER_REMOTE_DIR = "/ext/apps/Scripts"   # dossier des scripts JS sur la carte SD
FLIPPER_TEMPLATE = """\
// Script exécuté directement sur le Flipper Zero
print("Hello depuis Watch Fox !");
delay(500);
print("Terminé");
"""

# ═════════════════════════════════════════════════════════════════
#  W_F · Boutons rapides (onglet « ⚡ Boutons » des pages Flipper / ESP32)
# ═════════════════════════════════════════════════════════════════
FLIPPER_QUICK_JS = f"{FLIPPER_REMOTE_DIR}/_quick.js"   # script temporaire des boutons JS
QB_FILE = ROOT / "quick_buttons.json"                  # boutons créés par l'utilisateur

def qb_load(key: str) -> list[dict]:
    try:
        data = json.loads(QB_FILE.read_text(encoding="utf-8")).get(key, [])
        return [d for d in data if {"label", "type", "value"} <= set(d)]
    except Exception:  # noqa: BLE001
        return []

def qb_save(key: str, items: list[dict]) -> None:
    try:
        data = json.loads(QB_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        data = {}
    data[key] = items
    QB_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def qb_lines(payload) -> list[str]:
    """Liste de commandes : déjà une liste, ou texte séparé par « ; »."""
    if isinstance(payload, list):
        return payload
    return [c.strip() for c in str(payload).split(";") if c.strip()]

# Boutons : (libellé, type, contenu[, confirmation])
#   Flipper : "cli" (commandes CLI, "sleep X" = pause) / "js" (script envoyé + exécuté)
FLIPPER_QA = [
    ("📟 APPAREIL", [
        ("ℹ Infos appareil", "cli", ["device_info"]),
        ("🔋 Batterie", "cli", ["power info"]),
        ("💾 Stockage SD", "cli", ["storage info /ext"]),
        ("📂 Fichiers /ext", "cli", ["storage list /ext"]),
        ("🕒 Date / heure", "cli", ["date"]),
        ("⏱ Uptime", "cli", ["uptime"]),
        ("🧠 Mémoire libre", "cli", ["free"]),
        ("📋 Processus", "cli", ["ps"]),
    ]),
    ("✨ EFFETS", [
        ("📳 Vibrer", "cli", ["vibro 1", "sleep 0.4", "vibro 0"]),
        ("🔴 LED rouge", "cli", ["led r 255", "led g 0", "led b 0"]),
        ("🟢 LED verte", "cli", ["led r 0", "led g 255", "led b 0"]),
        ("🔵 LED bleue", "cli", ["led r 0", "led g 0", "led b 255"]),
        ("⚫ LED éteinte", "cli", ["led r 0", "led g 0", "led b 0"]),
    ]),
    ("🎮 TÉLÉCOMMANDE", [
        ("⬆ Haut", "cli", ["input send up short"]),
        ("⬇ Bas", "cli", ["input send down short"]),
        ("⬅ Gauche", "cli", ["input send left short"]),
        ("➡ Droite", "cli", ["input send right short"]),
        ("⏺ OK", "cli", ["input send ok short"]),
        ("↩ Retour", "cli", ["input send back short"]),
    ]),
    ("🚀 APPLICATIONS", [
        ("📜 Lister les apps", "cli", ["loader list"]),
        ("📡 Ouvrir Sub-GHz", "cli", ['loader open "Sub-GHz"']),
        ("📺 Ouvrir Infrarouge", "cli", ['loader open "Infrared"']),
        ("💳 Ouvrir NFC", "cli", ['loader open "NFC"']),
        ("✖ Fermer l'app", "cli", ["loader close"]),
    ]),
    ("🟨 SCRIPTS JS", [
        ("💬 Hello", "js", 'print("Hello depuis le bouton !");\ndelay(500);\nprint("Fini");\n'),
        ("🔔 Notif succès", "js", 'let notify = require("notification");\nnotify.success();\n'),
        ("🚨 Notif erreur", "js", 'let notify = require("notification");\nnotify.error();\n'),
        ("💡 Clignoter bleu", "js", 'let notify = require("notification");\nnotify.blink("blue", "long");\n'),
    ]),
]

ESP_SK_CONSOLE = r"""// Console de commandes : l'ESP32 répond aux boutons "Console série"
#include <WiFi.h>
#ifndef LED_BUILTIN
#define LED_BUILTIN 2
#endif

void setup() {
  Serial.begin(115200);
  pinMode(LED_BUILTIN, OUTPUT);
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  delay(1000);
  Serial.println("Console prete. Tape help");
}

void loop() {
  if (!Serial.available()) return;
  String c = Serial.readStringUntil('\n');
  c.trim();
  c.toLowerCase();
  if (c == "help") {
    Serial.println("help | info | led on | led off | scan | reboot");
  } else if (c == "info") {
    Serial.printf("Puce : %s, %d coeur(s), %d MHz\n", ESP.getChipModel(), (int)ESP.getChipCores(), (int)ESP.getCpuFreqMHz());
    Serial.printf("RAM libre : %u octets\n", (unsigned)ESP.getFreeHeap());
    Serial.println("MAC : " + WiFi.macAddress());
  } else if (c == "led on") {
    digitalWrite(LED_BUILTIN, HIGH);
    Serial.println("LED allumee");
  } else if (c == "led off") {
    digitalWrite(LED_BUILTIN, LOW);
    Serial.println("LED eteinte");
  } else if (c == "scan") {
    int n = WiFi.scanNetworks();
    Serial.printf("%d reseaux\n", n);
    for (int i = 0; i < n; i++)
      Serial.printf("%2d | %-28s | %4d dBm | canal %d\n", i + 1, WiFi.SSID(i).c_str(), (int)WiFi.RSSI(i), WiFi.channel(i));
    WiFi.scanDelete();
  } else if (c == "reboot") {
    Serial.println("Redemarrage...");
    delay(200);
    ESP.restart();
  } else if (c.length()) {
    Serial.println("Commande inconnue : " + c);
  }
}
"""

ESP_SK_BLINK = r"""// Fait clignoter la LED et écrit dans le moniteur série
#ifndef LED_BUILTIN
#define LED_BUILTIN 2
#endif

void setup() {
  Serial.begin(115200);
  pinMode(LED_BUILTIN, OUTPUT);
}

void loop() {
  digitalWrite(LED_BUILTIN, HIGH);
  Serial.println("LED ON");
  delay(500);
  digitalWrite(LED_BUILTIN, LOW);
  Serial.println("LED OFF");
  delay(500);
}
"""

ESP_SK_WIFI = r"""// Scan des réseaux WiFi toutes les 5 secondes
#include <WiFi.h>

void setup() {
  Serial.begin(115200);
  delay(1000);
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
}

void loop() {
  Serial.println("--- Scan WiFi ---");
  int n = WiFi.scanNetworks();
  if (n <= 0) Serial.println("Aucun reseau");
  for (int i = 0; i < n; i++)
    Serial.printf("%2d | %-28s | %4d dBm | canal %d\n", i + 1, WiFi.SSID(i).c_str(), (int)WiFi.RSSI(i), WiFi.channel(i));
  WiFi.scanDelete();
  delay(5000);
}
"""

ESP_SK_INFO = r"""// Affiche les infos de la puce puis ne fait plus rien
void setup() {
  Serial.begin(115200);
  delay(1500);
  Serial.printf("Puce : %s (rev %d)\n", ESP.getChipModel(), (int)ESP.getChipRevision());
  Serial.printf("Coeurs : %d @ %d MHz\n", (int)ESP.getChipCores(), (int)ESP.getCpuFreqMHz());
  Serial.printf("Flash : %u Mo\n", (unsigned)(ESP.getFlashChipSize() / (1024 * 1024)));
  Serial.printf("RAM libre : %u octets\n", (unsigned)ESP.getFreeHeap());
  Serial.printf("MAC : %llX\n", ESP.getEfuseMac());
}

void loop() {}
"""

ESP_SK_I2C = r"""// Scan du bus I2C (pins par défaut de la carte)
#include <Wire.h>

void setup() {
  Serial.begin(115200);
  delay(1000);
  Wire.begin();
}

void loop() {
  Serial.println("--- Scan I2C ---");
  int found = 0;
  for (uint8_t a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      Serial.printf("Peripherique en 0x%02X\n", a);
      found++;
    }
  }
  if (!found) Serial.println("Aucun peripherique");
  delay(3000);
}
"""

ESP_SK_HELLO = r"""// Sketch Arduino (C/C++) pour ESP32
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("Hello depuis l'ESP32 !");
}

void loop() {
  Serial.println("tick");
  delay(1000);
}
"""

#   ESP32 : "serial" (lignes envoyées) / "sketch" (compilé + téléversé) /
#           "esptool" (arguments esptool) / "reset" / "boot" (impulsion RTS/DTR)
ESP32_QA = [
    ("🔌 CARTE", [
        ("🔁 Reset", "reset", None),
        ("📋 Reset + voir la sortie", "resetcap", None),
        ("🛠 Mode bootloader", "boot", None),
        ("🔍 Infos puce (esptool)", "esptool", ["flash_id"]),
        ("🧹 Effacer la flash", "esptool", ["erase_flash"], True),
    ]),
    ("⌨ CONSOLE SÉRIE (sketch console requis)", [
        ("❓ help", "serial", ["help"]),
        ("ℹ info", "serial", ["info"]),
        ("💡 LED on", "serial", ["led on"]),
        ("🌑 LED off", "serial", ["led off"]),
        ("📶 Scan WiFi", "serial", ["scan"]),
        ("♻ Reboot", "serial", ["reboot"]),
    ]),
    ("📦 SKETCHS EN 1 CLIC (compile + téléverse)", [
        ("⌨ Installer la console", "sketch", ESP_SK_CONSOLE),
        ("💡 Blink LED", "sketch", ESP_SK_BLINK),
        ("📶 Scanner WiFi", "sketch", ESP_SK_WIFI),
        ("🔍 Infos puce", "sketch", ESP_SK_INFO),
        ("🔌 Scanner I2C", "sketch", ESP_SK_I2C),
        ("👋 Hello", "sketch", ESP_SK_HELLO),
    ]),
    ("🦈 MARAUDER (si installé)", [
        ("❓ help", "serial", ["help"]),
        ("📡 Scan AP", "serial", ["scanap"]),
        ("📋 Liste AP", "serial", ["list -a"]),
        ("⏹ Stop scan", "serial", ["stopscan"]),
    ]),
]

class ActionButton(Button):
    """Bouton qui porte sa propre action."""

    def __init__(self, title: str, kind: str, payload, confirm: bool = False) -> None:
        super().__init__(title, classes="qa")
        self.qa_title, self.qa_kind, self.qa_payload = title, kind, payload
        self.qa_confirm, self.qa_armed = confirm, False

class QuickPanel(Vertical):
    """Onglet « ⚡ Boutons » : grille de boutons par catégorie, boutons personnalisés
    (enregistrés dans quick_buttons.json) et zone de résultat. Un clic envoie le message
    QuickPanel.Run que la page (Flipper / ESP32) exécute."""

    class Run(Message):
        def __init__(self, button: ActionButton) -> None:
            super().__init__()
            self.button = button

    def __init__(self, prefix: str, key: str, groups: list, kinds: list,
                 editor_id: str, editor_kind: str, hint: str) -> None:
        super().__init__(id=f"{prefix}-qa")
        self.prefix, self.key, self.groups, self.kinds = prefix, key, groups, kinds
        self.editor_id, self.editor_kind, self.hint = editor_id, editor_kind, hint
        self.custom: list[dict] = qb_load(key)

    def compose(self) -> ComposeResult:
        p = self.prefix
        with VerticalScroll(classes="qa-scroll"):
            for title, actions in self.groups:
                yield Label(title, classes="qa-title")
                with Grid(classes="qa-grid"):
                    for item in actions:
                        yield ActionButton(*item)
            yield Label("⭐ MES BOUTONS", classes="qa-title")
            yield Grid(id=f"{p}-qa-custom", classes="qa-grid")
            yield Label("➕ CRÉER UN BOUTON", classes="qa-title")
            yield Input(placeholder="Nom du bouton", id=f"{p}-qa-label")
            yield Select(self.kinds, value=self.kinds[0][1], allow_blank=False, id=f"{p}-qa-kind")
            yield Input(placeholder=self.hint, id=f"{p}-qa-value")
            with Horizontal(classes="btn-row"):
                yield Button("＋ Ajouter", id=f"{p}-qa-add", variant="primary")
                yield Button("＋ Depuis l'éditeur", id=f"{p}-qa-fromed")
                yield Button("🗑 Supprimer (par nom)", id=f"{p}-qa-del", variant="error")
        yield RichLog(id=f"{p}-qa-out", classes="qa-out", wrap=True, markup=False, highlight=False)

    async def on_mount(self) -> None:
        await self._rebuild()

    def write(self, text: str, color: str = "") -> None:
        self.query_one(f"#{self.prefix}-qa-out", RichLog).write(Text(text, style=color))

    async def _rebuild(self) -> None:
        box = self.query_one(f"#{self.prefix}-qa-custom", Grid)
        await box.remove_children()
        buttons = [ActionButton("⭐ " + c["label"], c["type"], c["value"]) for c in self.custom]
        if buttons:
            await box.mount(*buttons)

    def _disarm(self, btn: ActionButton) -> None:
        if btn.qa_armed:
            btn.qa_armed = False
            btn.label = btn.qa_title

    async def _add(self, label: str, kind: str, value: str) -> None:
        label, value = label.strip(), value.strip()
        if not label or not value:
            self.write("Donnez un nom et un contenu au bouton.", C_RED)
            return
        self.custom = [c for c in self.custom if c["label"].lower() != label.lower()]
        self.custom.append({"label": label, "type": kind, "value": value})
        qb_save(self.key, self.custom)
        await self._rebuild()
        self.write(f"✔ Bouton « {label} » enregistré.", C_GREEN)

    @on(Button.Pressed)
    async def _pressed(self, event: Button.Pressed) -> None:
        btn = event.button
        event.stop()
        if isinstance(btn, ActionButton):
            if btn.qa_confirm and not btn.qa_armed:        # action risquée : 2 clics
                btn.qa_armed = True
                btn.label = "⚠ Re-cliquez pour confirmer"
                self.set_timer(5, lambda: self._disarm(btn))
                return
            self._disarm(btn)
            self.post_message(self.Run(btn))
            return
        p, bid = self.prefix, btn.id or ""
        label = self.query_one(f"#{p}-qa-label", Input).value
        if bid == f"{p}-qa-add":
            kind = self.query_one(f"#{p}-qa-kind", Select).value
            await self._add(label, kind if isinstance(kind, str) else self.kinds[0][1],
                            self.query_one(f"#{p}-qa-value", Input).value)
        elif bid == f"{p}-qa-fromed":
            await self._add(label, self.editor_kind,
                            self.app.query_one(self.editor_id, TextArea).text)
        elif bid == f"{p}-qa-del":
            before = len(self.custom)
            self.custom = [c for c in self.custom if c["label"].lower() != label.strip().lower()]
            if len(self.custom) == before:
                self.write("Aucun bouton à ce nom (tapez-le dans « Nom du bouton »).", C_RED)
                return
            qb_save(self.key, self.custom)
            await self._rebuild()
            self.write("Bouton supprimé.", C_MUTED)

RELIABILITY_STYLE = {"fiable": "bold green", "satire": "bold red", "inconnu": "yellow", "inconnu (Tor)": "yellow"}
CREDIBILITY_STYLE = {"crédible": "bold green", "suspect": "bold red", "moyen": "yellow", "non pertinent": "dim"}
VERDICT_STYLE = {"crédible": "green", "suspect": "red", "mitigé": "yellow"}

# Verrou : une seule capture de sortie / patch d'input à la fois (redirect_stdout est global)
RUN_LOCK = threading.Lock()

def score_color(s: float) -> str:
    if s < 20: return C_GREEN
    if s < 40: return C_LIME
    if s < 55: return C_ORANGE
    if s < 70: return C_AMBER
    return C_RED

def bar_text(ratio: float, width: int = 20) -> Text:
    ratio = max(0.0, min(1.0, ratio))
    filled = round(ratio * width)
    color = score_color(ratio * 100)
    t = Text()
    t.append("█" * filled, style=color)
    t.append("░" * (width - filled), style="#2E3247")
    t.append(f" {ratio * 100:3.0f}%", style=color)
    return t

def short(text, size=70) -> str:
    text = (text or "").strip()
    return text if len(text) <= size else text[: size - 1] + "…"

def styled(value, mapping) -> str:
    style = mapping.get(value, "white")
    return f"[{style}]{escape(str(value))}[/{style}]"

# ═════════════════════════════════════════════════════════════════
#  Spécification des modules (pages génériques)
# ═════════════════════════════════════════════════════════════════
@dataclass
class FieldSpec:
    key: str
    label: str
    placeholder: str = ""
    required: bool = True

@dataclass
class ModuleSpec:
    key: str
    icon: str
    title: str
    desc: str
    module: str
    runner: Callable
    fields: list[FieldSpec] = field(default_factory=list)

def _simple(cls: str, method: str, *keys: str) -> Callable:
    def run(mod, v):
        obj = getattr(mod, cls)(*[v[k] for k in keys])
        getattr(obj, method)()
    return run

def _profileur(mod, v):
    p = mod.Profileur(nom=v["nom"], prenom=v["prenom"], age=v["age"] or None)
    term_console.print("[bold blue][*] Recherche en cours... Patientez...[/bold blue]")
    p.executer_recherche_complete()
    p.afficher_resultats()

def _func(name: str) -> Callable:
    """Pour les modules qui exposent une fonction de module (pas de classe), ex. save.py."""
    def run(mod, v):
        getattr(mod, name)()
    return run

def _dehash(mod, v):
    """dehash.py n'expose pas de classe : on relance son main() CLI avec les
    valeurs saisies dans l'interface, sans toucher au module lui-même."""
    import sys as _sys
    argv = ["dehash.py", v["target"]]
    if v.get("wordlist"):
        argv += ["-w", v["wordlist"]]
    else:
        argv += ["-b"]  # pas de dictionnaire fourni -> brute force par défaut
    old_argv = _sys.argv
    _sys.argv = argv
    try:
        mod.main()
    finally:
        _sys.argv = old_argv

def _sentiment(mod, v):
    """analyse_sentiment.py expose SentimentAnalyzer.analyze() + print_results(),
    pas de run_scan() : on relie les deux tel quel."""
    analyzer = mod.SentimentAnalyzer()
    result = analyzer.analyze(v["target"])
    mod.print_results(result, show_sentences=True)

def _accepts_arg(fn) -> bool:
    """True si fn peut recevoir un argument positionnel."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return True
    for p in sig.parameters.values():
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.VAR_POSITIONAL):
            return True
    return False

def _call_flex(fn, target: str):
    """Appelle fn en lui passant target uniquement si elle l'accepte et si target existe."""
    if target and _accepts_arg(fn):
        return fn(target)
    return fn()

def _auto(*candidates: str) -> Callable:
    """Runner générique pour un module dont on ne connaît pas l'API exacte.
    Cherche une fonction de module parmi `candidates`, sinon une classe définie
    dans le module exposant l'une de ces méthodes. `target` est transmis au
    constructeur ou à la méthode s'ils l'acceptent."""
    names = candidates or ("run_scan", "run", "scan", "start", "main", "executer", "lancer")

    def run(mod, v):
        target = (v.get("target") or "").strip()
        # 1) fonction au niveau module
        for name in names:
            fn = getattr(mod, name, None)
            if callable(fn) and not isinstance(fn, type):
                _call_flex(fn, target)
                return
        # 2) classe définie dans le module exposant une méthode candidate
        for attr in vars(mod).values():
            if isinstance(attr, type) and getattr(attr, "__module__", "") == mod.__name__:
                for name in names:
                    meth = getattr(attr, name, None)
                    if callable(meth):
                        obj = _call_flex(attr, target)          # instancie (avec target si accepté)
                        _call_flex(getattr(obj, name), target)  # exécute (avec target si accepté)
                        return
        raise RuntimeError(f"Aucun point d'entrée trouvé dans {mod.__name__} "
                           f"(essayé : {', '.join(names)}).")
    return run

TARGET = [FieldSpec("target", "Cible")]

MODULES: list[ModuleSpec] = [
    ModuleSpec("p_phone", "📱", "Téléphone", "Analyse OSINT d'un numéro de téléphone.", "W_O.phone",
               _simple("PhonyNode", "run_scan", "target"), [FieldSpec("target", "Numéro", "+33612345678")]),
    ModuleSpec("p_web", "🌐", "Web / IP", "Analyse d'infrastructure d'un domaine ou d'une IP.", "W_O.web",
               _simple("WebScanner", "scan_infra", "target"), [FieldSpec("target", "Domaine / IP", "example.com")]),
    ModuleSpec("p_mail", "📧", "Email", "Recherche OSINT sur une adresse email.", "W_O.mail",
               _simple("EmailOSINT", "run_scan", "target"), [FieldSpec("target", "Adresse email", "nom@domaine.com")]),
    ModuleSpec("p_pseudo", "👤", "Pseudo / Username", "Recherche d'un pseudo sur les réseaux.", "W_O.pseudo",
               _simple("UsernameOSINT", "run_scan", "target"), [FieldSpec("target", "Pseudo")]),
    ModuleSpec("p_scan", "📡", "Scan de ports", "Scan réseau d'une cible.", "W_S.scan",
               _simple("NetworkScanner", "run_scan", "target"), [FieldSpec("target", "IP / Hôte", "192.168.1.1")]),
    ModuleSpec("p_sniff", "🔍", "Sniffeur réseau", "Capture / analyse de trafic.", "W_S.sniffeur",
               _simple("NetworkSniffer", "run_scan", "target"), [FieldSpec("target", "Cible / interface")]),
    ModuleSpec("p_pass", "🔑", "Testeur de mot de passe", "Analyse de la robustesse d'un mot de passe "
               "(le module vous demandera la saisie en bas de page).", "W_O.password",
               _simple("PasswordAnalyzer", "run_scan")),
    ModuleSpec("p_info", "📋", "Devis système", "Informations matérielles de la machine.", "W_S.info",
               _simple("SystemDevis", "run_scan")),
    ModuleSpec("p_profil", "🕵️", "Profilage (Nom/Prénom)", "Recherche de profil à partir d'une identité.", "W_O.profileur",
               _profileur, [FieldSpec("nom", "NOM"), FieldSpec("prenom", "PRÉNOM"),
                            FieldSpec("age", "ÂGE (optionnel)", required=False)]),
    # ⚠ danger.py vit dans W_A (et non W_O) : chemin corrigé selon l'arborescence
    ModuleSpec("p_url", "🛡️", "Vérifier une URL", "Analyse de dangerosité (VirusTotal).", "W_A.danger",
               _simple("URLAnalyzer", "run_scan", "target"), [FieldSpec("target", "URL", "https://…")]),
    ModuleSpec("p_meta", "📂", "Métadonnées", "Extraction de métadonnées (image / document).", "W_S.meta",
               _simple("MetadataExtractor", "run_scan", "target"), [FieldSpec("target", "Chemin du fichier")]),
    ModuleSpec("p_plaque", "🚗", "Véhicule (plaque / VIN)", "Recherche d'informations véhicule "
               "(base locale, API NHTSA, décodage VIN).", "W_O.plaque",
               _simple("PlaqueOSINT", "run_scan"), []),
    ModuleSpec("p_dehash", "🔓", "Déhashage", "Cassage d'un hash par dictionnaire (si wordlist fournie) "
               "ou brute force.", "W_S.dehash", _dehash,
               [FieldSpec("target", "Hash à déchiffrer"),
                FieldSpec("wordlist", "Wordlist (optionnel, sinon brute-force)", required=False)]),
    ModuleSpec("p_recover", "🗄️", "Récupération de fichiers supprimés", "Analyse bas niveau d'un disque/image "
               "pour retrouver des fichiers supprimés (nécessite pytsk3).", "W_S.save",
               _func("recover_deleted_files"), []),
    # ── W_H : attaques / exploitation ────────────────────────────
    ModuleSpec("p_brute", "🔨", "Brute force", "Attaque par force brute d'un service "
               "(SSH, FTP, HTTP…).", "W_H.brute_force", _auto(),
               [FieldSpec("target", "Hôte / IP", "192.168.1.1")]),
    ModuleSpec("p_ddos", "💥", "DDoS / Charge", "Test de déni de service et montée en charge.",
               "W_H.ddos", _auto(), [FieldSpec("target", "URL cible", "https://example.com")]),
    ModuleSpec("p_sqlmap", "🗃️", "SQLMap", "Détection / exploitation d'injections SQL.",
               "W_H.sqlmap", _auto(), [FieldSpec("target", "URL paramétrée", "https://…/page.php?id=1")]),
    ModuleSpec("p_bluetooth", "🔵", "Bluetooth", "Scan des appareils Bluetooth à proximité.",
               "W_O.bluetooth", _auto(), [FieldSpec("target", "Cible (optionnel)", required=False)]),

    # ── Modules supplémentaires : intégration complète de l'arborescence ──
    ModuleSpec("p_image", "🖼️", "Analyse d'image", "Détection IA / nettoyage de métadonnées sur une image.",
               "W_I.image", _auto(), [FieldSpec("target", "Chemin de l'image")]),
    # « Vérification Tor » : rattachée à la section Vérification (voir GROUP_TITLES)
    ModuleSpec("p_torbrowser", "🧅", "Vérification Tor", "Lancement / pilotage du Tor Browser.",
               "tor-browser", _auto(), [FieldSpec("target", "Cible (optionnel)", required=False)]),
    ModuleSpec("p_corescan", "🧩", "Scanner core", "Scanner réseau du paquet core.",
               "core.scanner", _auto(), [FieldSpec("target", "IP / Hôte", "192.168.1.1")]),
]

# ── Module natif texte IA ayant un fonctionnement "générique" (page W_I) ────
SENTIMENT_SPEC = ModuleSpec(
    "p_sentiment", "🎭", "Analyse de sentiment",
    "Sentiment, émotions, sarcasme et sous-entendus détectés dans un texte.",
    "W_A.analyse_sentiment", _sentiment, [FieldSpec("target", "Texte à analyser")],
)
MODULES.append(SENTIMENT_SPEC)

# ═════════════════════════════════════════════════════════════════
#  Regroupement du menu : (titre de section, couleur, préfixes de modules)
#  Plusieurs préfixes peuvent partager une section : « tor-browser » est ainsi
#  rattaché à la section Vérification, avec W_J.
# ═════════════════════════════════════════════════════════════════
GROUP_TITLES: list[tuple[str, str, list[str]]] = [
    ("W_A · Analyse",            "#FF6B6B", ["W_A."]),
    ("W_I · Texte & Image IA",   "#A8E063", ["W_I."]),
    ("W_J · Vérification & Tor", "#4FC3F7", ["W_J.", "tor-browser"]),
    ("W_F · Flipper & ESP32",    "#FF8C42", ["W_F."]),
    ("W_H · Attaques réseau",    "#FF4FA3", ["W_H."]),
    ("W_O · OSINT",              "#B388FF", ["W_O."]),
    ("W_S · Système & Réseau",   "#2ECC71", ["W_S."]),
    ("core · Moteur",            "#F39C12", ["core."]),
]

def section_color(module: str) -> str:
    """Couleur de titre associée à la section d'un module."""
    for _title, color, prefixes in GROUP_TITLES:
        if any(module.startswith(p) for p in prefixes):
            return color
    return C_MUTED

# Pages « natives » rattachées à leur section (affichées avant les modules génériques)
NATIVE_PAGES = {
    "W_I.": [("🧠  Détecteur / Humaniser / Reformater", "p_detect")],
    "W_J.": [("📰  Vérificateur d'informations", "p_verif")],
    "W_F.": [("🐬  Flipper Studio (JS / CLI)", "p_flipper"),
             ("📶  ESP32 Studio (C/C++ / Flash)", "p_esp32")],
}

# ═════════════════════════════════════════════════════════════════
#  Page générique pour les modules W_O / W_S / W_H
# ═════════════════════════════════════════════════════════════════
class ModulePage(Vertical):
    """Page d'un module : saisie des paramètres, puis exécution dans le vrai terminal
    (l'interface Textual est suspendue le temps du module, comme dans l'ancien menu CLI)."""

    def __init__(self, spec: ModuleSpec) -> None:
        super().__init__(id=spec.key)
        self.spec = spec

    def compose(self) -> ComposeResult:
        s = self.spec
        yield Label(Text(f"{s.icon}  {s.title}", style=f"bold {section_color(s.module)}"),
                    classes="page-title")
        yield Static(s.desc, classes="page-desc")
        for f in s.fields:
            yield Label(f.label, classes="field-label")
            yield Input(placeholder=f.placeholder, id=f"f-{f.key}")
        with Horizontal(classes="btn-row"):
            yield Button("▶ Lancer", id="run", variant="success")
        yield Static("Les résultats s'affichent dans le terminal ; Entrée pour revenir ici.",
                     classes="page-desc")
        yield Static("", id="last")

    @on(Button.Pressed, "#run")
    def _on_run(self) -> None:
        self.start()

    @on(Input.Submitted)
    def _on_submit(self) -> None:
        self.start()

    def start(self) -> None:
        values: dict[str, str] = {}
        for f in self.spec.fields:
            val = self.query_one(f"#f-{f.key}", Input).value.strip()
            if f.required and not val:
                self.app.notify(f"Champ requis : {f.label}", severity="warning")
                return
            values[f.key] = val

        status = "✔ terminé"
        with self.app.suspend():  # rend le vrai terminal au module
            term_console.clear()
            term_console.print(Rule(f"{self.spec.icon}  {self.spec.title}",
                                    style=section_color(self.spec.module)))
            try:
                mod = importlib.import_module(self.spec.module)
                self.spec.runner(mod, values)
            except SystemExit:
                status = "⚠ arrêt demandé par le module"
            except KeyboardInterrupt:
                term_console.print("\n[bold red]Interrompu.[/bold red]")
                status = "⚠ interrompu"
            except Exception:  # noqa: BLE001
                term_console.print_exception()
                status = "✘ erreur (voir le terminal)"
            try:
                input("\nAppuyez sur Entrée pour revenir à Watch Fox…")
            except (EOFError, KeyboardInterrupt):
                pass
        self.query_one("#last", Static).update(
            Text(f"Dernière exécution {datetime.now():%H:%M:%S} : {status}",
                 style=C_GREEN if status.startswith("✔") else C_ORANGE))

# ═════════════════════════════════════════════════════════════════
#  Page native W_I : détecteur IA / humanisation / reformatage
# ═════════════════════════════════════════════════════════════════
class Gauge(Static):
    def on_mount(self) -> None:
        self.reset()

    def show(self, score: float, verdict: str) -> None:
        color = score_color(score)
        t = Text(justify="center")
        t.append(f"{score:.0f}", style=f"bold {color}")
        t.append(" /100\n", style=C_MUTED)
        t.append(bar_text(score / 100, 40))
        t.append(f"\n{verdict}", style=f"bold {color}")
        self.update(t)

    def reset(self) -> None:
        t = Text(justify="center")
        t.append("—", style=f"bold {C_MUTED}")
        t.append(" /100\n", style=C_MUTED)
        t.append(bar_text(0, 40))
        t.append("\nEn attente…", style=C_MUTED)
        self.update(t)

class Card(Static):
    def __init__(self, label: str, **kw) -> None:
        super().__init__(**kw)
        self._label = label
        self.set("—")

    def set(self, value: str, color: str = "white") -> None:
        t = Text(justify="center")
        t.append(f"{self._label}\n", style=C_MUTED)
        t.append(value, style=f"bold {color}")
        self.update(t)

class DetectorPage(Horizontal):
    def __init__(self) -> None:
        super().__init__(id="p_detect")
        self._source_file: Path | None = None
        self._last_result = None
        self._busy = False
        if AI_ERROR is None:
            self._cleaner = MetadataCleaner()
            self._reformatter = TextReformatter()

    def compose(self) -> ComposeResult:
        if AI_ERROR is not None:
            yield Static(Text(f"Module W_I indisponible : {AI_ERROR}", style=C_RED))
            return
        with Vertical(id="ad-left"):
            yield Label("TEXTE À ANALYSER", classes="section")
            yield TextArea(id="ad-editor", soft_wrap=True)
            with Horizontal(id="ad-file-row"):
                yield Input(placeholder="Chemin (.txt .md .pdf .docx)", id="ad-file-input")
                yield Button("Ouvrir", id="ad-file-btn")
            yield Button("Analyser  [F5]", id="ad-analyze", variant="primary")
            yield Label("HUMANISATION", classes="section")
            yield Select([(m, m) for m in HUMANIZE_MODES], value="subtil", allow_blank=False, id="ad-mode")
            yield Button("Humaniser  [F6]", id="ad-humanize")
            yield Label("REFORMATAGE", classes="section")
            first = "pave" if "pave" in STYLE_LABELS else next(iter(STYLE_LABELS), None)
            yield Select([(lbl, key) for key, lbl in STYLE_LABELS.items()], value=first,
                         allow_blank=False, id="ad-style")
            yield Button("Reformater  [F7]", id="ad-refile")
            yield ProgressBar(id="ad-progress", show_eta=False, show_percentage=False)
            yield Static("", id="ad-status")
        with VerticalScroll(id="ad-right"):
            yield Gauge(id="ad-gauge")
            with Horizontal(id="ad-cards"):
                yield Card("VERDICT", id="ad-c-verdict")
                yield Card("TOKENS", id="ad-c-tokens")
                yield Card("CONFIANCE", id="ad-c-conf")
            with Vertical(id="ad-dims"):
                yield Label("DÉTAIL PAR DIMENSION", classes="section")
                for i, name in enumerate(DIMENSIONS):
                    with Horizontal(classes="dim-row"):
                        yield Label(name, classes="dim-name")
                        yield Static(bar_text(0), id=f"ad-dim-{i}")
            yield Static("", id="ad-warnings")
            yield Label("EXPORT JSON", classes="section")
            yield Input(value="analyse_ai.json", id="ad-export-input")

    # helpers
    @property
    def _editor(self) -> TextArea:
        return self.query_one("#ad-editor", TextArea)

    def _status(self, msg: str, color: str = C_MUTED) -> None:
        self.query_one("#ad-status", Static).update(Text(msg, style=color))

    def _set_busy(self, busy: bool, label: str = "") -> None:
        self._busy = busy
        for b in self.query(Button):
            b.disabled = busy
        bar = self.query_one("#ad-progress", ProgressBar)
        bar.set_class(busy, "busy")
        if busy:
            bar.update(total=None)
            self._status(label)

    def _get_text(self, what: str) -> str | None:
        text = self._editor.text.strip()
        if not text:
            self._status(f"Aucun texte à {what}.", C_RED)
            return None
        return text

    # actions
    @on(Button.Pressed, "#ad-analyze")
    def action_analyze(self) -> None:
        if self._busy or AI_ERROR:
            return
        text = self._get_text("analyser")
        if text is None:
            return
        self.query_one("#ad-gauge", Gauge).reset()
        self.query_one("#ad-warnings").remove_class("show")
        self._set_busy(True, "Analyse en cours…")
        self._run_analysis(text)

    @on(Button.Pressed, "#ad-humanize")
    def action_humanize(self) -> None:
        if self._busy or AI_ERROR:
            return
        text = self._get_text("humaniser")
        if text is None:
            return
        self._set_busy(True, "Humanisation en cours…")
        self._run_humanize(text, str(self.query_one("#ad-mode", Select).value))

    @on(Button.Pressed, "#ad-refile")
    def action_refile(self) -> None:
        if self._busy or AI_ERROR:
            return
        text = self._get_text("reformater")
        if text is None:
            return
        self._set_busy(True, "Reformatage en cours…")
        self._run_refile(text, str(self.query_one("#ad-style", Select).value))

    def action_reset(self) -> None:
        if AI_ERROR:
            return
        self._editor.clear()
        self.query_one("#ad-file-input", Input).value = ""
        self.query_one("#ad-gauge", Gauge).reset()
        for cid in ("#ad-c-verdict", "#ad-c-tokens", "#ad-c-conf"):
            self.query_one(cid, Card).set("—")
        for i in range(len(DIMENSIONS)):
            self.query_one(f"#ad-dim-{i}", Static).update(bar_text(0))
        self.query_one("#ad-warnings").remove_class("show")
        self._status("")
        self._last_result = None
        self._source_file = None
        self._set_busy(False)
        self._editor.focus()

    # fichiers
    @on(Button.Pressed, "#ad-file-btn")
    @on(Input.Submitted, "#ad-file-input")
    def _open_file(self) -> None:
        raw = self.query_one("#ad-file-input", Input).value.strip().strip('"').strip("'")
        if not raw:
            self._status("Indiquez un chemin de fichier.", C_RED)
            return
        path = Path(raw).expanduser()
        if not path.is_file():
            self._status(f"Fichier introuvable : {path}", C_RED)
            return
        if path.suffix.lower() not in SUPPORTED_EXT:
            self._status(f"Format non supporté : {path.suffix}", C_RED)
            return
        self._set_busy(True, f"Lecture de {path.name}…")
        self._load_file(path)

    @work(thread=True, exclusive=True, group="ad-io")
    def _load_file(self, path: Path) -> None:
        try:
            from W_I.detecteur import _read_txt, _read_pdf, _read_docx
            readers = {".txt": _read_txt, ".md": _read_txt, ".pdf": _read_pdf, ".docx": _read_docx}
            content = readers[path.suffix.lower()](path)
            self.app.call_from_thread(self._file_loaded, path, content)
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(self._fail, f"Erreur de lecture : {exc}")

    def _file_loaded(self, path: Path, content: str) -> None:
        self._set_busy(False)
        if not content.strip():
            self._status("Fichier vide ou illisible (dépendance manquante ?).", C_RED)
            return
        self._source_file = path
        self._editor.load_text(content)
        self._status(f"📄 {path.name} chargé ({len(content)} caractères).", C_GREEN)

    # workers
    def _fail(self, msg: str) -> None:
        self._set_busy(False)
        self._status(msg, C_RED)

    @work(thread=True, exclusive=True, group="ad-task")
    def _run_analysis(self, text: str) -> None:
        try:
            self.app.call_from_thread(self._show_result, analyze_text(text))
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(self._fail, f"Erreur : {exc}")

    @work(thread=True, exclusive=True, group="ad-task")
    def _run_humanize(self, text: str, mode: str) -> None:
        try:
            humanized = self._cleaner._human_targeted(text, mode)
            saved: Path | None = None
            if self._source_file:
                saved = self._source_file.with_stem(self._source_file.stem + "_humanisé").with_suffix(".txt")
                saved.write_text(humanized, encoding="utf-8")
            self.app.call_from_thread(
                self._apply_text, humanized,
                f"✔ Fichier sauvegardé : {saved.name}" if saved else "✔ Texte humanisé.")
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(self._fail, f"Erreur humanisation : {exc}")

    @work(thread=True, exclusive=True, group="ad-task")
    def _run_refile(self, text: str, style: str) -> None:
        try:
            out = self._reformatter.reformat(text, style)
            self.app.call_from_thread(self._apply_text, out, "✔ Texte reformaté.")
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(self._fail, f"Erreur de reformatage : {exc}")

    def _apply_text(self, text: str, msg: str) -> None:
        self._set_busy(False)
        self._editor.load_text(text)
        self._status(msg, C_GREEN)

    def _show_result(self, r) -> None:
        self._last_result = r
        self._set_busy(False)
        color = score_color(r.score)
        self.query_one("#ad-gauge", Gauge).show(r.score, r.verdict)
        self.query_one("#ad-c-verdict", Card).set(r.verdict, color)
        self.query_one("#ad-c-tokens", Card).set(str(r.token_count))
        conf_color = {"faible": C_RED, "modérée": C_ORANGE, "élevée": C_GREEN}.get(r.confidence, "white")
        self.query_one("#ad-c-conf", Card).set(r.confidence.capitalize(), conf_color)
        for dim in r.dimensions:
            if dim.name in DIMENSIONS:
                self.query_one(f"#ad-dim-{DIMENSIONS.index(dim.name)}", Static).update(bar_text(dim.score))
        warn = self.query_one("#ad-warnings", Static)
        if r.warnings:
            warn.update("⚠  " + "\n⚠  ".join(r.warnings))
            warn.add_class("show")
        else:
            warn.remove_class("show")
        self._status("✔ Analyse terminée.  (F8 pour exporter en JSON)", C_GREEN)

    def action_export(self) -> None:
        if AI_ERROR:
            return
        if self._last_result is None:
            self._status("Aucune analyse à exporter.", C_RED)
            return
        raw = self.query_one("#ad-export-input", Input).value.strip() or "analyse_ai.json"
        path = Path(raw).expanduser()
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self._last_result.to_dict(), fh, ensure_ascii=False, indent=2)
            self._status(f"✔ Exporté : {path}", C_GREEN)
        except Exception as exc:  # noqa: BLE001
            self._status(f"Erreur d'export : {exc}", C_RED)

    @on(Input.Submitted, "#ad-export-input")
    def _export_on_enter(self) -> None:
        self.action_export()

# ═════════════════════════════════════════════════════════════════
#  Page native W_J : vérificateur d'informations (recherche / Tor)
# ═════════════════════════════════════════════════════════════════
class VerifPage(Horizontal):
    def __init__(self) -> None:
        super().__init__(id="p_verif")
        self.engine = None
        self._last: tuple | None = None
        if VERIF_ERROR is None:
            try:
                self.engine = TorSearchEngine()
            except Exception as exc:  # noqa: BLE001
                self._engine_error = exc

    def compose(self) -> ComposeResult:
        if VERIF_ERROR is not None or self.engine is None:
            err = VERIF_ERROR or getattr(self, "_engine_error", "moteur indisponible")
            yield Static(Text(f"Module W_S indisponible : {err}", style=C_RED))
            return
        with VerticalScroll(id="v-left"):
            yield Label("PHRASE / IDÉE À VÉRIFIER", classes="section")
            yield Input(placeholder="Que voulez-vous vérifier ?", id="v-query")
            yield Label("NOMBRE DE RÉSULTATS (1-50)", classes="section")
            yield Input(value="10", id="v-num", type="integer")
            with Horizontal(classes="sw-row"):
                yield Switch(id="v-tor")
                yield Label(" Passer par Tor")
            with Horizontal(classes="sw-row"):
                yield Switch(value=True, id="v-starttor")
                yield Label(" Démarrer Tor si absent")
            with Horizontal(classes="sw-row"):
                yield Switch(value=True, id="v-analyze")
                yield Label(" Analyser les pages")
            yield Label("PAGES À ANALYSER (1-10)", classes="section")
            yield Input(value="5", id="v-pages", type="integer")
            yield Button("🔎 Lancer la vérification", id="v-go", variant="primary")
            yield Button("💾 Sauvegarder (JSON)", id="v-save")
            with Horizontal(classes="btn-row"):
                yield Button("Statut Tor", id="v-status")
                yield Button("Démarrer Tor", id="v-start")
            yield Label("HISTORIQUE", classes="section")
            yield Select([], prompt="Recherches sauvegardées…", id="v-hist")
            yield Button("↻ Rafraîchir l'historique", id="v-refresh")
            yield Static("", id="v-state")
        yield RichLog(id="v-out", wrap=True, markup=True, highlight=False)

    def on_mount(self) -> None:
        if self.engine is not None:
            self._refresh_history()

    def _state(self, msg: str, color: str = C_MUTED) -> None:
        self.query_one("#v-state", Static).update(Text(msg, style=color))

    @property
    def _log(self) -> RichLog:
        return self.query_one("#v-out", RichLog)

    def _busy(self, busy: bool) -> None:
        for b in self.query(Button):
            b.disabled = busy

    # ── Recherche ────────────────────────────────────────────────
    @on(Button.Pressed, "#v-go")
    @on(Input.Submitted, "#v-query")
    def _go(self) -> None:
        query = self.query_one("#v-query", Input).value.strip()
        if not query:
            self._state("Entrez une phrase à rechercher.", C_RED)
            return

        def num(wid: str, lo: int, hi: int, default: int) -> int:
            try:
                return max(lo, min(int(self.query_one(wid, Input).value), hi))
            except ValueError:
                return default

        use_tor = self.query_one("#v-tor", Switch).value
        params = {
            "query": query,
            "tor": use_tor,
            "start_tor": use_tor and self.query_one("#v-starttor", Switch).value and STEM_AVAILABLE,
            "results": num("#v-num", 1, 50, 10),
            "analyze": self.query_one("#v-analyze", Switch).value,
            "max_pages": num("#v-pages", 1, 10, 5),
        }
        self._busy(True)
        self._log.clear()
        self._state("Recherche en cours…", C_ORANGE)
        self._search(params)

    @work(thread=True, exclusive=True, group="verif")
    def _search(self, p: dict) -> None:
        eng, call = self.engine, self.app.call_from_thread
        buf = io.StringIO()
        results, exact, partial = [], [], []
        try:
            with RUN_LOCK, redirect_stdout(buf):
                if p["start_tor"] and not eng.is_tor_running():
                    call(self._state, "Démarrage de Tor (peut prendre une minute)…", C_ORANGE)
                    if not eng.start_tor(msg_handler=lambda line: None):
                        call(self._log.write, "[yellow]Tor n'a pas pu démarrer : retour au web normal.[/yellow]")
                        p["tor"] = False
                if p["tor"]:
                    eng.configure_tor_proxies()
                    call(self._state, "Recherche via Tor… (peut être long)", C_ORANGE)
                    results = eng.search_on_tor(p["query"], p["results"])
                else:
                    call(self._state, "Recherche sur le web…", C_ORANGE)
                    results = eng.search_on_surface_web(p["query"], p["results"])

                if p["analyze"] and results:
                    def progress(i, total, url):
                        call(self._state, f"Analyse page {i + 1}/{total} · {short(url, 40)}", C_ORANGE)

                    exact, partial = eng.search_content_in_pages(
                        p["query"], results, max_pages=p["max_pages"], progress=progress)
            errors = [l for l in buf.getvalue().splitlines() if "Erreur" in l]
            call(self._finish, p, results, exact, partial, errors)
        except Exception as exc:  # noqa: BLE001
            call(self._fail, f"Erreur : {exc}")

    def _fail(self, msg: str) -> None:
        self._busy(False)
        self._state(msg, C_RED)

    def _finish(self, p, results, exact, partial, errors) -> None:
        self._busy(False)
        self._last = (p, results, exact, partial)
        if errors:
            self._log.write(f"[yellow]{len(errors)} avertissement(s) :[/yellow]")
            for l in errors[:5]:
                self._log.write(f"  [dim]{escape(short(l, 110))}[/dim]")
        self.render_results(p["query"], results, exact, partial)
        self._state("✔ Recherche terminée.", C_GREEN)

    # ── Affichage des résultats ──────────────────────────────────
    def render_results(self, query, results, exact, partial, timestamp=None) -> None:
        w = self._log.write
        w(Rule(f"[bold cyan]Résultats pour « {escape(query)} »"))
        if timestamp:
            w(f"[dim]Recherche du {timestamp}[/dim]")
        if not results:
            w(Panel("Aucun résultat trouvé.", border_style="red"))
            return

        table = Table(box=box.ROUNDED, show_lines=True, header_style="bold", expand=True)
        table.add_column("#", justify="right", width=3)
        table.add_column("Titre / URL", ratio=3)
        table.add_column("Source", justify="center", ratio=1)
        table.add_column("Extrait", ratio=3)
        for i, r in enumerate(results, 1):
            table.add_row(
                str(i),
                f"[bold]{escape(short(r['title'], 80))}[/bold]\n[blue]{escape(short(r['url'], 80))}[/blue]",
                styled(r.get("source_reliability", "inconnu"), RELIABILITY_STYLE),
                escape(short(r.get("snippet", ""), 160)) or "[dim]—[/dim]",
            )
        w(table)

        counts: dict = {}
        for r in results:
            k = r.get("source_reliability", "inconnu")
            counts[k] = counts.get(k, 0) + 1
        w("Sources : " + "  ".join(f"{styled(k, RELIABILITY_STYLE)} × {v}" for k, v in counts.items()))

        if not (exact or partial):
            w("\n[dim]Analyse du contenu non effectuée : activez « Analyser les pages » pour un verdict.[/dim]")
            return

        w(Rule("[bold cyan]Analyse détaillée du contenu"))
        if exact:
            w(f"\n[bold]Correspondances exactes ({len(exact)})[/bold]")
            for i, m in enumerate(exact, 1):
                body = (
                    f"[bold]{escape(m['title'])}[/bold]\n[blue]{escape(m['url'])}[/blue]\n\n"
                    f"Auteur       : {escape(str(m['author']))}\n"
                    f"Source       : {styled(m['source_reliability'], RELIABILITY_STYLE)}\n"
                    f"Crédibilité  : {styled(m['credibility'], CREDIBILITY_STYLE)}\n\n"
                    f"[italic]« …{escape(m['context'])}… »[/italic]"
                )
                w(Panel(body, title=f"#{i}", border_style="green"))
        else:
            w("\n[yellow]Aucune correspondance exacte trouvée.[/yellow]")

        if partial:
            w(f"\n[bold]Correspondances partielles ({len(partial)})[/bold]")
            pt = Table(box=box.SIMPLE_HEAVY, header_style="bold", expand=True)
            pt.add_column("#", justify="right", width=3)
            pt.add_column("Titre / URL", ratio=3)
            pt.add_column("Auteur", ratio=1)
            pt.add_column("Source", justify="center")
            pt.add_column("Crédibilité", justify="center")
            for i, m in enumerate(partial, 1):
                pt.add_row(
                    str(i),
                    f"{escape(short(m['title'], 60))}\n[blue]{escape(short(m['url'], 60))}[/blue]",
                    escape(str(m["author"])),
                    styled(m["source_reliability"], RELIABILITY_STYLE),
                    styled(m["credibility"], CREDIBILITY_STYLE),
                )
            w(pt)

        summary = TorSearchEngine.summarize_credibility(exact)
        messages = {
            "crédible": "L'information semble globalement crédible.",
            "suspect": "L'information semble suspecte, vérifiez avec d'autres sources.",
            "mitigé": "Les sources sont mitigées, approfondissez votre recherche.",
        }
        color = VERDICT_STYLE[summary["verdict"]]
        w(Panel(
            f"Sources crédibles : [green]{summary['credible']}[/green]\n"
            f"Sources suspectes : [red]{summary['suspect']}[/red]\n\n"
            f"[bold {color}]CONCLUSION : {messages[summary['verdict']]}[/bold {color}]\n\n"
            "[dim]Indicateur automatique (mots-clés + liste de sources) : "
            "il ne remplace pas votre jugement.[/dim]",
            title="Résumé de la crédibilité", border_style=color))

    # ── Tor ──────────────────────────────────────────────────────
    @on(Button.Pressed, "#v-status")
    def _tor_status(self) -> None:
        self._busy(True)
        self._state("Test de Tor…", C_ORANGE)
        self._tor_worker(False)

    @on(Button.Pressed, "#v-start")
    def _tor_start(self) -> None:
        if not STEM_AVAILABLE:
            self._state("Module 'stem' non installé (pip install stem).", C_RED)
            return
        self._busy(True)
        self._state("Démarrage de Tor…", C_ORANGE)
        self._tor_worker(True)

    @work(thread=True, exclusive=True, group="verif")
    def _tor_worker(self, start: bool) -> None:
        eng, call, w = self.engine, self.app.call_from_thread, self._log.write
        try:
            call(w, Rule("[bold cyan]Statut Tor"))
            call(w, f"Module stem installé : {'[green]oui[/green]' if STEM_AVAILABLE else '[red]non[/red]'}")
            if start and not eng.is_tor_running():
                buf = io.StringIO()
                with RUN_LOCK, redirect_stdout(buf):
                    ok = eng.start_tor(msg_handler=lambda line: None)
                call(w, "[green]Tor démarré.[/green]" if ok else
                     "[red]Impossible de démarrer Tor.[/red] [dim]Installez-le (apt/brew install tor).[/dim]")
            running = eng.is_tor_running()
            call(w, f"Tor actif sur le port {eng.socks_port} : "
                    f"{'[green]oui[/green]' if running else '[red]non[/red]'}")
            if running:
                ip = eng.check_tor_connection()
                call(w, f"Connexion Tor fonctionnelle · IP de sortie : [bold]{escape(ip)}[/bold]" if ip else
                     "[yellow]Le port répond mais le trafic ne passe pas par Tor.[/yellow]")
        except Exception as exc:  # noqa: BLE001
            call(w, f"[red]Erreur : {escape(str(exc))}[/red]")
        finally:
            call(self._busy, False)
            call(self._state, "")

    # ── Sauvegarde / historique ──────────────────────────────────
    @on(Button.Pressed, "#v-save")
    def _save(self) -> None:
        if not self._last or not self._last[1]:
            self._state("Rien à sauvegarder.", C_RED)
            return
        p, results, exact, partial = self._last
        filename = f"recherche_{datetime.now():%Y%m%d_%H%M%S}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump({"query": p["query"], "timestamp": datetime.now().isoformat(),
                       "search_results": results, "exact_matches": exact, "partial_matches": partial},
                      f, ensure_ascii=False, indent=2)
        self._state(f"✔ Sauvegardé : {filename}", C_GREEN)
        self._refresh_history()

    @on(Button.Pressed, "#v-refresh")
    def _refresh_history(self) -> None:
        files = sorted(glob.glob("recherche_*.json"), reverse=True)
        opts = []
        for path in files:
            try:
                with open(path, encoding="utf-8") as f:
                    d = json.load(f)
                label = f"{d.get('timestamp', '')[:16].replace('T', ' ')} · {short(d.get('query', '?'), 28)}"
                opts.append((label, path))
            except (OSError, json.JSONDecodeError):
                continue
        self.query_one("#v-hist", Select).set_options(opts)

    @on(Select.Changed, "#v-hist")
    def _show_history(self, event: Select.Changed) -> None:
        if not isinstance(event.value, str):
            return
        try:
            with open(event.value, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            self._state("Fichier illisible.", C_RED)
            return
        self._log.clear()
        self.render_results(d.get("query", "?"), d.get("search_results", []),
                            d.get("exact_matches", []), d.get("partial_matches", []),
                            timestamp=d.get("timestamp", "")[:19].replace("T", " "))

# ═════════════════════════════════════════════════════════════════
#  Page native W_F : Flipper Zero (studio JS + console CLI)
# ═════════════════════════════════════════════════════════════════
class ExtTree(DirectoryTree):
    """Arbre de fichiers limité aux dossiers et à certaines extensions."""
    exts: tuple = (".js",)

    def filter_paths(self, paths):
        return [p for p in paths
                if not p.name.startswith(".") and (p.is_dir() or p.suffix.lower() in self.exts)]

class FilePicker(ModalScreen[str | None]):
    """Sélecteur de fichier (W_F : scripts .js, code C/C++, firmwares .bin)."""
    BINDINGS = [Binding("escape", "dismiss(None)", "Annuler")]
    DEFAULT_CSS = """
    FilePicker { align: center middle; }
    FilePicker > Vertical { width: 70%; height: 80%; border: heavy #FF8C42;
                            background: #1A1D27; padding: 1; }
    FilePicker Label { color: #7A788A; text-style: bold; }
    FilePicker DirectoryTree { height: 1fr; background: #14161F; margin-top: 1; }
    """

    def __init__(self, exts: tuple = (".js",), label: str = "CHOISIR UN SCRIPT .js") -> None:
        super().__init__()
        self.exts, self.label = exts, label

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"{self.label}  (Échap pour annuler)")
            tree = ExtTree(str(Path.cwd()))
            tree.exts = self.exts
            yield tree

    @on(DirectoryTree.FileSelected)
    def _picked(self, event: DirectoryTree.FileSelected) -> None:
        self.dismiss(str(event.path))

def _flipper_editor() -> TextArea:
    try:
        return TextArea.code_editor(FLIPPER_TEMPLATE, language="javascript", id="fz-editor")
    except Exception:  # noqa: BLE001  (tree-sitter absent : pas de coloration)
        return TextArea.code_editor(FLIPPER_TEMPLATE, id="fz-editor")

class FlipperPage(Horizontal):
    """Pilotage d'un Flipper Zero en USB : édition / envoi / exécution de scripts JS
    et console CLI libre. Toutes les E/S série passent par un thread + un verrou."""

    def __init__(self) -> None:
        super().__init__(id="p_flipper")
        self.flipper = None
        self.lock = threading.Lock()
        self.stop_flag = threading.Event()
        self._busy = False

    def compose(self) -> ComposeResult:
        if FLIPPER_ERROR is not None:
            yield Static(Text(f"Module W_F indisponible : {FLIPPER_ERROR}  "
                              "(pip install pyserial)", style=C_RED))
            return
        with VerticalScroll(id="fz-left"):
            yield Label("CONNEXION", classes="section")
            yield Select([], prompt="Port série", id="fz-port", allow_blank=True)
            with Horizontal(classes="btn-row"):
                yield Button("↻ Ports", id="fz-refresh")
                yield Button("Connecter", id="fz-connect", variant="primary")
            yield Static("", id="fz-state")
            yield Label("FICHIER LOCAL", classes="section")
            yield Input(placeholder="Chemin local .js", id="fz-local")
            with Horizontal(classes="btn-row"):
                yield Button("Ouvrir", id="fz-open")
                yield Button("Parcourir", id="fz-browse")
                yield Button("Sauver", id="fz-save")
            yield Label("SUR LE FLIPPER", classes="section")
            yield Input(value="python_script.js", placeholder="Nom sur le Flipper", id="fz-remote")
            yield Button("Envoyer  [F3]", id="fz-send")
            yield Button("Envoyer + Exécuter ▶  [F4]", id="fz-run", variant="success")
            yield Button("■ Stop  [F12]", id="fz-stop", variant="error")
            yield Label("OUTILS RAPIDES", classes="section")
            with Horizontal(classes="btn-row"):
                yield Button("Infos", id="fz-info")
                yield Button("Lister /ext", id="fz-ls")
            yield Static("", id="fz-status")
        with TabbedContent(id="fz-tabs"):
            with TabPane("Éditeur JS", id="fz-tab-js"):
                yield _flipper_editor()
                yield RichLog(id="fz-console", wrap=True, markup=False, highlight=False)
            with TabPane("Console CLI", id="fz-tab-cli"):
                yield RichLog(id="fz-cli-out", wrap=True, markup=False, highlight=False)
                yield Input(placeholder="Commande CLI (ex : device_info, storage list /ext)",
                            id="fz-cli-in")
            with TabPane("⚡ Boutons", id="fz-tab-btn"):
                yield QuickPanel("fz", "flipper", FLIPPER_QA,
                                 [("Commandes CLI", "cli"), ("Script JS", "js")],
                                 "#fz-editor", "js", "cmd1; sleep 1; cmd2  (ou code JS)")

    def on_mount(self) -> None:
        if FLIPPER_ERROR is not None:
            return
        self._set_conn(False)
        self._refresh_ports()
        self._say("Prêt. Branchez le Flipper en USB puis cliquez sur Connecter.")

    # ── utilitaires ──────────────────────────────────────────────
    @property
    def _js_log(self) -> RichLog:
        return self.query_one("#fz-console", RichLog)

    @property
    def _cli_log(self) -> RichLog:
        return self.query_one("#fz-cli-out", RichLog)

    def _say(self, msg: str, color: str = C_MUTED, cli: bool = False) -> None:
        (self._cli_log if cli else self._js_log).write(Text(msg, style=color))

    def _write_js(self, text: str) -> None:
        self._js_log.write(text)

    def _write_cli(self, text: str) -> None:
        self._cli_log.write(text)

    def _status(self, msg: str, color: str = C_MUTED) -> None:
        self.query_one("#fz-status", Static).update(Text(msg, style=color))

    def _set_conn(self, connected: bool) -> None:
        self.query_one("#fz-connect", Button).label = "Déconnecter" if connected else "Connecter"
        self.query_one("#fz-state", Static).update(
            Text("● connecté" if connected else "● déconnecté", style=C_GREEN if connected else C_RED))
        try:
            self.app.query_one(HomePage).set_flipper(
                connected, str(self.flipper.ser.port) if connected and self.flipper else "")
        except Exception:  # noqa: BLE001
            pass

    def _set_busy(self, busy: bool, label: str = "") -> None:
        self._busy = busy
        for b in self.query(Button):
            b.disabled = busy and b.id != "fz-stop"
        self.query_one("#fz-cli-in", Input).disabled = busy
        self._status(label if busy else "", C_ORANGE)

    def _refresh_ports(self) -> None:
        ports = list(list_ports.comports())
        sel = self.query_one("#fz-port", Select)
        sel.set_options([(f"{p.device} - {(p.description or '')[:20]}", p.device) for p in ports])
        for p in ports:
            if (p.vid, p.pid) == (FlipperUSB.VID, FlipperUSB.PID):
                sel.value = p.device
                break

    # ── connexion ────────────────────────────────────────────────
    @on(Button.Pressed, "#fz-refresh")
    def _on_refresh(self) -> None:
        self._refresh_ports()

    @on(Button.Pressed, "#fz-connect")
    def _toggle_connect(self) -> None:
        if self._busy:
            self._status("Opération en cours…", C_ORANGE)
            return
        if self.flipper is not None:
            try:
                with self.lock:
                    self.flipper.close()
            except Exception:  # noqa: BLE001
                pass
            self.flipper = None
            self._set_conn(False)
            self._say("[Déconnecté]")
            return
        value = self.query_one("#fz-port", Select).value
        self._set_busy(True, "Connexion…")
        self._connect_worker(value if isinstance(value, str) else None)

    @work(thread=True, group="fz")
    def _connect_worker(self, port: str | None) -> None:
        call = self.app.call_from_thread
        try:
            fl = FlipperUSB(port)
        except Exception as exc:  # noqa: BLE001
            call(self._connect_done, None, str(exc))
            return
        call(self._connect_done, fl, "")

    def _connect_done(self, fl, error: str) -> None:
        self._set_busy(False)
        if fl is None:
            self._say(f"[ERREUR connexion] {error}", C_RED)
            self._status("Connexion impossible.", C_RED)
            return
        self.flipper = fl
        self._set_conn(True)
        self._say("[Connecté au Flipper]", C_GREEN)

    # ── fichiers locaux ──────────────────────────────────────────
    @on(Button.Pressed, "#fz-open")
    @on(Input.Submitted, "#fz-local")
    def do_open(self) -> None:
        if FLIPPER_ERROR is not None:
            return
        raw = self.query_one("#fz-local", Input).value.strip().strip('"').strip("'")
        if raw:
            self._load_path(raw)
        else:
            self.do_browse()

    @on(Button.Pressed, "#fz-browse")
    def do_browse(self) -> None:
        self.app.push_screen(FilePicker(), lambda path: self._load_path(path) if path else None)

    def _load_path(self, raw: str) -> None:
        path = Path(raw).expanduser()
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            self._say(f"[ERREUR lecture] {exc}", C_RED)
            self._status(f"Lecture impossible : {path.name}", C_RED)
            return
        self.query_one("#fz-editor", TextArea).load_text(text)
        self.query_one("#fz-local", Input).value = str(path)
        self.query_one("#fz-remote", Input).value = path.name
        self.query_one(TabbedContent).active = "fz-tab-js"
        self._say(f"[Chargé] {path}")
        self._status(f"📄 {path.name} chargé ({len(text)} caractères).", C_GREEN)

    @on(Button.Pressed, "#fz-save")
    def _save_local(self) -> None:
        raw = self.query_one("#fz-local", Input).value.strip()
        if not raw:
            self._status("Indiquez d'abord un chemin local.", C_RED)
            return
        try:
            Path(raw).expanduser().write_text(
                self.query_one("#fz-editor", TextArea).text, encoding="utf-8")
            self._say(f"[Sauvegardé] {raw}", C_GREEN)
            self._status("✔ Fichier sauvegardé.", C_GREEN)
        except Exception as exc:  # noqa: BLE001
            self._say(f"[ERREUR sauvegarde] {exc}", C_RED)
            self._status("Sauvegarde impossible.", C_RED)

    # ── envoi / exécution JS ─────────────────────────────────────
    @on(Button.Pressed, "#fz-send")
    def do_send(self) -> None:
        self._start_send(run=False)

    @on(Button.Pressed, "#fz-run")
    def do_run(self) -> None:
        self._start_send(run=True)

    @on(Button.Pressed, "#fz-stop")
    def do_stop(self) -> None:
        self.stop_flag.set()
        if self._busy:
            self._status("Arrêt demandé…", C_ORANGE)

    def _start_send(self, run: bool) -> None:
        if FLIPPER_ERROR is not None or self._busy:
            return
        if self.flipper is None:
            self._status("Connectez d'abord le Flipper.", C_RED)
            return
        name = self.query_one("#fz-remote", Input).value.strip().replace("/", "_")
        name = name or "python_script.js"
        if not name.endswith(".js"):
            name += ".js"
        data = self.query_one("#fz-editor", TextArea).text.encode("utf-8")
        self.stop_flag.clear()
        self.query_one(TabbedContent).active = "fz-tab-js"
        self._set_busy(True, "Envoi + exécution…" if run else "Envoi en cours…")
        self._transfer(f"{FLIPPER_REMOTE_DIR}/{name}", data, run)

    @work(thread=True, group="fz")
    def _transfer(self, remote: str, data: bytes, run: bool) -> None:
        call = self.app.call_from_thread
        pending = ""

        def on_output(chunk: str) -> None:
            # le Flipper renvoie des morceaux : on n'affiche que des lignes complètes
            nonlocal pending
            pending += chunk
            *lines, pending = pending.split("\n")
            for line in lines:
                call(self._write_js, line)

        try:
            with self.lock:
                call(self._say, f"[Envoi de {len(data)} octets vers {remote}]")
                self.flipper.upload(remote, data)
                call(self._say, "[Envoi OK]", C_GREEN)
                if run:
                    call(self._say, "[Exécution]", C_ORANGE)
                    self.flipper.run_js_stream(remote, on_output, self.stop_flag.is_set)
                    tail = pending.replace(">: ", "").strip()
                    if tail:
                        call(self._write_js, tail)
                    call(self._say, "[Fin]", C_GREEN)
        except Exception as exc:  # noqa: BLE001
            call(self._say, f"[ERREUR] {exc}", C_RED)
        finally:
            call(self._set_busy, False)

    # ── boutons rapides ──────────────────────────────────────────
    @on(QuickPanel.Run)
    def _qa_run(self, event: QuickPanel.Run) -> None:
        btn = event.button
        panel = self.query_one("#fz-qa", QuickPanel)
        if self._busy:
            panel.write("Opération en cours…", C_ORANGE)
            return
        if self.flipper is None:
            panel.write("Connectez d'abord le Flipper.", C_RED)
            self._status("Connectez d'abord le Flipper.", C_RED)
            return
        self.stop_flag.clear()
        self._set_busy(True, f"{btn.qa_title}…")
        if btn.qa_kind == "js":
            self._qa_js_worker(btn.qa_title, str(btn.qa_payload))
        else:
            self._qa_cli_worker(btn.qa_title, qb_lines(btn.qa_payload))

    @work(thread=True, group="fz")
    def _qa_cli_worker(self, title: str, cmds: list[str]) -> None:
        call = self.app.call_from_thread
        panel = self.query_one("#fz-qa", QuickPanel)
        try:
            with self.lock:
                call(panel.write, f"▶ {title}", C_ORANGE)
                for line in cmds:
                    if self.stop_flag.is_set():
                        call(panel.write, "[Arrêté]", C_ORANGE)
                        break
                    if line.lower().startswith("sleep "):
                        time.sleep(float(line[6:]))
                        continue
                    out = self.flipper.cmd(line, timeout=8)
                    if out:
                        call(panel.write, out)
                else:
                    call(panel.write, "✔ ok", C_GREEN)
        except Exception as exc:  # noqa: BLE001
            call(panel.write, f"[ERREUR] {exc}", C_RED)
        finally:
            call(self._set_busy, False)

    @work(thread=True, group="fz")
    def _qa_js_worker(self, title: str, code: str) -> None:
        call = self.app.call_from_thread
        panel = self.query_one("#fz-qa", QuickPanel)
        pending = ""

        def on_output(chunk: str) -> None:
            nonlocal pending
            pending += chunk
            *lines, pending = pending.split("\n")
            for line in lines:
                call(panel.write, line)

        try:
            with self.lock:
                call(panel.write, f"▶ {title}", C_ORANGE)
                self.flipper.upload(FLIPPER_QUICK_JS, code.encode("utf-8"))
                self.flipper.run_js_stream(FLIPPER_QUICK_JS, on_output, self.stop_flag.is_set)
                tail = pending.replace(">: ", "").strip()
                if tail:
                    call(panel.write, tail)
                call(panel.write, "✔ Fin", C_GREEN)
        except Exception as exc:  # noqa: BLE001
            call(panel.write, f"[ERREUR] {exc}", C_RED)
        finally:
            call(self._set_busy, False)

    # ── console CLI ──────────────────────────────────────────────
    @on(Input.Submitted, "#fz-cli-in")
    def _cli_submit(self, event: Input.Submitted) -> None:
        cmd = event.value.strip()
        if cmd and self._run_cli(cmd):
            event.input.value = ""

    @on(Button.Pressed, "#fz-info")
    def _quick_info(self) -> None:
        self._run_cli("device_info")

    @on(Button.Pressed, "#fz-ls")
    def _quick_ls(self) -> None:
        self._run_cli("storage list /ext")

    def _run_cli(self, cmd: str) -> bool:
        if self._busy:
            return False
        if self.flipper is None:
            self._status("Connectez d'abord le Flipper.", C_RED)
            return False
        self.query_one(TabbedContent).active = "fz-tab-cli"
        self._say(f">: {cmd}", C_ORANGE, cli=True)
        self._set_busy(True, "Commande en cours…")
        self._cli_worker(cmd)
        return True

    @work(thread=True, group="fz")
    def _cli_worker(self, cmd: str) -> None:
        call = self.app.call_from_thread
        try:
            with self.lock:
                out = self.flipper.cmd(cmd, timeout=8)
            call(self._write_cli, out or "(aucune sortie)")
        except Exception as exc:  # noqa: BLE001
            call(self._say, f"[ERREUR] {exc}", C_RED, True)
        finally:
            call(self._set_busy, False)

# ═════════════════════════════════════════════════════════════════
#  Page native W_F : ESP32 (module WiFi du Flipper) - C/C++ + flash
# ═════════════════════════════════════════════════════════════════
ESP_RE = {
    "prog": re.compile(r"Sketch uses (\d+) bytes \((\d+)%\) of program storage space\. Maximum is (\d+) bytes", re.I),
    "ram": re.compile(r"Global variables use (\d+) bytes \((\d+)%\) of dynamic memory, leaving (\d+) bytes "
                      r"for local variables\. Maximum is (\d+) bytes", re.I),
    "chip": re.compile(r"(?:Chip is|Chip type:)\s*(.+)", re.I),
    "feat": re.compile(r"Features:\s*(.+)", re.I),
    "mac": re.compile(r"MAC:\s*([0-9a-f]{2}(?::[0-9a-f]{2}){5})", re.I),
    "flash": re.compile(r"(?:Detected flash size|Flash size):\s*(\S+)", re.I),
    "wrote": re.compile(r"Wrote (\d+) bytes.*? at (0x[0-9a-f]+) in ([\d.]+) seconds "
                        r"\(effective ([\d.]+) kbit/s\)", re.I),
    "fatal": re.compile(r"A fatal error occurred:\s*(.+)", re.I),
    "cerr": re.compile(r"^(.*?:\d+:\d+): (?:fatal )?error: (.+)$", re.I),
}

def esp_build_report(kind: str, ok: bool, stopped: bool, elapsed: float,
                     lines: list[str], meta: dict) -> tuple[str, str, list[tuple[str, str]]]:
    """Résume la sortie d'arduino-cli / esptool : (titre, couleur, lignes (texte, style)).
    Utile quand l'ESP32 est seul (sans écran ni LED visibles)."""
    text = "\n".join(lines)
    low = text.lower()
    titles = {"compile": "COMPILATION", "upload": "COMPILATION + TÉLÉVERSEMENT",
              "flash": "FLASH ESPTOOL"}
    if stopped:
        head, color = "■ ARRÊTÉ", C_ORANGE
    elif ok:
        head, color = "✔ SUCCÈS", C_GREEN
    else:
        head, color = "✘ ÉCHEC", C_RED
    rows: list[tuple[str, str]] = [(f"══ {titles.get(kind, kind.upper())} · {head} ══", f"bold {color}")]

    def row(label: str, value: str, style: str = "") -> None:
        rows.append((f"{label:<17}: {value}", style))

    def num(v) -> str:
        return f"{int(v):,}".replace(",", " ")

    row("Durée", f"{elapsed:.1f} s")
    if meta:
        row("Carte", f"{meta.get('board', '?')}  ({meta.get('fqbn', '?')})")
        row("Port", f"{meta.get('port', '?')}")
    m = ESP_RE["prog"].search(text)
    if m:
        row("Programme", f"{num(m[1])} octets ({m[2]} %) sur {num(m[3])}")
    m = ESP_RE["ram"].search(text)
    if m:
        row("Mémoire (RAM)", f"{num(m[1])} octets ({m[2]} %) — {num(m[3])} libres sur {num(m[4])}")
    for key, label in (("chip", "Puce"), ("feat", "Caractéristiques"), ("mac", "Adresse MAC"),
                       ("flash", "Flash")):
        m = ESP_RE[key].search(text)
        if m:
            row(label, m[1].strip())
    writes = ESP_RE["wrote"].findall(text)
    if writes:
        total = sum(int(w[0]) for w in writes)
        secs = sum(float(w[2]) for w in writes)
        row("Écrit", f"{num(total)} octets en {secs:.1f} s "
                     f"({len(writes)} région(s), dernière à {writes[-1][1]})")
        verified = low.count("hash of data verified")
        row("Vérification", f"{'✔' if verified >= len(writes) else '⚠'} "
                            f"{verified}/{len(writes)} région(s) vérifiée(s)",
            C_GREEN if verified >= len(writes) else C_ORANGE)
    if "hard resetting" in low:
        row("Redémarrage", "✔ carte redémarrée (hard reset)", C_GREEN)

    if not ok and not stopped:
        diag: list[tuple[str, str]] = []
        m = ESP_RE["fatal"].search(text)
        if m:
            diag.append((f"{'Erreur esptool':<17}: {m[1].strip()}", C_RED))
        errs = [f"{mm[1]} → {mm[2]}" for ln in lines
                if (mm := ESP_RE["cerr"].match(ln.strip()))][:3]
        diag += [(f"{'Erreur compilation':<17}: {e}", C_RED) for e in errs]
        hints = []
        if "permission denied" in low:
            hints.append("Droits du port refusés : « sudo usermod -aG dialout $USER », "
                         "puis fermez et rouvrez votre session.")
        if any(k in low for k in ("failed to connect", "no serial data received",
                                  "wrong boot mode", "timed out waiting for packet header")):
            hints.append("La puce ne répond pas : maintenez BOOT, appuyez sur RESET, relâchez BOOT, "
                         "puis relancez (ou essayez un autre câble / port).")
        if any(k in low for k in ("resource busy", "could not exclusively lock",
                                  "access is denied", "port is busy")):
            hints.append("Port occupé : fermez les autres moniteurs série "
                         "(sous Linux : « sudo systemctl stop ModemManager »).")
        if any(k in low for k in ("sketch too big", "text section exceeds", "region `iram")):
            hints.append("Sketch trop gros pour la partition : choisissez un schéma de partition plus grand.")
        if any(k in low for k in ("not installed", "unknown fqbn", "platform esp32")):
            hints.append("Core ESP32 absent : cliquez sur « Installer core ESP32 ».")
        if not diag and not hints:
            hints.append("Cause non identifiée : consultez l'onglet « Code C/C++ » (sortie complète).")
        rows.append(("", ""))
        rows.append(("── DIAGNOSTIC ──", f"bold {C_RED}"))
        rows += diag
        rows += [(f"→ {h}", C_ORANGE) for h in hints]
    return head, color, rows

def _esp32_editor() -> TextArea:
    try:
        return TextArea.code_editor(esp.TEMPLATE, language="cpp", id="es-editor")
    except Exception:  # noqa: BLE001  (langage non disponible : pas de coloration)
        return TextArea.code_editor(esp.TEMPLATE, id="es-editor")

class ESP32Page(Horizontal):
    """ESP32 en série (USB direct ou via « USB-UART Bridge » du Flipper) : moniteur série,
    compilation / téléversement de sketchs C/C++ (arduino-cli) et flash de .bin (esptool).
    Les commandes externes tournent dans un thread, leur sortie est relayée en direct."""

    def __init__(self) -> None:
        super().__init__(id="p_esp32")
        self.ser = None
        self.reader_stop = threading.Event()
        self.stop_flag = threading.Event()
        self.proc = None
        self._busy = False
        self._mirror_until = 0.0                       # recopie du moniteur vers l'onglet Boutons
        self._auto_monitor: tuple[str, int] | None = None
        self._all_lines: list[str] = []                # sortie complète de la dernière tâche
        self._meta: dict = {}
        self._t0 = 0.0
        self._report_until = 0.0                       # fenêtre de capture série post-téléversement
        self._cap_lines: list[str] = []

    def compose(self) -> ComposeResult:
        if ESP32_ERROR is not None:
            yield Static(Text(f"Module ESP32 indisponible : {ESP32_ERROR}  "
                              "(pip install pyserial)", style=C_RED))
            return
        with VerticalScroll(id="es-left"):
            yield Label("CONNEXION", classes="section")
            yield Select([], prompt="Port série", id="es-port", allow_blank=True)
            yield Select([(str(b), b) for b in esp.BAUDS], value=115200,
                         allow_blank=False, id="es-baud")
            with Horizontal(classes="btn-row"):
                yield Button("↻ Ports", id="es-refresh")
                yield Button("Connecter", id="es-connect", variant="primary")
            yield Static("", id="es-state")
            yield Label("CARTE & SKETCH", classes="section")
            yield Select(esp.BOARDS, value=esp.BOARDS[0][1], allow_blank=False, id="es-board")
            with Horizontal(classes="sw-row"):
                yield Switch(value=True, id="es-cdc")
                yield Label(" Serial via USB (CDC)")
            yield Input(value="sketch", placeholder="Nom du sketch", id="es-name")
            yield Label("FICHIER LOCAL", classes="section")
            yield Input(placeholder="Chemin local .ino / .c / .cpp", id="es-local")
            with Horizontal(classes="btn-row"):
                yield Button("Ouvrir", id="es-open")
                yield Button("Parcourir", id="es-browse")
                yield Button("Sauver", id="es-save")
            yield Label("COMPILATION", classes="section")
            yield Button("Compiler  [F3]", id="es-compile")
            yield Button("Téléverser ▶  [F4]", id="es-upload", variant="success")
            yield Button("Installer core ESP32", id="es-core")
            yield Button("■ Stop  [F12]", id="es-stop", variant="error")
            yield Label("FIRMWARE .BIN", classes="section")
            yield Input(placeholder="Firmware .bin à flasher", id="es-bin")
            yield Input(value="0x10000", placeholder="Adresse (0x0 = .bin complet)", id="es-addr")
            with Horizontal(classes="btn-row"):
                yield Button("Parcourir .bin", id="es-bin-browse")
                yield Button("Flasher", id="es-flash", variant="warning")
            yield Static("", id="es-status")
        with TabbedContent(id="es-tabs"):
            with TabPane("Code C/C++", id="es-tab-code"):
                yield _esp32_editor()
                yield RichLog(id="es-build", wrap=True, markup=False, highlight=False)
            with TabPane("Moniteur série", id="es-tab-mon"):
                yield RichLog(id="es-monitor", wrap=True, markup=False, highlight=False)
                with Horizontal(id="es-sendbar"):
                    yield Input(placeholder="Envoyer une ligne à l'ESP32…", id="es-send")
                    yield Select(esp.EOLS, value="\r\n", allow_blank=False, id="es-eol")
            with TabPane("⚡ Boutons", id="es-tab-btn"):
                yield QuickPanel("es", "esp32", ESP32_QA,
                                 [("Commandes série", "serial"), ("Sketch Arduino", "sketch")],
                                 "#es-editor", "sketch", "cmd1; sleep 1; cmd2  (ou code C++)")
            with TabPane("📋 Rapport", id="es-tab-report"):
                yield RichLog(id="es-report", wrap=True, markup=False, highlight=False)

    def on_mount(self) -> None:
        if ESP32_ERROR is not None:
            return
        self._set_conn(False)
        self._refresh_ports()
        self._say("Prêt. Branchez l'ESP32 (USB-C direct ou via le Flipper en "
                  "« USB-UART Bridge »), choisissez le port puis Connecter.")

    # ── utilitaires ──────────────────────────────────────────────
    def _say(self, msg: str, color: str = C_MUTED, mon: bool = False) -> None:
        log = self.query_one("#es-monitor" if mon else "#es-build", RichLog)
        log.write(Text(msg, style=color))

    def _status(self, msg: str, color: str = C_MUTED) -> None:
        self.query_one("#es-status", Static).update(Text(msg, style=color))

    def _ui(self, fn, *args):
        """Appelle fn dans le thread de l'interface (depuis un thread de fond)."""
        try:
            return self.app.call_from_thread(fn, *args)
        except Exception:  # noqa: BLE001
            return None

    def _set_conn(self, connected: bool) -> None:
        self.query_one("#es-connect", Button).label = "Déconnecter" if connected else "Connecter"
        self.query_one("#es-state", Static).update(
            Text("● connecté" if connected else "● déconnecté", style=C_GREEN if connected else C_RED))
        try:
            self.app.query_one(HomePage).set_esp32(
                connected, str(self.ser.port) if connected and self.ser else "")
        except Exception:  # noqa: BLE001
            pass

    def _set_busy(self, busy: bool, label: str = "") -> None:
        self._busy = busy
        for b in self.query(Button):
            b.disabled = busy and b.id != "es-stop"
        self._status(label if busy else "", C_ORANGE)

    def _refresh_ports(self) -> None:
        ports = list(list_ports.comports())
        sel = self.query_one("#es-port", Select)
        sel.set_options([(f"{p.device} - {(p.description or '')[:20]}", p.device) for p in ports])
        pick = next((p for p in ports if p.vid == esp.ESPRESSIF_VID), None) or \
            next((p for p in ports if (p.vid, p.pid) == esp.FLIPPER_VID_PID), None)
        if pick:
            sel.value = pick.device

    def _port(self) -> str | None:
        value = self.query_one("#es-port", Select).value
        return value if isinstance(value, str) else None

    def _fqbn(self) -> str:
        fqbn = str(self.query_one("#es-board", Select).value)
        if self.query_one("#es-cdc", Switch).value and fqbn != "esp32:esp32:esp32":
            fqbn += ":CDCOnBoot=cdc"
        return fqbn

    # ── moniteur série ───────────────────────────────────────────
    def _open_monitor(self, port: str, baud: int) -> None:
        self.ser = serial.Serial(port, baud, timeout=0.1)
        self.reader_stop = threading.Event()
        threading.Thread(target=self._reader, args=(self.ser, self.reader_stop),
                         daemon=True).start()
        self._set_conn(True)
        self._say(f"[Connecté à {port} @ {baud}]", C_GREEN, mon=True)

    def _close_monitor(self) -> None:
        self.reader_stop.set()
        if self.ser:
            try:
                self.ser.close()
            except Exception:  # noqa: BLE001
                pass
        self._set_conn(False)
        self.ser = None

    def _monitor_lost(self, err: str) -> None:
        self._close_monitor()
        self._say(f"[Connexion perdue] {err}", C_RED, mon=True)

    def _write_mon(self, line: str) -> None:
        self.query_one("#es-monitor", RichLog).write(line)
        if time.time() < self._mirror_until:           # réponse à un bouton : on la recopie
            self.query_one("#es-qa", QuickPanel).write(line)
        if time.time() < self._report_until:           # capture post-téléversement
            self._cap_lines.append(line)
            self.query_one("#es-report", RichLog).write(Text("  " + line, style="cyan"))

    def _reader(self, ser, stop: threading.Event) -> None:
        buf = ""
        while not stop.is_set():
            try:
                data = ser.read(ser.in_waiting or 1)
            except Exception as exc:  # noqa: BLE001
                if not stop.is_set():
                    self._ui(self._monitor_lost, str(exc))
                return
            if not data:
                if buf:                       # ligne sans retour chariot (prompt…)
                    self._ui(self._write_mon, buf)
                    buf = ""
                continue
            buf += data.decode(errors="replace").replace("\r", "")
            *lines, buf = buf.split("\n")
            for line in lines:
                self._ui(self._write_mon, line)

    @on(Button.Pressed, "#es-refresh")
    def _on_refresh(self) -> None:
        self._refresh_ports()

    @on(Button.Pressed, "#es-connect")
    def _toggle_connect(self) -> None:
        if self._busy:
            self._status("Opération en cours…", C_ORANGE)
            return
        if self.ser:
            self._close_monitor()
            self._say("[Déconnecté]", mon=True)
            return
        port = self._port()
        if not port:
            self._status("Choisissez d'abord un port série.", C_RED)
            return
        try:
            self._open_monitor(port, int(self.query_one("#es-baud", Select).value))
        except Exception as exc:  # noqa: BLE001
            self._say(f"[ERREUR connexion] {exc}", C_RED, mon=True)
            self._status("Connexion impossible.", C_RED)

    @on(Input.Submitted, "#es-send")
    def _send_line(self, event: Input.Submitted) -> None:
        if not self.ser:
            self._status("Connectez d'abord l'ESP32.", C_RED)
            return
        eol = self.query_one("#es-eol", Select).value
        try:
            self.ser.write(event.value.encode() + (eol if isinstance(eol, str) else "").encode())
            self._say(f"> {event.value}", "cyan", mon=True)
            event.input.value = ""
        except Exception as exc:  # noqa: BLE001
            self._say(f"[ERREUR envoi] {exc}", C_RED, mon=True)

    # ── fichiers ─────────────────────────────────────────────────
    # ── rapport de téléversement ─────────────────────────────────
    def _show_report(self, kind: str, ok: bool, stopped: bool, elapsed: float) -> None:
        _, _, rows = esp_build_report(kind, ok, stopped, elapsed, self._all_lines, self._meta)
        log = self.query_one("#es-report", RichLog)
        log.clear()
        for text, style in rows:
            log.write(Text(text, style=style))
        try:
            esp.BUILD_DIR.mkdir(parents=True, exist_ok=True)
            (esp.BUILD_DIR / "last_report.txt").write_text(
                "\n".join(t for t, _ in rows), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        self.query_one("#es-tabs", TabbedContent).active = "es-tab-report"

    def _start_capture(self) -> None:
        """Pendant 6 s, la sortie série de l'ESP32 est recopiée dans le rapport."""
        self._cap_lines = []
        self._report_until = time.time() + 6
        log = self.query_one("#es-report", RichLog)
        log.write(Text(""))
        log.write(Text("── Sortie série de l'ESP32 après redémarrage (6 s) ──",
                       style=f"bold {C_ORANGE}"))
        self.set_timer(6.5, self._finish_capture)

    def _finish_capture(self) -> None:
        log = self.query_one("#es-report", RichLog)
        if self._cap_lines:
            log.write(Text(f"✔ {len(self._cap_lines)} ligne(s) reçue(s) : le programme tourne.",
                           style=C_GREEN))
        else:
            log.write(Text(
                "Aucune sortie série reçue. Causes possibles : le sketch n'écrit rien "
                "(Serial.println), débit différent de celui choisi, « Serial via USB (CDC) » mal "
                "réglé, ou la carte est restée en mode bootloader. Essayez « 📋 Reset + voir la "
                "sortie » dans l'onglet ⚡ Boutons.", style=C_ORANGE))

    def _qa_reset_capture(self) -> None:
        panel = self.query_one("#es-qa", QuickPanel)
        if not self.ser:
            panel.write("Connectez d'abord l'ESP32 (bouton Connecter).", C_RED)
            return
        self.query_one("#es-report", RichLog).clear()
        self._qa_pulse(False)
        self._start_capture()
        self.query_one("#es-tabs", TabbedContent).active = "es-tab-report"

    # ── boutons rapides ──────────────────────────────────────────
    @on(QuickPanel.Run)
    def _qa_run(self, event: QuickPanel.Run) -> None:
        btn = event.button
        panel = self.query_one("#es-qa", QuickPanel)
        if self._busy:
            panel.write("Opération en cours…", C_ORANGE)
            return
        kind, payload = btn.qa_kind, btn.qa_payload
        if kind == "serial":
            if not self.ser:
                panel.write("Connectez d'abord l'ESP32 (bouton Connecter).", C_RED)
                self._status("Connectez d'abord l'ESP32.", C_RED)
                return
            eol = self.query_one("#es-eol", Select).value
            self._qa_serial_worker(btn.qa_title, qb_lines(payload),
                                   eol if isinstance(eol, str) else "")
        elif kind == "resetcap":
            self._qa_reset_capture()
        elif kind in ("reset", "boot"):
            self._qa_pulse(kind == "boot")
        elif kind == "esptool":
            self._qa_esptool(btn.qa_title, list(payload))
        elif kind == "sketch":
            self._qa_sketch(btn.qa_title, str(payload))

    @work(thread=True, group="es-qa")
    def _qa_serial_worker(self, title: str, lines: list[str], eol: str) -> None:
        panel = self.query_one("#es-qa", QuickPanel)
        ser = self.ser
        self._mirror_until = time.time() + 4
        self._ui(panel.write, f"▶ {title}", C_ORANGE)
        try:
            for line in lines:
                if line.lower().startswith("sleep "):
                    time.sleep(float(line[6:]))
                    continue
                ser.write(line.encode() + eol.encode())
                self._ui(panel.write, f"> {line}", "cyan")
                self._mirror_until = time.time() + 4
                time.sleep(0.05)
        except Exception as exc:  # noqa: BLE001
            self._ui(panel.write, f"[ERREUR envoi] {exc}", C_RED)

    def _qa_pulse(self, bootloader: bool) -> None:
        panel = self.query_one("#es-qa", QuickPanel)
        if not self.ser:
            panel.write("Connectez d'abord l'ESP32 (bouton Connecter).", C_RED)
            return
        s = self.ser
        try:
            if bootloader:
                s.dtr, s.rts = False, True
                time.sleep(0.1)
                s.dtr, s.rts = True, False
                time.sleep(0.1)
                s.dtr = False
                panel.write("Mode bootloader demandé (pont USB-série classique ; "
                            "sinon BOOT + RESET à la main).", C_ORANGE)
            else:
                s.dtr, s.rts = False, True
                time.sleep(0.1)
                s.rts = False
                self._mirror_until = time.time() + 4
                panel.write("Reset envoyé.", C_GREEN)
        except Exception as exc:  # noqa: BLE001
            panel.write(f"[ERREUR reset] {exc}", C_RED)

    def _qa_esptool(self, title: str, args: list[str]) -> None:
        panel = self.query_one("#es-qa", QuickPanel)
        if importlib.util.find_spec("esptool") is None:
            panel.write("esptool manquant : pip install esptool", C_RED)
            return
        port = self._port()
        if not port:
            panel.write("Choisissez d'abord un port série.", C_RED)
            return
        panel.write(f"▶ {title} — sortie dans l'onglet « Code C/C++ ».", C_ORANGE)
        self._begin("flash", [[sys.executable, "-m", "esptool", "--port", port, *args]],
                    True, f"{title}…")

    def _qa_sketch(self, title: str, code: str) -> None:
        panel = self.query_one("#es-qa", QuickPanel)
        if not (exe := self._arduino_cli()):
            panel.write("arduino-cli introuvable.", C_RED)
            return
        port = self._port()
        if not port:
            panel.write("Choisissez d'abord un port série.", C_RED)
            return
        folder = esp.BUILD_DIR / "quick_sketch"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "quick_sketch.ino").write_text(code, encoding="utf-8")
        fqbn = self._fqbn()
        self._auto_monitor = None if self.ser else (
            port, int(self.query_one("#es-baud", Select).value))
        panel.write(f"▶ {title} — compilation dans l'onglet « Code C/C++ » "
                    "(votre éditeur n'est pas modifié).", C_ORANGE)
        self._begin("upload", [
            [exe, "compile", "--fqbn", fqbn, str(folder)],
            [exe, "upload", "-p", port, "--fqbn", fqbn, str(folder)],
        ], True, f"{title}…")

    @on(Button.Pressed, "#es-open")
    @on(Input.Submitted, "#es-local")
    def do_open(self) -> None:
        if ESP32_ERROR is not None:
            return
        raw = self.query_one("#es-local", Input).value.strip().strip('"').strip("'")
        if raw:
            self._load_path(raw)
        else:
            self._browse()

    @on(Button.Pressed, "#es-browse")
    def _browse(self) -> None:
        self.app.push_screen(
            FilePicker((".ino", ".c", ".cpp", ".h"), "CHOISIR UN FICHIER C/C++"),
            lambda path: self._load_path(path) if path else None)

    @on(Button.Pressed, "#es-bin-browse")
    def _browse_bin(self) -> None:
        def picked(path: str | None) -> None:
            if path:
                self.query_one("#es-bin", Input).value = path
        self.app.push_screen(FilePicker((".bin",), "CHOISIR UN FIRMWARE .bin"), picked)

    def _load_path(self, raw: str) -> None:
        path = Path(raw).expanduser()
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            self._say(f"[ERREUR lecture] {exc}", C_RED)
            self._status(f"Lecture impossible : {path.name}", C_RED)
            return
        self.query_one("#es-editor", TextArea).load_text(text)
        self.query_one("#es-local", Input).value = str(path)
        self.query_one("#es-name", Input).value = path.stem
        self.query_one("#es-tabs", TabbedContent).active = "es-tab-code"
        self._say(f"[Chargé] {path}")
        self._status(f"📄 {path.name} chargé ({len(text)} caractères).", C_GREEN)

    @on(Button.Pressed, "#es-save")
    def _save_local(self) -> None:
        raw = self.query_one("#es-local", Input).value.strip()
        if not raw:
            self._status("Indiquez d'abord un chemin local.", C_RED)
            return
        try:
            Path(raw).expanduser().write_text(
                self.query_one("#es-editor", TextArea).text, encoding="utf-8")
            self._say(f"[Sauvegardé] {raw}", C_GREEN)
            self._status("✔ Fichier sauvegardé.", C_GREEN)
        except Exception as exc:  # noqa: BLE001
            self._say(f"[ERREUR sauvegarde] {exc}", C_RED)
            self._status("Sauvegarde impossible.", C_RED)

    def _write_sketch(self) -> Path:
        """Arduino exige un dossier <nom>/<nom>.ino."""
        name = re.sub(r"[^A-Za-z0-9_]", "_", self.query_one("#es-name", Input).value.strip())
        name = name or "sketch"
        if name[0].isdigit():
            name = "s_" + name
        folder = esp.BUILD_DIR / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{name}.ino").write_text(
            self.query_one("#es-editor", TextArea).text, encoding="utf-8")
        return folder

    # ── actions de build ─────────────────────────────────────────
    def _arduino_cli(self) -> str | None:
        exe = shutil.which("arduino-cli")
        if not exe:
            self._say("[arduino-cli introuvable] Installez-le : "
                      "https://arduino.github.io/arduino-cli/", C_RED)
            self._status("arduino-cli introuvable.", C_RED)
        return exe

    def _begin(self, kind: str, steps: list[list[str]], release_port: bool, label: str) -> None:
        self.query_one("#es-tabs", TabbedContent).active = "es-tab-code"
        self.stop_flag.clear()
        board = str(self.query_one("#es-board", Select).value)
        self._meta = {"port": self._port() or "?", "fqbn": self._fqbn(),
                      "board": next((n for n, v in esp.BOARDS if v == board), board)}
        self._all_lines = []
        self._t0 = time.time()
        self._set_busy(True, label)
        self._run_task(kind, steps, release_port)

    @on(Button.Pressed, "#es-compile")
    def do_send(self) -> None:   # F3 : « Envoyer / Compiler »
        if ESP32_ERROR is not None or self._busy or not (exe := self._arduino_cli()):
            return
        folder = self._write_sketch()
        self._begin("compile", [[exe, "compile", "--fqbn", self._fqbn(), str(folder)]],
                    False, "Compilation…")

    @on(Button.Pressed, "#es-upload")
    def do_run(self) -> None:    # F4 : « Exécuter / Téléverser »
        if ESP32_ERROR is not None or self._busy or not (exe := self._arduino_cli()):
            return
        port = self._port()
        if not port:
            self._status("Choisissez d'abord un port série.", C_RED)
            return
        folder, fqbn = self._write_sketch(), self._fqbn()
        self._auto_monitor = None if self.ser else (
            port, int(self.query_one("#es-baud", Select).value))
        self._begin("upload", [
            [exe, "compile", "--fqbn", fqbn, str(folder)],
            [exe, "upload", "-p", port, "--fqbn", fqbn, str(folder)],
        ], True, "Compilation + téléversement…")

    @on(Button.Pressed, "#es-core")
    def _install_core(self) -> None:
        if self._busy or not (exe := self._arduino_cli()):
            return
        base = [exe, "--additional-urls", esp.ESP32_INDEX_URL]
        self._say("[Installation du core ESP32 : plusieurs centaines de Mo à télécharger]", C_ORANGE)
        self._begin("core", [base + ["core", "update-index"],
                             base + ["core", "install", "esp32:esp32"]], False,
                    "Installation du core ESP32…")

    @on(Button.Pressed, "#es-flash")
    def _flash_bin(self) -> None:
        if self._busy:
            return
        if importlib.util.find_spec("esptool") is None:
            self._say("[esptool manquant] pip install esptool", C_RED)
            self._status("esptool manquant.", C_RED)
            return
        port = self._port()
        raw = self.query_one("#es-bin", Input).value.strip().strip('"').strip("'")
        binfile = Path(raw).expanduser()
        addr = self.query_one("#es-addr", Input).value.strip()
        if not port:
            self._status("Choisissez d'abord un port série.", C_RED)
        elif not raw or not binfile.is_file():
            self._status(f"Firmware introuvable : {raw or '(vide)'}", C_RED)
        elif not re.fullmatch(r"0x[0-9a-fA-F]+|\d+", addr):
            self._status("Adresse invalide (ex : 0x10000, ou 0x0).", C_RED)
        else:
            self._begin("flash", [[sys.executable, "-m", "esptool", "--port", port,
                                   "--baud", str(esp.FLASH_BAUD), "write_flash", addr, str(binfile)]],
                        True, "Flash en cours…")

    @on(Button.Pressed, "#es-stop")
    def do_stop(self) -> None:
        self.stop_flag.set()
        proc = self.proc
        if proc and proc.poll() is None:
            proc.terminate()
        if self._busy:
            self._status("Arrêt demandé…", C_ORANGE)

    # ── exécution des commandes externes (thread) ────────────────
    def _write_build(self, line: str, color: str = "") -> None:
        self.query_one("#es-build", RichLog).write(Text(line, style=color))

    def _run_proc(self, cmd: list[str]) -> tuple[int, str]:
        """Lance cmd, relaie sa sortie en direct. Renvoie (code, fin de sortie)."""
        tail: list[str] = []
        last_bucket = -1
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace", bufsize=1)
        except Exception as exc:  # noqa: BLE001
            self._ui(self._write_build, f"[ERREUR] {exc}", C_RED)
            return -1, ""
        self.proc = proc
        for line in proc.stdout:
            line = line.rstrip()
            m = esp.PCT.search(line)
            if m:                              # progression esptool : un affichage tous les 10 %
                bucket = int(m.group(1)) // 10
                if bucket == last_bucket:
                    continue
                last_bucket = bucket
            tail = (tail + [line])[-40:]
            self._all_lines.append(line)
            self._ui(self._write_build, line)
        rc = proc.wait()
        self.proc = None
        return rc, "\n".join(tail)

    @work(thread=True, group="es")
    def _run_task(self, kind: str, steps: list[list[str]], release_port: bool) -> None:
        saved, ok = None, True
        try:
            if release_port and self.ser:      # le port doit être libre pour le téléversement
                saved = (self.ser.port, self.ser.baudrate)
                self._ui(self._close_monitor)
            elif release_port and self._auto_monitor:  # sketch d'un bouton : rouvre le moniteur
                saved, self._auto_monitor = self._auto_monitor, None
            if kind in ("upload", "flash"):
                self._ui(self._write_build, "Si l'ESP32 ne répond pas : maintenez BOOT, appuyez sur "
                                            "RESET, relâchez BOOT, puis relancez.", C_MUTED)
            for cmd in steps:
                if self.stop_flag.is_set():
                    ok = False
                    break
                self._ui(self._write_build, "$ " + " ".join(cmd), C_ORANGE)
                rc, tail = self._run_proc(cmd)
                if rc != 0:
                    ok = False
                    if self.stop_flag.is_set():
                        break
                    low = tail.lower()
                    if "not installed" in low or "unknown fqbn" in low or "platform" in low:
                        self._ui(self._write_build, "→ Core ESP32 absent ? Cliquez sur "
                                                    "« Installer core ESP32 ».", C_ORANGE)
                    elif kind in ("upload", "flash"):
                        self._ui(self._write_build, "→ Mettez l'ESP32 en mode bootloader "
                                                    "(BOOT + RESET) et vérifiez le port.", C_ORANGE)
                    break
            if self.stop_flag.is_set():
                self._ui(self._write_build, "[Arrêté]", C_ORANGE)
            else:
                self._ui(self._write_build, "[Terminé]" if ok else "[ÉCHEC]", C_GREEN if ok else C_RED)
            if kind in ("compile", "upload", "flash"):
                self._ui(self._show_report, kind, ok, self.stop_flag.is_set(),
                         time.time() - self._t0)
            if saved and self._reconnect(*saved) and ok and kind in ("upload", "flash"):
                self._ui(self._start_capture)
        finally:
            self._ui(self._refresh_ports)
            self._ui(self._set_busy, False)

    def _reconnect(self, port: str, baud: int) -> bool:
        """Le port peut se ré-énumérer après un flash : on réessaie quelques secondes."""
        for _ in range(12):                    # on rouvre vite pour ne pas rater les messages de boot
            time.sleep(0.5)
            try:
                self.app.call_from_thread(self._open_monitor, port, baud)
                return True
            except Exception:  # noqa: BLE001
                continue
        self._ui(self._say, "[Reconnexion impossible] Le port a peut-être changé : "
                            "rafraîchissez les ports puis reconnectez.", C_ORANGE, True)
        return False

    def shutdown(self) -> None:
        self.stop_flag.set()
        self.reader_stop.set()
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
            if self.ser:
                self.ser.close()
        except Exception:  # noqa: BLE001
            pass

# ═════════════════════════════════════════════════════════════════
#  Page d'accueil
# ═════════════════════════════════════════════════════════════════
class HomePage(VerticalScroll):
    def __init__(self) -> None:
        super().__init__(id="home")
        self._host, self._ip = "…", "…"
        self._flipper = "[bold red]● déconnecté[/bold red]"
        self._esp32 = "[bold red]● déconnecté[/bold red]"

    def compose(self) -> ComposeResult:
        yield Static(id="home-banner")
        yield Static(id="home-help")

    def on_mount(self) -> None:
        self._render_banner("…", "…")
        help_ = Text()
        help_.append("\nUtilisation\n", style="bold")
        help_.append("  ↑/↓ choisir un module · Entrée valider et aller à sa page · F1 revenir au menu\n"
                     "  Ctrl+Q quitter\n\n", style=C_MUTED)
        help_.append("Raccourcis du détecteur IA : ", style="bold")
        help_.append("F5 Analyser · F6 Humaniser · F7 Reformater · F8 Exporter · F9 Réinitialiser\n", style=C_MUTED)
        help_.append("Raccourcis Flipper / ESP32 : ", style="bold")
        help_.append("F2 Ouvrir · F3 Envoyer / Compiler · F4 Exécuter / Téléverser · F12 Stop\n",
                     style=C_MUTED)
        self.query_one("#home-help", Static).update(help_)
        self._fetch_info()

    @work(thread=True)
    def _fetch_info(self) -> None:
        host, ip = get_hostname(), get_public_ip()
        self.app.call_from_thread(self._render_banner, host, ip)

    def set_flipper(self, connected: bool, port: str = "") -> None:
        if connected:
            self._flipper = "[bold green]● connecté[/bold green]" + (f" [dim]{escape(port)}[/dim]" if port else "")
        else:
            self._flipper = "[bold red]● déconnecté[/bold red]"
        self._render_banner()

    def set_esp32(self, connected: bool, port: str = "") -> None:
        if connected:
            self._esp32 = "[bold green]● connecté[/bold green]" + (f" [dim]{escape(port)}[/dim]" if port else "")
        else:
            self._esp32 = "[bold red]● déconnecté[/bold red]"
        self._render_banner()

    def _render_banner(self, host: str | None = None, ip: str | None = None) -> None:
        self._host = host if host is not None else self._host
        self._ip = ip if ip is not None else self._ip
        flipper = self._flipper if FLIPPER_ERROR is None else None
        esp32 = self._esp32 if ESP32_ERROR is None else None
        body = build_banner_body(self._host, self._ip, flipper, esp32)
        self.query_one("#home-banner", Static).update(Panel.fit(body, border_style="orange1"))

# ═════════════════════════════════════════════════════════════════
#  Application
# ═════════════════════════════════════════════════════════════════
class WatchFoxApp(App):
    TITLE = "🦊 Watch Fox"
    SUB_TITLE = "Intelligence & Investigation Framework"

    CSS = """
    Screen { background: #0F1117; }
    #sidebar { width: 36; background: #1A1D27; border-right: heavy #2E3247; }
    #menu { background: #1A1D27; border: none; height: 1fr; }
    ContentSwitcher { width: 1fr; height: 1fr; }
    #home { padding: 1 2; }

    .section { color: #7A788A; text-style: bold; margin-top: 1; }

    /* Pages génériques */
    ModulePage { padding: 1 2; height: 1fr; }
    .page-title { text-style: bold; color: #FF8C42; }
    .page-desc { color: #7A788A; margin-bottom: 1; }
    .field-label { color: #7A788A; margin-top: 1; }
    .btn-row { height: 3; margin-top: 1; }
    .btn-row Button { margin-right: 1; }
    ModulePage RichLog { height: 1fr; min-height: 8; margin-top: 1; border: round #2E3247;
                         background: #14161F; }
    #prompt-label { height: auto; }

    /* Page détecteur IA */
    #ad-left { width: 46; min-width: 38; background: #1A1D27; padding: 0 1; border-right: heavy #2E3247; }
    #ad-right { width: 1fr; padding: 0 1; }
    #ad-editor { height: 1fr; min-height: 8; margin-bottom: 1; }
    #ad-file-row { height: 3; }
    #ad-file-input { width: 1fr; }
    #ad-file-btn { width: 10; min-width: 10; }
    #ad-left Button { width: 100%; }
    #ad-left Select { margin-bottom: 1; }
    #ad-status { height: 1; margin-top: 1; color: #7A788A; }
    #ad-progress { display: none; height: 1; }
    #ad-progress.busy { display: block; }
    #ad-gauge { height: 5; content-align: center middle; border: round #2E3247;
                background: #1A1D27; margin-top: 1; }
    #ad-cards { height: 4; margin-top: 1; }
    Card { width: 1fr; height: 4; border: round #2E3247; background: #21253A;
           content-align: center middle; margin-right: 1; }
    #ad-dims { border: round #2E3247; background: #1A1D27; padding: 0 1; margin-top: 1; height: auto; }
    .dim-row { height: 1; }
    .dim-name { width: 22; color: #7A788A; }
    #ad-warnings { border: round #F39C12; color: #F39C12; padding: 0 1; margin-top: 1;
                   display: none; height: auto; }
    #ad-warnings.show { display: block; }

    /* Page vérificateur W_J */
    #v-left { width: 46; min-width: 38; background: #1A1D27; padding: 0 1; border-right: heavy #2E3247; }
    #v-left Button { width: 100%; margin-top: 1; }
    #v-left .btn-row Button { width: 1fr; margin-top: 0; }
    .sw-row { height: 3; margin-top: 1; }
    .sw-row Label { margin-top: 1; }
    #v-out { width: 1fr; padding: 0 1; background: #14161F; }
    #v-state { height: auto; margin-top: 1; color: #7A788A; }

    /* Page Flipper W_F */
    #fz-left { width: 46; min-width: 38; background: #1A1D27; padding: 0 1; border-right: heavy #2E3247; }
    #fz-left Button { width: 100%; margin-top: 1; }
    #fz-left .btn-row Button { width: 1fr; min-width: 0; margin-top: 0; }
    #fz-state, #fz-status { height: auto; margin-top: 1; color: #7A788A; }
    #fz-tabs { width: 1fr; height: 1fr; }
    #fz-tabs ContentSwitcher { height: 1fr; }
    #fz-tabs TabPane { height: 1fr; padding: 0 1; }
    #fz-editor { height: 3fr; min-height: 8; border: round #2E3247; margin-bottom: 1; }
    #fz-console, #fz-cli-out { height: 1fr; min-height: 5; border: round #2E3247;
                               background: #14161F; }
    #fz-cli-in { margin-top: 1; }

    /* Boutons rapides W_F */
    QuickPanel { height: 1fr; }
    QuickPanel .qa-scroll { height: 2fr; }
    QuickPanel .qa-title { color: #FF8C42; text-style: bold; margin-top: 1; }
    QuickPanel .qa-grid { layout: grid; grid-size: 3; grid-gutter: 0 1; grid-rows: auto;
                          height: auto; margin-top: 1; }
    QuickPanel .qa-grid Button { width: 100%; min-width: 0; }
    QuickPanel .qa-out { height: 1fr; min-height: 5; border: round #2E3247;
                         background: #14161F; margin-top: 1; }
    QuickPanel Input, QuickPanel Select { margin-top: 1; }
    QuickPanel .btn-row Button { width: 1fr; min-width: 0; }

    /* Page ESP32 W_F */
    #es-left { width: 46; min-width: 38; background: #1A1D27; padding: 0 1; border-right: heavy #2E3247; }
    #es-left Button { width: 100%; margin-top: 1; }
    #es-left .btn-row Button { width: 1fr; min-width: 0; margin-top: 0; }
    #es-left Select, #es-left Input { margin-top: 1; }
    #es-state, #es-status { height: auto; margin-top: 1; color: #7A788A; }
    #es-tabs { width: 1fr; height: 1fr; }
    #es-tabs ContentSwitcher { height: 1fr; }
    #es-tabs TabPane { height: 1fr; padding: 0 1; }
    #es-editor { height: 3fr; min-height: 8; border: round #2E3247; margin-bottom: 1; }
    #es-build, #es-monitor, #es-report { height: 1fr; min-height: 5; border: round #2E3247;
                             background: #14161F; }
    #es-sendbar { height: auto; margin-top: 1; }
    #es-send { width: 1fr; }
    #es-eol { width: 14; margin-left: 1; }
    """

    BINDINGS = [
        Binding("f1", "focus_menu", "Menu"),
        Binding("f5", "ai('analyze')", "Analyser"),
        Binding("f6", "ai('humanize')", "Humaniser"),
        Binding("f7", "ai('refile')", "Reformater"),
        Binding("f8", "ai('export')", "Exporter"),
        Binding("f9", "ai('reset')", "Reset IA"),
        Binding("f2", "hw('open')", "Ouvrir"),
        Binding("f3", "hw('send')", "Envoyer/Compiler"),
        Binding("f4", "hw('run')", "Lancer/Téléverser"),
        Binding("f12", "hw('stop')", "Stop"),
        Binding("ctrl+q", "quit", "Quitter"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="sidebar"):
                yield OptionList(*self._menu_options(), id="menu")
            with ContentSwitcher(initial="home"):
                yield HomePage()
                yield DetectorPage()
                yield VerifPage()
                yield FlipperPage()
                yield ESP32Page()
                for spec in MODULES:
                    yield ModulePage(spec)
        yield Footer()

    @staticmethod
    def _menu_options() -> list[Option]:
        """Construit le menu à partir de MODULES : chaque section porte sa couleur,
        aucun module de l'arborescence ne peut être oublié à l'affichage."""
        def head(t: str, color: str) -> Option:
            return Option(Text(f"── {t} ──", style=f"bold {color}"), disabled=True)

        def opt(s: ModuleSpec) -> Option:
            return Option(f"{s.icon}  {s.title}", id=s.key)

        opts: list[Option] = [Option("🏠  Accueil", id="home")]
        seen: set[str] = set()
        for title, color, prefixes in GROUP_TITLES:
            mods = [s for s in MODULES if any(s.module.startswith(p) for p in prefixes)]
            natives: list[tuple[str, str]] = []
            for p in prefixes:
                natives += NATIVE_PAGES.get(p, [])
            if not mods and not natives:
                continue
            opts.append(head(title, color))
            opts += [Option(label, id=pid) for label, pid in natives]
            opts += [opt(s) for s in mods]
            seen.update(s.module for s in mods)
        # filet de sécurité : tout module non rattaché à une section connue
        leftovers = [s for s in MODULES if s.module not in seen]
        if leftovers:
            opts.append(head("Divers", C_MUTED))
            opts += [opt(s) for s in leftovers]
        return opts

    def on_mount(self) -> None:
        self.query_one("#menu", OptionList).focus()

    # ── Navigation ───────────────────────────────────────────────
    def _switch(self, key: str | None) -> None:
        if key:
            self.query_one(ContentSwitcher).current = key

    @on(OptionList.OptionHighlighted, "#menu")
    def _highlight(self, event: OptionList.OptionHighlighted) -> None:
        self._switch(event.option.id)

    @on(OptionList.OptionSelected, "#menu")
    def _selected(self, event: OptionList.OptionSelected) -> None:
        self._switch(event.option.id)
        page = self.query_one(ContentSwitcher).get_child_by_id(event.option.id)
        for w in page.query("Input, TextArea"):
            if not w.disabled:
                w.focus()
                break

    def action_focus_menu(self) -> None:
        self.query_one("#menu", OptionList).focus()

    def action_ai(self, what: str) -> None:
        """Raccourcis F5-F9 : actifs seulement sur la page du détecteur IA."""
        if self.query_one(ContentSwitcher).current != "p_detect" or AI_ERROR:
            return
        getattr(self.query_one(DetectorPage), f"action_{what}")()

    def action_hw(self, what: str) -> None:
        """Raccourcis F2-F4 / F12 : agissent sur la page Flipper ou ESP32 selon celle affichée."""
        pages = {"p_flipper": (FlipperPage, FLIPPER_ERROR), "p_esp32": (ESP32Page, ESP32_ERROR)}
        page_cls, error = pages.get(self.query_one(ContentSwitcher).current, (None, None))
        if page_cls is None or error:
            return
        getattr(self.query_one(page_cls), f"do_{what}")()

    def on_unmount(self) -> None:
        try:
            fl = self.query_one(FlipperPage).flipper
            if fl is not None:
                fl.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.query_one(ESP32Page).shutdown()
        except Exception:  # noqa: BLE001
            pass
        try:
            eng = self.query_one(VerifPage).engine
            if eng is not None:
                eng.stop_tor()
        except Exception:  # noqa: BLE001
            pass

if __name__ == "__main__":
    WatchFoxApp().run()