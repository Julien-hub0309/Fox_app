#!/usr/bin/env python3
"""
Watch Fox – Intelligence & Investigation Framework
Interface terminal (Textual) : un menu à gauche, une page par module à droite.

Arborescence attendue :
    main.py
    utile/display.py
    W_A/{detecteur,anti_detecteur,refile}.py     -> page native "Détecteur IA / Humaniser / Reformater"
    W_S/idee.py                                  -> page native "Vérificateur d'informations"
    W_F/{phone,web,mail,pseudo,scan,sniffeur,password,info,profileur,danger,meta,ia}.py
                                                 -> pages génériques (exécution dans le vrai terminal)
"""
from __future__ import annotations

import builtins
import glob
import importlib
import importlib.util
import io
import json
import sys
import threading
import traceback
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

# ── Chemins ──────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
for p in (ROOT, ROOT / "W_A", ROOT / "W_S", ROOT / "W_F"):  # sous-dossiers en repli (imports "à plat")
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
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button, ContentSwitcher, Footer, Header, Input, Label, OptionList,
    ProgressBar, RichLog, Select, Static, Switch, TextArea,
)
from textual.widgets.option_list import Option

try:
    from utile.display import console as term_console, get_hostname, get_public_ip
except ModuleNotFoundError as exc:
    print(f"[ERREUR] utile/display.py introuvable ({exc}).")
    sys.exit(1)

# ── Imports W_A (page native) ────────────────────────────────────
AI_ERROR: Exception | None = None
STYLE_LABELS: dict = {}
try:
    from W_A.detecteur import analyze_text, AnalysisResult
    from W_A.anti_detecteur import MetadataCleaner
    from W_A.refile import TextReformatter, STYLE_LABELS
except Exception as exc:  # noqa: BLE001
    AI_ERROR = exc

# ── Imports W_S (page native) ────────────────────────────────────
VERIF_ERROR: Exception | None = None
STEM_AVAILABLE = False
try:
    from W_S.idee import TorSearchEngine, STEM_AVAILABLE
except Exception as exc:  # noqa: BLE001
    VERIF_ERROR = exc

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
#  Spécification des modules W_F (pages génériques)
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


TARGET = [FieldSpec("target", "Cible")]

MODULES: list[ModuleSpec] = [
    ModuleSpec("p_phone", "📱", "Téléphone", "Analyse OSINT d'un numéro de téléphone.", "W_F.phone",
               _simple("PhonyNode", "run_scan", "target"), [FieldSpec("target", "Numéro", "+33612345678")]),
    ModuleSpec("p_web", "🌐", "Web / IP", "Analyse d'infrastructure d'un domaine ou d'une IP.", "W_F.web",
               _simple("WebScanner", "scan_infra", "target"), [FieldSpec("target", "Domaine / IP", "example.com")]),
    ModuleSpec("p_mail", "📧", "Email", "Recherche OSINT sur une adresse email.", "W_F.mail",
               _simple("EmailOSINT", "run_scan", "target"), [FieldSpec("target", "Adresse email", "nom@domaine.com")]),
    ModuleSpec("p_pseudo", "👤", "Pseudo / Username", "Recherche d'un pseudo sur les réseaux.", "W_F.pseudo",
               _simple("UsernameOSINT", "run_scan", "target"), [FieldSpec("target", "Pseudo")]),
    ModuleSpec("p_scan", "📡", "Scan de ports", "Scan réseau d'une cible.", "W_F.scan",
               _simple("NetworkScanner", "run_scan", "target"), [FieldSpec("target", "IP / Hôte", "192.168.1.1")]),
    ModuleSpec("p_sniff", "🔍", "Sniffeur réseau", "Capture / analyse de trafic.", "W_F.sniffeur",
               _simple("NetworkSniffer", "run_scan", "target"), [FieldSpec("target", "Cible / interface")]),
    ModuleSpec("p_pass", "🔑", "Testeur de mot de passe", "Analyse de la robustesse d'un mot de passe "
               "(le module vous demandera la saisie en bas de page).", "W_F.password",
               _simple("PasswordAnalyzer", "run_scan")),
    ModuleSpec("p_info", "📋", "Devis système", "Informations matérielles de la machine.", "W_F.info",
               _simple("SystemDevis", "run_scan")),
    ModuleSpec("p_profil", "🕵️", "Profilage (Nom/Prénom)", "Recherche de profil à partir d'une identité.", "W_F.profileur",
               _profileur, [FieldSpec("nom", "NOM"), FieldSpec("prenom", "PRÉNOM"),
                            FieldSpec("age", "ÂGE (optionnel)", required=False)]),
    ModuleSpec("p_url", "🛡️", "Vérifier une URL", "Analyse de dangerosité (VirusTotal).", "W_F.danger",
               _simple("URLAnalyzer", "run_scan", "target"), [FieldSpec("target", "URL", "https://…")]),
    ModuleSpec("p_meta", "📂", "Métadonnées", "Extraction de métadonnées (image / document).", "W_F.meta",
               _simple("MetadataExtractor", "run_scan", "target"), [FieldSpec("target", "Chemin du fichier")]),
    ModuleSpec("p_ia", "🤖", "Détecteur de texte IA (fichier)", "Détection IA sur un fichier (module W_F.ia).", "W_F.ia",
               _simple("IADetector", "run_scan", "target"), [FieldSpec("target", "Chemin du fichier")]),
]


# ═════════════════════════════════════════════════════════════════
#  Page générique pour les modules W_F
# ═════════════════════════════════════════════════════════════════
class ModulePage(Vertical):
    """Page d'un module W_F : saisie des paramètres, puis exécution dans le vrai terminal
    (l'interface Textual est suspendue le temps du module, comme dans l'ancien menu CLI)."""

    def __init__(self, spec: ModuleSpec) -> None:
        super().__init__(id=spec.key)
        self.spec = spec

    def compose(self) -> ComposeResult:
        s = self.spec
        yield Label(f"{s.icon}  {s.title}", classes="page-title")
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
            term_console.print(Rule(f"{self.spec.icon}  {self.spec.title}", style="orange1"))
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
#  Page native W_A : détecteur IA / humanisation / reformatage
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
            yield Static(Text(f"Module W_A indisponible : {AI_ERROR}", style=C_RED))
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
            from W_A.detecteur import _read_txt, _read_pdf, _read_docx
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
#  Page native W_S : vérificateur d'informations (recherche / Tor)
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
#  Page d'accueil
# ═════════════════════════════════════════════════════════════════
class HomePage(VerticalScroll):
    def __init__(self) -> None:
        super().__init__(id="home")

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
        self.query_one("#home-help", Static).update(help_)
        self._fetch_info()

    @work(thread=True)
    def _fetch_info(self) -> None:
        host, ip = get_hostname(), get_public_ip()
        self.app.call_from_thread(self._render_banner, host, ip)

    def _render_banner(self, host: str, ip: str) -> None:
        body = (
            "[bold cyan]🦊 Watch Fox 🦊[/bold cyan]\n"
            "[dim]Intelligence & Investigation Framework[/dim]\n"
            "──────────────────────────────────────────\n"
            f"[bold magenta]Device :[/bold magenta] [white]{escape(host)}[/white]\n"
            f"[bold magenta]IPv4   :[/bold magenta] [white]{escape(ip)}[/white]"
        )
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

    /* Pages génériques W_F */
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

    /* Page vérificateur W_S */
    #v-left { width: 46; min-width: 38; background: #1A1D27; padding: 0 1; border-right: heavy #2E3247; }
    #v-left Button { width: 100%; margin-top: 1; }
    #v-left .btn-row Button { width: 1fr; margin-top: 0; }
    .sw-row { height: 3; margin-top: 1; }
    .sw-row Label { margin-top: 1; }
    #v-out { width: 1fr; padding: 0 1; background: #14161F; }
    #v-state { height: auto; margin-top: 1; color: #7A788A; }
    """

    BINDINGS = [
        Binding("f1", "focus_menu", "Menu"),
        Binding("f5", "ai('analyze')", "Analyser"),
        Binding("f6", "ai('humanize')", "Humaniser"),
        Binding("f7", "ai('refile')", "Reformater"),
        Binding("f8", "ai('export')", "Exporter"),
        Binding("f9", "ai('reset')", "Reset IA"),
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
                for spec in MODULES:
                    yield ModulePage(spec)
        yield Footer()

    @staticmethod
    def _menu_options() -> list[Option]:
        def head(t: str) -> Option:
            return Option(Text(f"── {t} ──", style=f"bold {C_MUTED}"), disabled=True)

        opts = [Option("🏠  Accueil", id="home"),
                head("W_A · Texte IA"),
                Option("🧠  Détecteur / Humaniser / Reformater", id="p_detect"),
                head("W_S · Vérification"),
                Option("📰  Vérificateur d'informations", id="p_verif"),
                head("W_F · OSINT & Réseau")]
        opts += [Option(f"{s.icon}  {s.title}", id=s.key) for s in MODULES]
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

    def on_unmount(self) -> None:
        try:
            eng = self.query_one(VerifPage).engine
            if eng is not None:
                eng.stop_tor()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    WatchFoxApp().run()