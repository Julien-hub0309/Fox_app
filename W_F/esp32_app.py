import json
import re
import importlib.util
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
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (Button, DirectoryTree, Footer, Header, Input,
                             Label, RichLog, Select, Static, Switch,
                             TabbedContent, TabPane, TextArea)

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


BUTTONS_FILE = Path(__file__).resolve().parent / "esp32_buttons.json"
QUICK_SKETCH_DIR = BUILD_DIR / "quick_sketch"

# --------------------------------------------------------------------------
# Sketchs prêts à téléverser (boutons "📦"). Ton éditeur n'est pas modifié.
# --------------------------------------------------------------------------
SK_CONSOLE = r"""// Console de commandes : l'ESP32 répond aux boutons "Console série"
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
      Serial.printf("%2d | %-28s | %4d dBm | canal %d\n", i + 1, WiFi.SSID(i).c_str(), (int)WiFi.RSSI(i), (int)WiFi.channel(i));
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

SK_BLINK = r"""// Fait clignoter la LED et écrit dans le moniteur série
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

SK_WIFI = r"""// Scan des réseaux WiFi toutes les 5 secondes
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
    Serial.printf("%2d | %-28s | %4d dBm | canal %d\n", i + 1, WiFi.SSID(i).c_str(), (int)WiFi.RSSI(i), (int)WiFi.channel(i));
  WiFi.scanDelete();
  delay(5000);
}
"""

SK_INFO = r"""// Affiche les infos de la puce puis ne fait plus rien
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

SK_I2C = r"""// Scan du bus I2C (pins par défaut de la carte)
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

# --------------------------------------------------------------------------
# Boutons : (libellé, type, contenu[, confirmation])
#   "serial"  -> lignes envoyées à l'ESP32 connecté ("sleep X" = pause en s)
#   "sketch"  -> sketch compilé + téléversé en un clic
#   "esptool" -> arguments esptool (port ajouté automatiquement)
#   "reset" / "boot" -> impulsion RTS/DTR (câble USB-série classique)
# Tu peux modifier cette liste ou créer tes boutons depuis l'interface.
# --------------------------------------------------------------------------
QUICK_GROUPS = [
    ("🔌 Carte", [
        ("🔁 Reset", "reset", None),
        ("🛠 Mode bootloader", "boot", None),
        ("🔍 Infos puce (esptool)", "esptool", ["flash_id"]),
        ("🧹 Effacer la flash", "esptool", ["erase_flash"], True),
    ]),
    ("⌨ Console série", [
        ("❓ help", "serial", ["help"]),
        ("ℹ info", "serial", ["info"]),
        ("💡 LED on", "serial", ["led on"]),
        ("🌑 LED off", "serial", ["led off"]),
        ("📶 Scan WiFi", "serial", ["scan"]),
        ("♻ Reboot", "serial", ["reboot"]),
    ]),
    ("📦 Sketchs en 1 clic", [
        ("⌨ Installer la console", "sketch", SK_CONSOLE),
        ("💡 Blink LED", "sketch", SK_BLINK),
        ("📶 Scanner WiFi", "sketch", SK_WIFI),
        ("🔍 Infos puce", "sketch", SK_INFO),
        ("🔌 Scanner I2C", "sketch", SK_I2C),
        ("👋 Hello", "sketch", TEMPLATE),
    ]),
    ("🦈 Marauder (si installé)", [
        ("❓ help", "serial", ["help"]),
        ("📡 Scan AP", "serial", ["scanap"]),
        ("📋 Liste AP", "serial", ["list -a"]),
        ("⏹ Stop scan", "serial", ["stopscan"]),
    ]),
]


class ActionButton(Button):
    """Bouton qui porte sa propre action."""

    def __init__(self, title: str, kind: str, payload, confirm: bool = False,
                 custom: bool = False) -> None:
        super().__init__(title, classes="qa")
        self.qa_title = title
        self.qa_kind = kind
        self.qa_payload = payload
        self.qa_confirm = confirm
        self.qa_custom = custom
        self.qa_armed = False


class ExtTree(DirectoryTree):
    """Arbre de fichiers limité aux dossiers et aux extensions voulues."""
    exts: tuple = ()

    def filter_paths(self, paths):
        return [p for p in paths if not p.name.startswith(".")
                and (p.is_dir() or p.suffix.lower() in self.exts)]


class FilePicker(ModalScreen[str | None]):
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


class ESP32App(App):
    TITLE = "ESP32 Studio"
    CSS = """
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
    #editor { height: 3fr; border: round $primary; }
    #tabs { height: 2fr; }
    #tabs TabPane { padding: 0; height: 1fr; }
    #build, #monitor { height: 1fr; border: round $success; }

    #main { height: 1fr; }
    #side { width: 34; border-right: solid $primary; padding: 0 1; }
    #work { width: 1fr; }
    #side Button { width: 100%; }
    #side .qa { height: 1; border: none; min-width: 0; margin: 0; }
    #side .section { text-style: bold; color: $accent; margin-top: 1; }
    #custom { height: auto; }
    #side Input, #side Select { width: 100%; }
    """
    BINDINGS = [
        Binding("f2", "open_file", "Ouvrir"),
        Binding("f5", "upload", "Téléverser"),
        Binding("f6", "compile", "Compiler"),
        Binding("f7", "stop", "Stop"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.ser: serial.Serial | None = None
        self.reader_stop = threading.Event()
        self.stop_flag = threading.Event()
        self.proc: subprocess.Popen | None = None
        self.busy = False
        self.auto_monitor: tuple[str, int] | None = None
        self.custom: list[dict] = self.load_custom()

    # ---------- interface ----------
    def compose(self) -> ComposeResult:
        yield Header()
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
        with Horizontal(id="main"):
            with VerticalScroll(id="side"):
                for title, actions in QUICK_GROUPS:
                    yield Label(title, classes="section")
                    for item in actions:
                        yield ActionButton(*item)
                yield Label("⭐ Mes boutons", classes="section")
                yield Vertical(id="custom")
                yield Label("➕ Créer un bouton", classes="section")
                yield Input(placeholder="Nom du bouton", id="new_label")
                yield Select([("Commandes série", "serial"), ("Sketch Arduino", "sketch")],
                             value="serial", allow_blank=False, id="new_type")
                yield Input(placeholder="cmd1; sleep 1; cmd2  (ou code)", id="new_value")
                yield Button("＋ Ajouter", id="add_btn", variant="primary")
                yield Button("＋ Depuis l'éditeur (sketch)", id="add_from_editor")
                yield Button("🗑 Supprimer (par nom)", id="del_btn", variant="error")
            with Vertical(id="work"):
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
        yield Footer()

    async def on_mount(self) -> None:
        self.refresh_ports()
        await self.rebuild_custom()
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
            return self.call_from_thread(fn, *args)
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
        self.push_screen(FilePicker((".ino", ".c", ".cpp", ".h"),
                                    "Choisis un fichier C/C++"), loaded)

    @on(Button.Pressed, "#open_bin")
    def pick_bin(self) -> None:
        def loaded(path: str | None) -> None:
            if path:
                self.query_one("#bin_path", Input).value = path
        self.push_screen(FilePicker((".bin",), "Choisis un firmware .bin"), loaded)

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

    # ---------- boutons d'actions rapides ----------
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
        buttons = [ActionButton("⭐ " + c["label"], c["type"], c["value"], custom=True)
                   for c in self.custom]
        if buttons:
            await box.mount(*buttons)

    def _disarm(self, btn: ActionButton) -> None:
        if btn.qa_armed:
            btn.qa_armed = False
            btn.label = btn.qa_title

    @on(Button.Pressed)
    def quick_action(self, event: Button.Pressed) -> None:
        btn = event.button
        if not isinstance(btn, ActionButton) or self.busy:
            return
        if btn.qa_confirm and not btn.qa_armed:       # action risquée : 2 clics
            btn.qa_armed = True
            btn.label = "⚠ Re-clique pour confirmer"
            self.set_timer(5, lambda: self._disarm(btn))
            return
        self._disarm(btn)
        kind, payload = btn.qa_kind, btn.qa_payload
        tabs = self.query_one("#tabs", TabbedContent)

        if kind == "serial":
            tabs.active = "tab_mon"
            if not self.ser:
                self.mon_line("[Monitor] Connecte d'abord l'ESP32.", ERR)
                return
            lines = payload if isinstance(payload, list) else [
                c.strip() for c in str(payload).split(";") if c.strip()]
            eol = self.query_one("#eol", Select).value
            self.run_serial(btn.qa_title, lines, eol if isinstance(eol, str) else "")
        elif kind in ("reset", "boot"):
            tabs.active = "tab_mon"
            self.pulse_reset(kind == "boot")
        elif kind == "esptool":
            self.esptool_task(list(payload))
        elif kind == "sketch":
            QUICK_SKETCH_DIR.mkdir(parents=True, exist_ok=True)
            (QUICK_SKETCH_DIR / "quick_sketch.ino").write_text(str(payload), encoding="utf-8")
            self.build_line(f"[{btn.qa_title}] sketch envoyé (ton éditeur n'est pas modifié)", MUTED)
            self.do_upload(QUICK_SKETCH_DIR)

    def do_upload(self, folder: Path) -> None:
        if self.busy or not (exe := self.arduino_cli()):
            return
        port = self.selected_port()
        if not port:
            self.build_line("[Téléverser] Choisis d'abord un port série.", ERR)
            return
        fqbn = self.fqbn()
        self.auto_monitor = None if self.ser else (
            port, int(self.query_one("#baud", Select).value))   # rouvre le moniteur après
        self.start("upload", [
            [exe, "compile", "--fqbn", fqbn, str(folder)],
            [exe, "upload", "-p", port, "--fqbn", fqbn, str(folder)],
        ], True)

    def esptool_task(self, args: list[str]) -> None:
        if importlib.util.find_spec("esptool") is None:
            self.build_line("[esptool manquant] pip install esptool", ERR)
            return
        port = self.selected_port()
        if not port:
            self.build_line("[esptool] Choisis d'abord un port série.", ERR)
            return
        self.start("flash", [[sys.executable, "-m", "esptool", "--port", port, *args]], True)

    def pulse_reset(self, bootloader: bool) -> None:
        if not self.ser:
            self.mon_line("[Monitor] Connecte d'abord l'ESP32.", ERR)
            return
        s = self.ser
        try:
            if bootloader:
                s.dtr, s.rts = False, True
                time.sleep(0.1)
                s.dtr, s.rts = True, False
                time.sleep(0.1)
                s.dtr = False
                self.mon_line("[Mode bootloader demandé — fonctionne avec un pont USB-série "
                              "classique ; sinon BOOT + RESET à la main]", WARN)
            else:
                s.dtr, s.rts = False, True
                time.sleep(0.1)
                s.rts = False
                self.mon_line("[Reset envoyé]", MUTED)
        except Exception as e:
            self.mon_line(f"[ERREUR reset] {e}", ERR)

    @work(thread=True)
    def run_serial(self, title: str, lines: list[str], eol: str) -> None:
        ser = self.ser
        if not ser:
            return
        self._ui(self.mon_line, f"▶ {title}", MUTED)
        try:
            for line in lines:
                if line.lower().startswith("sleep "):
                    time.sleep(float(line[6:]))
                    continue
                ser.write(line.encode() + eol.encode())
                self._ui(self.mon_line, f"> {line}", CYAN)
                time.sleep(0.05)
        except Exception as e:
            self._ui(self.mon_line, f"[ERREUR envoi] {e}", ERR)

    # ---------- création / suppression de boutons ----------
    async def _add_custom(self, label: str, kind: str, value: str) -> None:
        label, value = label.strip(), value.strip()
        if not label or not value:
            self.build_line("[Bouton] Donne un nom et un contenu.", WARN)
            return
        self.custom = [c for c in self.custom if c["label"].lower() != label.lower()]
        self.custom.append({"label": label, "type": kind, "value": value})
        self.save_custom()
        await self.rebuild_custom()
        self.build_line(f"[Bouton « {label} » enregistré]", OK)

    @on(Button.Pressed, "#add_btn")
    async def add_button(self) -> None:
        kind = self.query_one("#new_type", Select).value
        await self._add_custom(self.query_one("#new_label", Input).value,
                               kind if isinstance(kind, str) else "serial",
                               self.query_one("#new_value", Input).value)

    @on(Button.Pressed, "#add_from_editor")
    async def add_from_editor(self) -> None:
        await self._add_custom(self.query_one("#new_label", Input).value, "sketch",
                               self.query_one("#editor", TextArea).text)

    @on(Button.Pressed, "#del_btn")
    async def delete_button(self) -> None:
        label = self.query_one("#new_label", Input).value.strip().lower()
        before = len(self.custom)
        self.custom = [c for c in self.custom if c["label"].lower() != label]
        if len(self.custom) == before:
            self.build_line("[Supprimer] Aucun bouton à ce nom (tape son nom dans "
                            "« Nom du bouton »).", WARN)
            return
        self.save_custom()
        await self.rebuild_custom()
        self.build_line("[Bouton supprimé]", MUTED)

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
            elif release_port and self.auto_monitor:
                saved, self.auto_monitor = self.auto_monitor, None
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
                self.call_from_thread(self.open_monitor, port, baud)
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


if __name__ == "__main__":
    ESP32App().run()