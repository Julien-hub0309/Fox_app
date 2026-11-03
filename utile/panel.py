from __future__ import annotations

import json
import threading
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (Button, DirectoryTree, Input, Label, RichLog,
                             Select, Static, TextArea)

COLORS = {"good": "green", "warn": "orange1", "bad": "red", "info": "cyan",
          "muted": "grey58"}


# ════════════════════════════════════════════════════════════════
#  Modèle de données
# ════════════════════════════════════════════════════════════════
@dataclass
class Row:
    label: str
    percent: float | None = None      # None -> pas de barre, juste le texte
    text: str = ""
    level: str = "good"               # good | warn | bad | info


@dataclass
class ModuleResult:
    main: str = "—"                   # grosse valeur de la carte principale
    suffix: str = ""                  # ex. "/100", "bits", "profils"
    percent: float | None = None      # barre de la carte principale
    caption: str = ""                 # ligne sous la barre
    level: str = "info"               # couleur de la carte principale
    cards: list[tuple[str, str]] = field(default_factory=list)   # 3 cartes
    detail_title: str = "DÉTAIL"
    rows: list[Row] = field(default_factory=list)
    data: dict = field(default_factory=dict)       # contenu de l'export JSON
    log: list[str] = field(default_factory=list)   # lignes ajoutées au journal
    set_fields: dict[str, str] = field(default_factory=dict)  # remplit des champs
    silent: bool = False              # True = ne touche pas aux cartes/détail
    error: str | None = None


@dataclass
class Field:
    id: str
    label: str = ""
    kind: str = "input"               # input | text | select
    placeholder: str = ""
    value: str = ""
    options: list[tuple[str, str]] = field(default_factory=list)
    password: bool = False


@dataclass
class Action:
    id: str
    label: str
    fn: Callable[[dict, Callable[[str], None]], ModuleResult | str | None]
    variant: str = "default"          # default | primary | success | error
    section: str = ""                 # titre au-dessus (ex. HUMANISATION)
    fields: list[Field] = field(default_factory=list)  # champs propres à l'action


@dataclass
class ModuleSpec:
    key: str
    title: str
    icon: str
    fields: list[Field]
    actions: list[Action]             # actions[0] = bouton principal (F5)
    export_name: str = "resultat.json"
    idle_main: str = "—"
    idle_suffix: str = ""
    idle_caption: str = "En attente…"
    detail_title: str = "DÉTAIL"
    open_mode: str | None = None      # None | "text" | "path"
    open_exts: tuple = ()
    file_reader: Callable[[Path], str] | None = None
    card_titles: tuple = ("RÉSULTAT", "INFO", "STATUT")


# ════════════════════════════════════════════════════════════════
#  Capture de la sortie console / print des modules existants
# ════════════════════════════════════════════════════════════════
class LineSink:
    encoding = "utf-8"

    def __init__(self, cb: Callable[[str], None]) -> None:
        self.cb, self.buf = cb, ""

    def write(self, s: str) -> int:
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if line.strip():
                self.cb(line)
        return len(s)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False

    def close_out(self) -> None:
        if self.buf.strip():
            self.cb(self.buf)
        self.buf = ""


_CAP_LOCK = threading.Lock()


@contextmanager
def capture_output(cb: Callable[[str], None]):
    """Redirige `console` (rich) et `print` vers le journal du panneau."""
    sink = LineSink(cb)
    try:
        from utile.display import console
    except Exception:
        console = None
    with _CAP_LOCK:
        old_file = old_width = None
        if console is not None:
            old_file, old_width = console.file, getattr(console, "_width", None)
            console.file = sink
            console.width = 110
        try:
            with redirect_stdout(sink):
                yield
        finally:
            sink.close_out()
            if console is not None:
                console.file = old_file
                console._width = old_width


# ════════════════════════════════════════════════════════════════
#  Rendu (barres / cartes)
# ════════════════════════════════════════════════════════════════
def bar(pct: float, width: int, color: str) -> Text:
    pct = max(0.0, min(100.0, pct))
    n = round(width * pct / 100)
    t = Text("█" * n, style=color)
    t.append("░" * (width - n), style="grey27")
    return t


class FilePicker(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "dismiss(None)", "Annuler")]
    DEFAULT_CSS = """
    FilePicker { align: center middle; }
    FilePicker > Vertical { width: 70%; height: 80%; border: thick $accent;
                            background: $surface; padding: 1; }
    FilePicker DirectoryTree { height: 1fr; }
    """

    def __init__(self, exts: tuple = ()) -> None:
        super().__init__()
        self.exts = exts

    def compose(self) -> ComposeResult:
        class _Tree(DirectoryTree):
            exts = self.exts

            def filter_paths(self, paths):
                return [p for p in paths if not p.name.startswith(".")
                        and (p.is_dir() or not self.exts
                             or p.suffix.lower() in self.exts)]
        with Vertical():
            yield Label("Choisis un fichier (Échap pour annuler)")
            yield _Tree(str(Path.cwd()))

    @on(DirectoryTree.FileSelected)
    def picked(self, event: DirectoryTree.FileSelected) -> None:
        self.dismiss(str(event.path))


# ════════════════════════════════════════════════════════════════
#  Le panneau
# ════════════════════════════════════════════════════════════════
class ModulePanel(Horizontal):
    BINDINGS = [
        Binding("f5", "analyse", "Analyser"),
        Binding("f8", "export", "Exporter"),
        Binding("f9", "reset", "Reset"),
        Binding("f2", "open_file", "Ouvrir"),
    ]
    DEFAULT_CSS = """
    ModulePanel { height: 1fr; }
    ModulePanel #left { width: 38; padding: 0 1; border-right: tall #1c2740; }
    ModulePanel #right { width: 1fr; padding: 0 1; }
    ModulePanel .sect { color: $text-muted; text-style: bold; margin-top: 1; }
    ModulePanel #left Button { width: 100%; margin-top: 1; }
    ModulePanel TextArea.field { height: 14; }
    ModulePanel #hero { height: auto; border: round #243252; background: #101a30;
                        padding: 1 2; margin-top: 1; }
    ModulePanel #cards { height: auto; margin-top: 1; }
    ModulePanel .card { width: 1fr; height: 4; border: round #243252;
                        background: #101a30; content-align: center middle;
                        text-align: center; margin-right: 1; }
    ModulePanel #detail { height: auto; max-height: 16; border: round #243252;
                          background: #101a30; padding: 1 2; margin-top: 1;
                          overflow-y: auto; }
    ModulePanel #export_name { margin-top: 0; }
    ModulePanel #journal { height: 1fr; min-height: 5; border: round #1d3b2a;
                           margin-top: 1; }
    """

    def __init__(self, spec: ModuleSpec, **kw) -> None:
        super().__init__(**kw)
        self.spec = spec
        self.busy = False
        self.last: ModuleResult | None = None
        self.all_fields = list(spec.fields) + [f for a in spec.actions for f in a.fields]

    # ---------- composition ----------
    def _make(self, f: Field):
        wid = f"f_{f.id}"
        if f.kind == "text":
            ta = TextArea(f.value, id=wid, classes="field")
            return ta
        if f.kind == "select":
            return Select(f.options, value=f.value or f.options[0][1],
                          allow_blank=False, id=wid)
        return Input(value=f.value, placeholder=f.placeholder,
                     password=f.password, id=wid)

    def compose(self) -> ComposeResult:
        s = self.spec
        with VerticalScroll(id="left"):
            for f in s.fields:
                if f.label:
                    yield Label(f.label.upper(), classes="sect")
                yield self._make(f)
            if s.open_mode:
                yield Button("Ouvrir", id="open")
            first = s.actions[0]
            yield Button(first.label, id=f"act_{first.id}", variant="primary")
            for f in first.fields:
                yield Label(f.label.upper(), classes="sect")
                yield self._make(f)
            for a in s.actions[1:]:
                if a.section:
                    yield Label(a.section.upper(), classes="sect")
                for f in a.fields:
                    yield self._make(f)
                yield Button(a.label, id=f"act_{a.id}",
                             variant=a.variant if a.variant != "default" else "default")
        with VerticalScroll(id="right"):
            yield Static(id="hero", markup=False)
            with Horizontal(id="cards"):
                for i in range(3):
                    yield Static(id=f"card{i}", classes="card", markup=False)
            yield Static(id="detail", markup=False)
            yield Label("EXPORT JSON", classes="sect")
            yield Input(value=s.export_name, id="export_name")
            yield Label("JOURNAL", classes="sect")
            yield RichLog(id="journal", wrap=True, markup=False, highlight=False)

    def on_mount(self) -> None:
        self.show_idle()

    # ---------- affichage ----------
    def show_idle(self) -> None:
        s = self.spec
        self.last = None
        self._hero(ModuleResult(main=s.idle_main, suffix=s.idle_suffix,
                                caption=s.idle_caption, level="muted"))
        self._cards([(t, "—") for t in s.card_titles])
        self._detail(s.detail_title, [])

    def _hero(self, r: ModuleResult) -> None:
        color = COLORS.get(r.level, "cyan")
        t = Text()
        t.append(r.main, style=f"bold {color}")
        if r.suffix:
            t.append(f" {r.suffix}", style="grey58")
        if r.percent is not None:
            t.append("\n")
            t.append_text(bar(r.percent, 44, color))
            t.append(f"  {r.percent:.0f}%", style=color)
        if r.caption:
            t.append(f"\n{r.caption}", style="grey58")
        self.query_one("#hero", Static).update(t)

    def _cards(self, cards: list[tuple[str, str]]) -> None:
        cards = (list(cards) + [("", "")] * 3)[:3]
        for i, (title, value) in enumerate(cards):
            t = Text(justify="center")
            t.append(title.upper(), style="grey58")
            t.append(f"\n{value}", style="bold")
            self.query_one(f"#card{i}", Static).update(t)

    def _detail(self, title: str, rows: list[Row]) -> None:
        t = Text()
        t.append(title.upper(), style="bold")
        for r in rows[:300]:
            color = COLORS.get(r.level, "green")
            t.append(f"\n{r.label[:26]:<26} ", style="grey62")
            if r.percent is not None:
                t.append_text(bar(r.percent, 20, color))
                t.append(f" {r.percent:>3.0f}%", style=color)
            if r.text:
                t.append(f"  {r.text}", style="white" if r.percent is None else "grey58")
        self.query_one("#detail", Static).update(t)

    def log_line(self, line: str | Text) -> None:
        if isinstance(line, str):
            line = Text.from_ansi(line)
        self.query_one("#journal", RichLog).write(line)

    # ---------- champs ----------
    def collect(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for f in self.all_fields:
            w = self.query_one(f"#f_{f.id}")
            out[f.id] = w.text if isinstance(w, TextArea) else str(w.value or "")
        return out

    def set_field(self, fid: str, value: str) -> None:
        w = self.query_one(f"#f_{fid}")
        if isinstance(w, TextArea):
            w.load_text(value)
        else:
            w.value = value

    # ---------- exécution ----------
    @on(Button.Pressed)
    def _pressed(self, ev: Button.Pressed) -> None:
        bid = ev.button.id or ""
        if bid == "open":
            self.action_open_file()
        elif bid.startswith("act_"):
            act = next((a for a in self.spec.actions if f"act_{a.id}" == bid), None)
            if act:
                self.run_action(act)

    def action_analyse(self) -> None:
        self.run_action(self.spec.actions[0])

    def run_action(self, act: Action) -> None:
        if self.busy:
            self.log_line("[…] Une tâche est déjà en cours.")
            return
        self.busy = True
        self.query_one("#hero", Static).update(
            Text.assemble(("Traitement en cours… ", "orange1"), (act.label, "grey58")))
        self._worker(act, self.collect())

    @work(thread=True)
    def _worker(self, act: Action, inputs: dict) -> None:
        call = self.app.call_from_thread
        try:
            with capture_output(lambda l: call(self.log_line, l)):
                res = act.fn(inputs, lambda l: call(self.log_line, l))
        except Exception as e:                      # noqa: BLE001
            res = ModuleResult(error=f"{type(e).__name__}: {e}")
        call(self._finish, res)

    def _finish(self, res: Any) -> None:
        self.busy = False
        if isinstance(res, str) or res is None:
            res = ModuleResult(silent=True, log=[res] if res else [])
        for l in res.log:
            self.log_line(l)
        for fid, val in res.set_fields.items():
            self.set_field(fid, val)
        if res.error:
            self._hero(ModuleResult(main="Erreur", caption=res.error, level="bad"))
            self.log_line(Text(f"[ERREUR] {res.error}", style="red"))
            return
        if res.silent:
            self._restore_hero()
            return
        self.last = res
        self._hero(res)
        self._cards(res.cards or [(t, "—") for t in self.spec.card_titles])
        self._detail(res.detail_title or self.spec.detail_title, res.rows)

    def _restore_hero(self) -> None:
        if self.last:
            self._hero(self.last)
        else:
            self.show_idle()

    # ---------- fichiers ----------
    def action_open_file(self) -> None:
        s = self.spec
        if not s.open_mode:
            return

        def loaded(path: str | None) -> None:
            if not path:
                return
            first = s.fields[0]
            if s.open_mode == "path":
                self.set_field(first.id, path)
            else:
                try:
                    text = (s.file_reader(Path(path)) if s.file_reader
                            else Path(path).read_text(encoding="utf-8", errors="replace"))
                except Exception as e:             # noqa: BLE001
                    self.log_line(f"[ERREUR lecture] {e}")
                    return
                self.set_field(first.id, text)
            self.log_line(f"[Chargé] {path}")
        self.app.push_screen(FilePicker(s.open_exts), loaded)

    # ---------- export / reset ----------
    @on(Input.Submitted, "#export_name")
    def _export_enter(self) -> None:
        self.action_export()

    def action_export(self) -> None:
        if not self.last or not self.last.data:
            self.log_line("[Export] Rien à exporter : lance d'abord une analyse.")
            return
        name = self.query_one("#export_name", Input).value.strip() or self.spec.export_name
        try:
            Path(name).write_text(
                json.dumps(self.last.data, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8")
            self.log_line(f"[Exporté] {Path(name).resolve()}")
        except Exception as e:                      # noqa: BLE001
            self.log_line(f"[ERREUR export] {e}")

    def action_reset(self) -> None:
        for f in self.spec.fields:
            if f.kind != "select":
                self.set_field(f.id, f.value)
        self.query_one("#journal", RichLog).clear()
        self.show_idle()