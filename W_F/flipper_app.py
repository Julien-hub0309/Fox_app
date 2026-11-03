import json
import threading
import time
from pathlib import Path

from serial.tools import list_ports
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (Button, DirectoryTree, Footer, Header, Input,
                             Label, RichLog, Select, Static, TextArea)

from flipper_ctl import FlipperUSB

REMOTE_DIR = "/ext/apps/Scripts"   # dossier des scripts JS sur la carte SD
QUICK_JS = f"{REMOTE_DIR}/_quick.js"   # fichier temporaire pour les boutons JS
BUTTONS_FILE = Path(__file__).resolve().parent / "flipper_buttons.json"

TEMPLATE = """\
// Script exécuté directement sur le Flipper Zero
print("Hello depuis Python !");
delay(500);
print("Terminé");
"""

# --------------------------------------------------------------------------
# Boutons prêts à l'emploi : (libellé, type, contenu)
#   type "cli" -> liste de commandes CLI ("sleep X" = pause de X secondes)
#   type "js"  -> script JavaScript envoyé puis exécuté sur le Flipper
# Modifie / ajoute ce que tu veux ici, ou crée des boutons depuis l'interface.
# Certaines commandes/API dépendent de la version du firmware.
# --------------------------------------------------------------------------
QUICK_GROUPS = [
    ("📟 Appareil", [
        ("ℹ Infos appareil", "cli", ["device_info"]),
        ("🔋 Batterie", "cli", ["power info"]),
        ("💾 Stockage SD", "cli", ["storage info /ext"]),
        ("📂 Fichiers /ext", "cli", ["storage list /ext"]),
        ("🕒 Date / heure", "cli", ["date"]),
        ("⏱ Uptime", "cli", ["uptime"]),
        ("🧠 Mémoire libre", "cli", ["free"]),
        ("📋 Processus", "cli", ["ps"]),
    ]),
    ("✨ Effets", [
        ("📳 Vibrer", "cli", ["vibro 1", "sleep 0.4", "vibro 0"]),
        ("🔴 LED rouge", "cli", ["led r 255", "led g 0", "led b 0"]),
        ("🟢 LED verte", "cli", ["led r 0", "led g 255", "led b 0"]),
        ("🔵 LED bleue", "cli", ["led r 0", "led g 0", "led b 255"]),
        ("⚫ LED éteinte", "cli", ["led r 0", "led g 0", "led b 0"]),
    ]),
    ("🎮 Télécommande", [
        ("⬆ Haut", "cli", ["input send up short"]),
        ("⬇ Bas", "cli", ["input send down short"]),
        ("⬅ Gauche", "cli", ["input send left short"]),
        ("➡ Droite", "cli", ["input send right short"]),
        ("⏺ OK", "cli", ["input send ok short"]),
        ("↩ Retour", "cli", ["input send back short"]),
    ]),
    ("🚀 Applications", [
        ("📜 Lister les apps", "cli", ["loader list"]),
        ("📡 Ouvrir Sub-GHz", "cli", ['loader open "Sub-GHz"']),
        ("📺 Ouvrir Infrarouge", "cli", ['loader open "Infrared"']),
        ("💳 Ouvrir NFC", "cli", ['loader open "NFC"']),
        ("✖ Fermer l'app", "cli", ["loader close"]),
    ]),
    ("🟨 Scripts JS", [
        ("💬 Hello", "js", 'print("Hello depuis le bouton !");\ndelay(500);\nprint("Fini");\n'),
        ("🔔 Notif succès", "js", 'let notify = require("notification");\nnotify.success();\n'),
        ("🚨 Notif erreur", "js", 'let notify = require("notification");\nnotify.error();\n'),
        ("💡 Clignoter bleu", "js", 'let notify = require("notification");\nnotify.blink("blue", "long");\n'),
    ]),
]


class ActionButton(Button):
    """Bouton qui porte sa propre action (commandes CLI ou script JS)."""

    def __init__(self, title: str, kind: str, payload, custom: bool = False) -> None:
        super().__init__(title, classes="qa")
        self.qa_title = title
        self.qa_kind = kind
        self.qa_payload = payload
        self.qa_custom = custom


class FilePicker(ModalScreen[str | None]):
    """Petit sélecteur de fichier."""
    BINDINGS = [Binding("escape", "dismiss(None)", "Annuler")]
    DEFAULT_CSS = """
    FilePicker { align: center middle; }
    FilePicker > Vertical { width: 70%; height: 80%; border: thick $accent;
                            background: $surface; padding: 1; }
    FilePicker DirectoryTree { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Choisis un fichier .js (Échap pour annuler)")
            yield DirectoryTree(str(Path.cwd()))

    @on(DirectoryTree.FileSelected)
    def picked(self, event: DirectoryTree.FileSelected) -> None:
        self.dismiss(str(event.path))


class FlipperJSApp(App):
    TITLE = "Flipper JS Studio"
    CSS = """
    #topbar, #filebar, #actions { height: auto; padding: 0 1; }
    #topbar > *, #filebar > *, #actions > * { margin-right: 1; }
    #port { width: 28; }
    #status { padding-top: 1; }
    #remote_name { width: 28; }
    #local_path { width: 1fr; }

    #main { height: 1fr; }
    #side { width: 34; border-right: solid $primary; padding: 0 1; }
    #work { width: 1fr; }
    #side Button { width: 100%; }
    #side .qa { height: 1; border: none; min-width: 0; margin: 0; }
    #side .section { text-style: bold; color: $accent; margin-top: 1; }
    #custom { height: auto; }
    #side Input, #side Select { width: 100%; }

    #editor { height: 3fr; border: round $primary; }
    #cli_line { margin: 0 1; }
    #console { height: 2fr; border: round $success; }
    """
    BINDINGS = [
        Binding("f2", "open_file", "Ouvrir"),
        Binding("f5", "send_run", "Envoyer+Exécuter"),
        Binding("f6", "send_only", "Envoyer"),
        Binding("f7", "stop", "Stop"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.flipper: FlipperUSB | None = None
        self.lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.custom: list[dict] = self.load_custom()

    # ---------- boutons personnalisés (persistants) ----------
    @staticmethod
    def load_custom() -> list[dict]:
        try:
            data = json.loads(BUTTONS_FILE.read_text(encoding="utf-8"))
            return [d for d in data if {"label", "type", "value"} <= set(d)]
        except Exception:
            return []

    def save_custom(self) -> None:
        BUTTONS_FILE.write_text(
            json.dumps(self.custom, ensure_ascii=False, indent=2), encoding="utf-8")

    async def rebuild_custom(self) -> None:
        box = self.query_one("#custom", Vertical)
        await box.remove_children()
        buttons = [ActionButton("⭐ " + c["label"], c["type"], c["value"], True)
                   for c in self.custom]
        if buttons:
            await box.mount(*buttons)

    # ---------- interface ----------
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="topbar"):
            yield Select([], prompt="Port série", id="port", allow_blank=True)
            yield Button("↻", id="refresh")
            yield Button("Connecter", id="connect", variant="primary")
            yield Static("● déconnecté", id="status")
        with Horizontal(id="main"):
            with VerticalScroll(id="side"):
                for title, actions in QUICK_GROUPS:
                    yield Label(title, classes="section")
                    for label, kind, payload in actions:
                        yield ActionButton(label, kind, payload)
                yield Label("⭐ Mes boutons", classes="section")
                yield Vertical(id="custom")
                yield Label("➕ Créer un bouton", classes="section")
                yield Input(placeholder="Nom du bouton", id="new_label")
                yield Select([("Commandes CLI", "cli"), ("Script JS", "js")],
                             value="cli", allow_blank=False, id="new_type")
                yield Input(placeholder="cmd1; sleep 1; cmd2  (ou code JS)", id="new_value")
                yield Button("＋ Ajouter", id="add_btn", variant="primary")
                yield Button("＋ Depuis l'éditeur (JS)", id="add_from_editor")
                yield Button("🗑 Supprimer (par nom)", id="del_btn", variant="error")
            with Vertical(id="work"):
                with Horizontal(id="filebar"):
                    yield Button("Ouvrir…", id="open")
                    yield Input(placeholder="Chemin local .js (pour Sauver)", id="local_path")
                    yield Button("Sauver", id="save")
                    yield Input(value="python_script.js", id="remote_name",
                                placeholder="Nom sur le Flipper")
                with Horizontal(id="actions"):
                    yield Button("Envoyer", id="send")
                    yield Button("Envoyer + Exécuter ▶", id="send_run", variant="success")
                    yield Button("■ Stop", id="stop", variant="error")
                try:
                    yield TextArea.code_editor(TEMPLATE, language="javascript", id="editor")
                except Exception:  # tree-sitter absent : pas de coloration
                    yield TextArea.code_editor(TEMPLATE, id="editor")
                yield Input(placeholder="Commande CLI libre du Flipper puis Entrée "
                                        "(ex : storage list /ext)", id="cli_line")
                yield RichLog(id="console", wrap=True, markup=False, highlight=False)
        yield Footer()

    async def on_mount(self) -> None:
        self.refresh_ports()
        await self.rebuild_custom()
        self.log_line("Prêt. Branche le Flipper en USB puis clique sur Connecter.")

    # ---------- utilitaires ----------
    def log_line(self, text: str) -> None:
        self.query_one("#console", RichLog).write(text)

    def log_from_thread(self, text: str) -> None:
        self.call_from_thread(self.query_one("#console", RichLog).write, text)

    def set_status(self, text: str, color: str) -> None:
        self.query_one("#status", Static).update(f"[{color}]{text}[/]")

    def refresh_ports(self) -> None:
        ports = list(list_ports.comports())
        sel = self.query_one("#port", Select)
        sel.set_options([(f"{p.device} - {(p.description or '')[:20]}", p.device)
                         for p in ports])
        for p in ports:
            if (p.vid, p.pid) == (FlipperUSB.VID, FlipperUSB.PID):
                sel.value = p.device

    # ---------- connexion ----------
    @on(Button.Pressed, "#refresh")
    def _refresh(self) -> None:
        self.refresh_ports()

    @on(Button.Pressed, "#connect")
    def toggle_connect(self) -> None:
        btn = self.query_one("#connect", Button)
        if self.flipper:
            with self.lock:
                self.flipper.close()
            self.flipper = None
            btn.label = "Connecter"
            self.set_status("● déconnecté", "red")
            return
        value = self.query_one("#port", Select).value
        port = value if isinstance(value, str) else None
        try:
            self.flipper = FlipperUSB(port)
        except Exception as e:
            self.log_line(f"[ERREUR connexion] {e}")
            return
        btn.label = "Déconnecter"
        self.set_status("● connecté", "green")
        self.log_line("[Connecté au Flipper]")

    # ---------- boutons d'actions rapides ----------
    @on(Button.Pressed)
    def quick_action(self, event: Button.Pressed) -> None:
        btn = event.button
        if not isinstance(btn, ActionButton):
            return
        if not self.flipper:
            self.log_line("[Flipper] Connecte d'abord le Flipper.")
            return
        if btn.qa_kind == "js":
            self.stop_flag.clear()
            self.log_line(f"▶ {btn.qa_title}")
            self.transfer(QUICK_JS, str(btn.qa_payload).encode("utf-8"), True)
        else:
            payload = btn.qa_payload
            cmds = payload if isinstance(payload, list) else [
                c.strip() for c in str(payload).split(";") if c.strip()]
            self.run_cli(btn.qa_title, cmds)

    @on(Input.Submitted, "#cli_line")
    def cli_free(self, event: Input.Submitted) -> None:
        line = event.value.strip()
        if not line:
            return
        if not self.flipper:
            self.log_line("[Flipper] Connecte d'abord le Flipper.")
            return
        event.input.value = ""
        self.run_cli(f"> {line}", [c.strip() for c in line.split(";") if c.strip()])

    @work(thread=True)
    def run_cli(self, title: str, commands: list[str]) -> None:
        if not self.lock.acquire(blocking=False):
            self.log_from_thread("[Occupé] Une opération est en cours (script en exécution ?).")
            return
        try:
            self.log_from_thread(f"▶ {title}")
            for line in commands:
                if line.lower().startswith("sleep "):
                    time.sleep(float(line[6:]))
                    continue
                out = self.flipper.cmd(line, timeout=5)
                if out:
                    self.log_from_thread(out)
            self.log_from_thread("✔ ok")
        except Exception as e:
            self.log_from_thread(f"[ERREUR] {e}")
        finally:
            self.lock.release()

    # ---------- création / suppression de boutons ----------
    async def _add_custom(self, label: str, kind: str, value: str) -> None:
        label, value = label.strip(), value.strip()
        if not label or not value:
            self.log_line("[Bouton] Donne un nom et un contenu.")
            return
        self.custom = [c for c in self.custom if c["label"].lower() != label.lower()]
        self.custom.append({"label": label, "type": kind, "value": value})
        self.save_custom()
        await self.rebuild_custom()
        self.log_line(f"[Bouton « {label} » enregistré]")

    @on(Button.Pressed, "#add_btn")
    async def add_button(self) -> None:
        kind = self.query_one("#new_type", Select).value
        await self._add_custom(self.query_one("#new_label", Input).value,
                               kind if isinstance(kind, str) else "cli",
                               self.query_one("#new_value", Input).value)

    @on(Button.Pressed, "#add_from_editor")
    async def add_from_editor(self) -> None:
        await self._add_custom(self.query_one("#new_label", Input).value, "js",
                               self.query_one("#editor", TextArea).text)

    @on(Button.Pressed, "#del_btn")
    async def delete_button(self) -> None:
        label = self.query_one("#new_label", Input).value.strip().lower()
        before = len(self.custom)
        self.custom = [c for c in self.custom if c["label"].lower() != label]
        if len(self.custom) == before:
            self.log_line("[Supprimer] Aucun bouton à ce nom (tape son nom dans « Nom du bouton »).")
            return
        self.save_custom()
        await self.rebuild_custom()
        self.log_line("[Bouton supprimé]")

    # ---------- fichiers ----------
    @on(Button.Pressed, "#open")
    def action_open_file(self) -> None:
        def loaded(path: str | None) -> None:
            if not path:
                return
            try:
                text = Path(path).read_text(encoding="utf-8")
            except Exception as e:
                self.log_line(f"[ERREUR lecture] {e}")
                return
            self.query_one("#editor", TextArea).load_text(text)
            self.query_one("#local_path", Input).value = path
            self.query_one("#remote_name", Input).value = Path(path).name
            self.log_line(f"[Chargé] {path}")
        self.push_screen(FilePicker(), loaded)

    @on(Button.Pressed, "#save")
    def save_local(self) -> None:
        path = self.query_one("#local_path", Input).value.strip()
        if not path:
            self.log_line("[Sauver] Indique d'abord un chemin local.")
            return
        try:
            Path(path).write_text(self.query_one("#editor", TextArea).text, encoding="utf-8")
            self.log_line(f"[Sauvegardé] {path}")
        except Exception as e:
            self.log_line(f"[ERREUR sauvegarde] {e}")

    @on(Button.Pressed, "#send")
    def action_send_only(self) -> None:
        self.start_send(run=False)

    @on(Button.Pressed, "#send_run")
    def action_send_run(self) -> None:
        self.start_send(run=True)

    @on(Button.Pressed, "#stop")
    def action_stop(self) -> None:
        self.stop_flag.set()

    # ---------- envoi / exécution ----------
    def start_send(self, run: bool) -> None:
        if not self.flipper:
            self.log_line("[Flipper] Connecte d'abord le Flipper.")
            return
        name = self.query_one("#remote_name", Input).value.strip().replace("/", "_")
        name = name or "python_script.js"
        if not name.endswith(".js"):
            name += ".js"
        data = self.query_one("#editor", TextArea).text.encode("utf-8")
        self.stop_flag.clear()
        self.transfer(f"{REMOTE_DIR}/{name}", data, run)

    @work(thread=True)
    def transfer(self, remote: str, data: bytes, run: bool) -> None:
        with self.lock:
            try:
                self.log_from_thread(f"[Envoi de {len(data)} octets vers {remote}]")
                self.flipper.upload(remote, data)
                self.log_from_thread("[Envoi OK]")
                if run:
                    self.log_from_thread("[Exécution]")
                    self.flipper.run_js_stream(
                        remote, lambda t: self.log_from_thread(t.rstrip("\n")),
                        self.stop_flag.is_set)
                    self.log_from_thread("[Fin]")
            except Exception as e:
                self.log_from_thread(f"[ERREUR] {e}")


if __name__ == "__main__":
    FlipperJSApp().run()