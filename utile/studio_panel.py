import importlib.util
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import serial
from rich.text import Text
from serial.tools import list_ports
from textual import on, work
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.app import ComposeResult
from textual.widgets import (Button, DirectoryTree, Input, Label, RichLog, Select,
                             Static, Switch, TabbedContent, TabPane, TextArea)

try:
    from modules.flipper_ctl import FlipperUSB
except ImportError:                      # flipper_ctl.py à la racine
    from flipper_ctl import FlipperUSB


# ═══════════════════════════ FLIPPER ═══════════════════════════
REMOTE_DIR = "/ext/apps/Scripts"   # dossier des scripts JS sur la carte SD

TEMPLATE = """\
// Script exécuté directement sur le Flipper Zero
print("Hello depuis Python !");
delay(500);
print("Terminé");
"""


class JSFilePicker(ModalScreen[str | None]):
    """Petit sélecteur de fichier."""
    BINDINGS = [Binding("escape", "dismiss(None)", "Annuler")]
    DEFAULT_CSS = """
    JSFilePicker { align: center middle; }
    JSFilePicker > Vertical { width: 70%; height: 80%; border: thick $accent;
                            background: $surface; padding: 1; }
    JSFilePicker DirectoryTree { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Choisis un fichier .js (Échap pour annuler)")
            yield DirectoryTree(str(Path.cwd()))

    @on(DirectoryTree.FileSelected)
    def picked(self, event: DirectoryTree.FileSelected) -> None:
        self.dismiss(str(event.path))


class FlipperPanel(Vertical):
    DEFAULT_CSS = """
    FlipperPanel { height: 1fr; padding: 0 1; }
    #topbar, #filebar, #actions { height: auto; padding: 0 1; }
    #topbar > *, #filebar > *, #actions > * { margin-right: 1; }
    #port { width: 28; }
    #status { padding-top: 1; }
    #remote_name { width: 28; }
    #local_path { width: 1fr; }
    #editor { height: 3fr; border: round #243252; }
    #console { height: 1fr; border: round #1d3b2a; }
    """
    BINDINGS = [
        Binding("f2", "open_file", "Ouvrir"),
        Binding("f5", "send_run", "Envoyer+Exécuter"),
        Binding("f6", "send_only", "Envoyer"),
        Binding("f7", "stop", "Stop"),
    ]

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.flipper: FlipperUSB | None = None
        self._io_lock = threading.Lock()
        self.stop_flag = threading.Event()

    # ---------- interface ----------
    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Select([], prompt="Port série", id="port", allow_blank=True)
            yield Button("↻", id="refresh")
            yield Button("Connecter", id="connect", variant="primary")
            yield Static("● déconnecté", id="status")
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
        yield RichLog(id="console", wrap=True, markup=False, highlight=False)

    def action_analyse(self) -> None:
        self.action_send_run()

    def on_mount(self) -> None:
        self.refresh_ports()
        self.log_line("Prêt. Branche le Flipper en USB puis clique sur Connecter.")

    # ---------- utilitaires ----------
    def log_line(self, text: str) -> None:
        self.query_one("#console", RichLog).write(text)

    def log_from_thread(self, text: str) -> None:
        self.app.call_from_thread(self.query_one("#console", RichLog).write, text)

    def set_status(self, text: str, color: str) -> None:
        self.query_one("#status", Static).update(f"[{color}]{text}[/]")

    def refresh_ports(self) -> None:
        ports = list(list_ports.comports())
        sel = self.query_one("#port", Select)
        sel.set_options([(f"{p.device} - {p.description[:20]}", p.device) for p in ports])
        for p in ports:
            if (p.vid, p.pid) == (FlipperUSB.VID, FlipperUSB.PID):
                sel.value = p.device

    # ---------- boutons ----------
    @on(Button.Pressed, "#refresh")
    def _refresh(self) -> None:
        self.refresh_ports()

    @on(Button.Pressed, "#connect")
    def toggle_connect(self) -> None:
        btn = self.query_one("#connect", Button)
        if self.flipper:
            with self._io_lock:
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
        self.app.push_screen(JSFilePicker(), loaded)

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
        with self._io_lock:
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




# ═══════════════════════════ ESP32 ═══════════════════════════
BUILD_DIR = Path(__file__).resolve().parent / "esp32_build"   # sketches générés
ESP32_INDEX_URL = "https://espressif.github.io/arduino-esp32/package_esp32_index.json"
FLASH_BAUD = 460800          # baisse à 115200 si le flash échoue via le pont du Flipper
ESPRESSIF_VID = 0x303A       # USB natif ESP32-S2/S3/C3
FLIPPER_VID_PID = (0x0483, 0x5740)

BOARDS = [
    ("ESP32-S2 · Flipper WiFi Dev Board", "esp32:esp32:esp32s2"),
    ("ESP32 (classique)", "esp32:esp32:esp32"),
    ("ESP32-S3", "esp32:esp32:esp32s3"),
    ("ESP32-C3", "esp32:esp32:esp32c3"),
]
BAUDS = [9600, 115200, 230400, 460800, 921600]
EOLS = [("CR+LF", "\r\n"), ("LF", "\n"), ("CR", "\r"), ("Aucun", "")]

OK, WARN, ERR, MUTED, CYAN = "green", "orange1", "red", "grey58", "cyan"
PCT = re.compile(r"\((\d+)\s?%\)")     # progression esptool : on n'affiche que tous les 10 %

TEMPLATE = """\
// Sketch Arduino (C/C++) pour ESP32
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


class ExtTree(DirectoryTree):
    """Arbre de fichiers limité aux dossiers et aux extensions voulues."""
    exts: tuple = ()

    def filter_paths(self, paths):
        return [p for p in paths if not p.name.startswith(".")
                and (p.is_dir() or p.suffix.lower() in self.exts)]


class ESPFilePicker(ModalScreen[str | None]):
    """Petit sélecteur de fichier."""
    BINDINGS = [Binding("escape", "dismiss(None)", "Annuler")]
    DEFAULT_CSS = """
    FilePicker { align: center middle; }
    FilePicker > Vertical { width: 70%; height: 80%; border: thick $accent;
                            background: $surface; padding: 1; }
    FilePicker DirectoryTree { height: 1fr; }
    """

    def __init__(self, exts: tuple, label: str) -> None:
        super().__init__()
        self.exts, self.label = exts, label

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"{self.label} (Échap pour annuler)")
            tree = ExtTree(str(Path.cwd()))
            tree.exts = self.exts
            yield tree

    @on(DirectoryTree.FileSelected)
    def picked(self, event: DirectoryTree.FileSelected) -> None:
        self.dismiss(str(event.path))


class ESP32Panel(Vertical):
    DEFAULT_CSS = """
    ESP32Panel { height: 1fr; padding: 0 1; }
    #topbar, #boardbar, #filebar, #actions, #flashbar, #sendbar { height: auto; padding: 0 1; }
    #topbar > *, #boardbar > *, #filebar > *, #actions > *, #flashbar > *,
    #sendbar > * { margin-right: 1; }
    #port { width: 34; }
    #baud { width: 14; }
    #status { padding-top: 1; }
    #board { width: 38; }
    #cdc_label { padding-top: 1; }
    #sketch_name { width: 22; }
    #local_path, #bin_path, #send_line { width: 1fr; }
    #bin_addr { width: 14; }
    #eol { width: 14; }
    #editor { height: 3fr; border: round #243252; }
    #tabs { height: 2fr; }
    #tabs TabPane { padding: 0; height: 1fr; }
    #build, #monitor { height: 1fr; border: round #1d3b2a; }
    """
    BINDINGS = [
        Binding("f2", "open_file", "Ouvrir"),
        Binding("f5", "upload", "Téléverser"),
        Binding("f6", "compile", "Compiler"),
        Binding("f7", "stop", "Stop"),
    ]

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.ser: serial.Serial | None = None
        self.reader_stop = threading.Event()
        self.stop_flag = threading.Event()
        self.proc: subprocess.Popen | None = None
        self.busy = False

    # ---------- interface ----------
    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Select([], prompt="Port série", id="port", allow_blank=True)
            yield Select([(str(b), b) for b in BAUDS], value=115200,
                         allow_blank=False, id="baud")
            yield Button("↻", id="refresh")
            yield Button("Connecter", id="connect", variant="primary")
            yield Static("● déconnecté", id="status")
        with Horizontal(id="boardbar"):
            yield Select(BOARDS, value=BOARDS[0][1], allow_blank=False, id="board")
            yield Switch(value=True, id="cdc")
            yield Label("Serial via USB (CDC)", id="cdc_label")
            yield Input(value="sketch", placeholder="Nom du sketch", id="sketch_name")
        with Horizontal(id="filebar"):
            yield Button("Ouvrir…", id="open")
            yield Input(placeholder="Chemin local .ino/.c/.cpp (pour Sauver)", id="local_path")
            yield Button("Sauver", id="save")
        with Horizontal(id="actions"):
            yield Button("Compiler", id="compile")
            yield Button("Téléverser ▶", id="upload", variant="success")
            yield Button("Installer core ESP32", id="core")
            yield Button("■ Stop", id="stop", variant="error")
        with Horizontal(id="flashbar"):
            yield Button("Choisir .bin…", id="open_bin")
            yield Input(placeholder="Firmware .bin à flasher", id="bin_path")
            yield Input(value="0x10000", id="bin_addr")
            yield Button("Flasher .bin", id="flash_bin", variant="warning")
        try:
            yield TextArea.code_editor(TEMPLATE, language="cpp", id="editor")
        except Exception:  # langage non disponible : pas de coloration
            yield TextArea.code_editor(TEMPLATE, id="editor")
        with TabbedContent(id="tabs"):
            with TabPane("Build", id="tab_build"):
                yield RichLog(id="build", wrap=True, markup=False, highlight=False)
            with TabPane("Moniteur série", id="tab_mon"):
                yield RichLog(id="monitor", wrap=True, markup=False, highlight=False)
                with Horizontal(id="sendbar"):
                    yield Input(placeholder="Envoyer une ligne à l'ESP32…", id="send_line")
                    yield Select(EOLS, value="\r\n", allow_blank=False, id="eol")

    def action_analyse(self) -> None:
        self.action_upload()

    def on_mount(self) -> None:
        self.refresh_ports()
        self.build_line("Prêt. Branche l'ESP32 (USB-C direct ou via le Flipper en "
                        "« USB-UART Bridge »), choisis le port puis Connecter.", MUTED)

    # ---------- utilitaires ----------
    def build_line(self, text: str, color: str | None = None) -> None:
        self.query_one("#build", RichLog).write(Text(text, style=color or ""))

    def mon_line(self, text: str, color: str | None = None) -> None:
        self.query_one("#monitor", RichLog).write(Text(text, style=color or ""))

    def set_status(self, text: str, color: str) -> None:
        self.query_one("#status", Static).update(f"[{color}]{text}[/]")

    def _ui(self, fn, *args):
        """Appelle fn dans le thread de l'interface (depuis un thread de fond)."""
        try:
            return self.app.call_from_thread(fn, *args)
        except Exception:
            return None

    def refresh_ports(self) -> None:
        ports = list(list_ports.comports())
        sel = self.query_one("#port", Select)
        sel.set_options([(f"{p.device} - {(p.description or '')[:20]}", p.device)
                         for p in ports])
        pick = next((p for p in ports if p.vid == ESPRESSIF_VID), None) or \
            next((p for p in ports if (p.vid, p.pid) == FLIPPER_VID_PID), None)
        if pick:
            sel.value = pick.device

    def selected_port(self) -> str | None:
        value = self.query_one("#port", Select).value
        return value if isinstance(value, str) else None

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        for b in self.query(Button):
            b.disabled = busy and b.id != "stop"

    def fqbn(self) -> str:
        fqbn = str(self.query_one("#board", Select).value)
        if self.query_one("#cdc", Switch).value and fqbn != "esp32:esp32:esp32":
            fqbn += ":CDCOnBoot=cdc"
        return fqbn

    # ---------- moniteur série ----------
    def open_monitor(self, port: str, baud: int) -> None:
        self.ser = serial.Serial(port, baud, timeout=0.1)
        self.reader_stop = threading.Event()
        threading.Thread(target=self._reader, args=(self.ser, self.reader_stop),
                         daemon=True).start()
        self.query_one("#connect", Button).label = "Déconnecter"
        self.set_status(f"● {port}", "green")
        self.mon_line(f"[Connecté à {port} @ {baud}]", OK)

    def close_monitor(self) -> None:
        self.reader_stop.set()
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.query_one("#connect", Button).label = "Connecter"
        self.set_status("● déconnecté", "red")

    def monitor_lost(self, err: str) -> None:
        self.close_monitor()
        self.mon_line(f"[Connexion perdue] {err}", ERR)

    def _reader(self, ser: serial.Serial, stop: threading.Event) -> None:
        buf = ""
        while not stop.is_set():
            try:
                data = ser.read(ser.in_waiting or 1)
            except Exception as e:
                if not stop.is_set():
                    self._ui(self.monitor_lost, str(e))
                return
            if not data:
                if buf:                       # ligne sans retour chariot (prompt…)
                    self._ui(self.mon_line, buf)
                    buf = ""
                continue
            buf += data.decode(errors="replace").replace("\r", "")
            *lines, buf = buf.split("\n")
            for line in lines:
                self._ui(self.mon_line, line)

    @on(Button.Pressed, "#refresh")
    def _refresh(self) -> None:
        self.refresh_ports()

    @on(Button.Pressed, "#connect")
    def toggle_connect(self) -> None:
        if self.busy:
            return
        if self.ser:
            self.close_monitor()
            self.mon_line("[Déconnecté]", MUTED)
            return
        port = self.selected_port()
        if not port:
            self.mon_line("[Monitor] Choisis d'abord un port série.", ERR)
            return
        try:
            self.open_monitor(port, int(self.query_one("#baud", Select).value))
        except Exception as e:
            self.mon_line(f"[ERREUR connexion] {e}", ERR)

    @on(Input.Submitted, "#send_line")
    def send_line(self, event: Input.Submitted) -> None:
        if not self.ser:
            self.mon_line("[Monitor] Connecte d'abord l'ESP32.", ERR)
            return
        eol = self.query_one("#eol", Select).value
        try:
            self.ser.write(event.value.encode() + (eol if isinstance(eol, str) else "").encode())
            self.mon_line(f"> {event.value}", CYAN)
            event.input.value = ""
        except Exception as e:
            self.mon_line(f"[ERREUR envoi] {e}", ERR)

    # ---------- fichiers ----------
    @on(Button.Pressed, "#open")
    def action_open_file(self) -> None:
        def loaded(path: str | None) -> None:
            if not path:
                return
            try:
                text = Path(path).read_text(encoding="utf-8")
            except Exception as e:
                self.build_line(f"[ERREUR lecture] {e}", ERR)
                return
            self.query_one("#editor", TextArea).load_text(text)
            self.query_one("#local_path", Input).value = path
            self.query_one("#sketch_name", Input).value = Path(path).stem
            self.build_line(f"[Chargé] {path}")
        self.app.push_screen(ESPFilePicker((".ino", ".c", ".cpp", ".h"),
                                    "Choisis un fichier C/C++"), loaded)

    @on(Button.Pressed, "#open_bin")
    def pick_bin(self) -> None:
        def loaded(path: str | None) -> None:
            if path:
                self.query_one("#bin_path", Input).value = path
        self.app.push_screen(ESPFilePicker((".bin",), "Choisis un firmware .bin"), loaded)

    @on(Button.Pressed, "#save")
    def save_local(self) -> None:
        path = self.query_one("#local_path", Input).value.strip()
        if not path:
            self.build_line("[Sauver] Indique d'abord un chemin local.", WARN)
            return
        try:
            Path(path).write_text(self.query_one("#editor", TextArea).text, encoding="utf-8")
            self.build_line(f"[Sauvegardé] {path}", OK)
        except Exception as e:
            self.build_line(f"[ERREUR sauvegarde] {e}", ERR)

    def write_sketch(self) -> Path:
        """Arduino exige un dossier <nom>/<nom>.ino."""
        name = re.sub(r"[^A-Za-z0-9_]", "_", self.query_one("#sketch_name", Input).value.strip())
        name = name or "sketch"
        if name[0].isdigit():
            name = "s_" + name
        folder = BUILD_DIR / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{name}.ino").write_text(
            self.query_one("#editor", TextArea).text, encoding="utf-8")
        return folder

    # ---------- actions de build ----------
    def arduino_cli(self) -> str | None:
        exe = shutil.which("arduino-cli")
        if not exe:
            self.build_line("[arduino-cli introuvable] Installe-le : "
                            "https://arduino.github.io/arduino-cli/", ERR)
        return exe

    def start(self, kind: str, steps: list[list[str]], release_port: bool) -> None:
        self.query_one("#tabs", TabbedContent).active = "tab_build"
        self.stop_flag.clear()
        self.set_busy(True)
        self.run_task(kind, steps, release_port)

    @on(Button.Pressed, "#compile")
    def action_compile(self) -> None:
        if self.busy or not (exe := self.arduino_cli()):
            return
        folder = self.write_sketch()
        self.start("compile", [[exe, "compile", "--fqbn", self.fqbn(), str(folder)]], False)

    @on(Button.Pressed, "#upload")
    def action_upload(self) -> None:
        if self.busy or not (exe := self.arduino_cli()):
            return
        port = self.selected_port()
        if not port:
            self.build_line("[Téléverser] Choisis d'abord un port série.", ERR)
            return
        folder, fqbn = self.write_sketch(), self.fqbn()
        self.start("upload", [
            [exe, "compile", "--fqbn", fqbn, str(folder)],
            [exe, "upload", "-p", port, "--fqbn", fqbn, str(folder)],
        ], True)

    @on(Button.Pressed, "#core")
    def install_core(self) -> None:
        if self.busy or not (exe := self.arduino_cli()):
            return
        base = [exe, "--additional-urls", ESP32_INDEX_URL]
        self.build_line("[Installation du core ESP32 : téléchargement de plusieurs centaines de Mo]", WARN)
        self.start("core", [base + ["core", "update-index"],
                            base + ["core", "install", "esp32:esp32"]], False)

    @on(Button.Pressed, "#flash_bin")
    def flash_bin(self) -> None:
        if self.busy:
            return
        if importlib.util.find_spec("esptool") is None:
            self.build_line("[esptool manquant] pip install esptool", ERR)
            return
        port = self.selected_port()
        binfile = Path(self.query_one("#bin_path", Input).value.strip().strip('"')).expanduser()
        addr = self.query_one("#bin_addr", Input).value.strip()
        if not port:
            self.build_line("[Flash] Choisis d'abord un port série.", ERR)
        elif not binfile.is_file():
            self.build_line(f"[Flash] Fichier introuvable : {binfile}", ERR)
        elif not re.fullmatch(r"0x[0-9a-fA-F]+|\d+", addr):
            self.build_line("[Flash] Adresse invalide (ex : 0x10000, ou 0x0 pour un .bin complet).", ERR)
        else:
            self.start("flash", [[sys.executable, "-m", "esptool", "--port", port,
                                  "--baud", str(FLASH_BAUD), "write_flash", addr, str(binfile)]], True)

    @on(Button.Pressed, "#stop")
    def action_stop(self) -> None:
        self.stop_flag.set()
        proc = self.proc
        if proc and proc.poll() is None:
            proc.terminate()

    # ---------- exécution des commandes externes ----------
    def run_proc(self, cmd: list[str]) -> tuple[int, str]:
        """Lance cmd, affiche sa sortie en direct. Renvoie (code, fin de sortie)."""
        tail: list[str] = []
        last_bucket = -1
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace", bufsize=1)
        except Exception as e:
            self._ui(self.build_line, f"[ERREUR] {e}", ERR)
            return -1, ""
        self.proc = proc
        for line in proc.stdout:
            line = line.rstrip()
            m = PCT.search(line)
            if m:
                bucket = int(m.group(1)) // 10
                if bucket == last_bucket:
                    continue
                last_bucket = bucket
            tail = (tail + [line])[-40:]
            self._ui(self.build_line, line)
        rc = proc.wait()
        self.proc = None
        return rc, "\n".join(tail)

    @work(thread=True)
    def run_task(self, kind: str, steps: list[list[str]], release_port: bool) -> None:
        saved = None
        ok = True
        try:
            if release_port and self.ser:      # le port doit être libre pour le téléversement
                saved = (self.ser.port, self.ser.baudrate)
                self._ui(self.close_monitor)
            if kind in ("upload", "flash"):
                self._ui(self.build_line, "Si l'ESP32 ne répond pas : maintiens BOOT, appuie sur "
                                          "RESET, relâche BOOT, puis relance.", MUTED)
            for cmd in steps:
                if self.stop_flag.is_set():
                    ok = False
                    break
                self._ui(self.build_line, "$ " + " ".join(cmd), WARN)
                rc, tail = self.run_proc(cmd)
                if rc != 0:
                    ok = False
                    if self.stop_flag.is_set():
                        break
                    low = tail.lower()
                    if "not installed" in low or "unknown fqbn" in low or "platform" in low:
                        self._ui(self.build_line, "→ Core ESP32 absent ? Clique sur "
                                                  "« Installer core ESP32 ».", WARN)
                    elif kind in ("upload", "flash"):
                        self._ui(self.build_line, "→ Mets l'ESP32 en mode bootloader "
                                                  "(BOOT + RESET) et vérifie le port.", WARN)
                    break
            if self.stop_flag.is_set():
                self._ui(self.build_line, "[Arrêté]", WARN)
            else:
                self._ui(self.build_line, "[Terminé]" if ok else "[ÉCHEC]", OK if ok else ERR)
            if saved:                          # le port peut se ré-énumérer après un flash
                self._reconnect(*saved)
        finally:
            self._ui(self.refresh_ports)
            self._ui(self.set_busy, False)

    def _reconnect(self, port: str, baud: int) -> None:
        for _ in range(6):
            time.sleep(1.0)
            try:
                self.app.call_from_thread(self.open_monitor, port, baud)
                return
            except Exception:
                continue
        self._ui(self.mon_line, "[Reconnexion impossible] Le port a peut-être changé : "
                                "rafraîchis les ports puis reconnecte.", WARN)

    def on_unmount(self) -> None:
        self.reader_stop.set()
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass