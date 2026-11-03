"""
flipper_ctl.py - Contrôle d'un Flipper Zero + ESP32 depuis Python.

Dépendances : pip install pyserial bleak

- FlipperUSB : CLI texte via USB (complet, le plus simple).
- FlipperBLE : transport BLE brut (service série du Flipper). Il transporte le
  protocole RPC protobuf, PAS la CLI texte. Pour parler RPC il faut les .proto
  officiels : https://github.com/flipperdevices/flipperzero-protobuf
- ESP32     : liaison série par câble (USB direct, ou via le Flipper en
  "USB-UART Bridge").
"""
import asyncio
import time
import serial
from serial.tools import list_ports

PROMPT = b">: "


# --------------------------------------------------------------------------
# Flipper Zero via USB (CLI)
# --------------------------------------------------------------------------
class FlipperUSB:
    VID, PID = 0x0483, 0x5740  # STMicro VCP utilisé par le Flipper

    def __init__(self, port=None, baud=230400, timeout=3.0):
        self.ser = serial.Serial(port or self._find_port(), baud, timeout=0.1)
        self.timeout = timeout
        self.ser.write(b"\r")
        self._read_until_prompt()

    @classmethod
    def _find_port(cls):
        for p in list_ports.comports():
            if p.vid == cls.VID and p.pid == cls.PID:
                return p.device
        raise RuntimeError("Flipper introuvable en USB")

    def _read_until_prompt(self, timeout=None):
        buf, end = b"", time.time() + (timeout or self.timeout)
        while time.time() < end:
            buf += self.ser.read(256)
            if buf.endswith(PROMPT):
                break
        return buf

    def cmd(self, command, timeout=None):
        """Envoie une commande CLI et renvoie la sortie texte."""
        self.ser.reset_input_buffer()
        self.ser.write(command.encode() + b"\r")
        raw = self._read_until_prompt(timeout).decode(errors="replace")
        lines = raw.replace("\r", "").split("\n")
        # retire l'écho de la commande et le prompt final
        return "\n".join(lines[1:]).replace(">: ", "").strip()

    def interrupt(self):
        """Ctrl+C pour stopper une commande continue (ex: subghz rx)."""
        self.ser.write(b"\x03")
        return self._read_until_prompt().decode(errors="replace")

    # --- raccourcis ---
    def info(self):             return self.cmd("device_info")
    def ls(self, path="/ext"):  return self.cmd(f"storage list {path}")
    def open_app(self, name):   return self.cmd(f'loader open "{name}"')
    def run_js(self, path):     return self.cmd(f"js {path}", timeout=30)

    # --- envoi de fichiers + exécution de JS en direct ---
    def _read_until(self, token: bytes, timeout=3.0):
        buf, end = b"", time.time() + timeout
        while time.time() < end:
            buf += self.ser.read(256)
            if token in buf:
                break
        return buf

    def upload(self, remote_path: str, data: bytes, chunk=4096):
        """Écrit `data` dans `remote_path` (écrase le fichier existant)."""
        folder = remote_path.rsplit("/", 1)[0]
        self.cmd(f'storage mkdir "{folder}"')           # ignoré si existe déjà
        self.cmd(f'storage remove "{remote_path}"')      # repart d'un fichier vide
        for i in range(0, len(data), chunk):
            part = data[i:i + chunk]
            self.ser.reset_input_buffer()
            self.ser.write(f'storage write_chunk "{remote_path}" {len(part)}\r'.encode())
            if b"Ready" not in self._read_until(b"Ready"):
                raise RuntimeError("Le Flipper n'a pas accepté write_chunk")
            self.ser.write(part)
            self._read_until_prompt()
        # vérification de la taille
        stat = self.cmd(f'storage stat "{remote_path}"')
        digits = "".join(c if c.isdigit() else " " for c in stat).split()
        if not digits or int(digits[0]) != len(data):
            raise RuntimeError(f"Taille incorrecte après envoi : {stat!r}")

    def run_js_stream(self, path, on_output, should_stop=lambda: False):
        """Lance un script JS et transmet sa sortie en direct.
        S'arrête quand le script finit ou quand should_stop() renvoie True."""
        self.ser.reset_input_buffer()
        self.ser.write(f'js {path}\r'.encode())
        buf = b""
        while True:
            if should_stop():
                self.ser.write(b"\x03")
                on_output("\n[Arrêt demandé]\n")
                self._read_until_prompt(2.0)
                return
            data = self.ser.read(256)
            if data:
                buf += data
                on_output(data.decode(errors="replace").replace("\r", ""))
                if buf.endswith(PROMPT):
                    return
    def ir_tx(self, proto, addr, cmd):
        return self.cmd(f"ir tx {proto} {addr} {cmd}")
    def gpio_set(self, pin, value):
        self.cmd(f"gpio mode {pin} 1")  # 1 = sortie
        return self.cmd(f"gpio set {pin} {value}")
    def subghz_tx(self, key_hex, freq_hz, te=403, repeat=3):
        # À utiliser uniquement sur des fréquences/appareils autorisés
        return self.cmd(f"subghz tx {key_hex} {freq_hz} {te} {repeat}")

    def close(self):
        self.ser.close()


# --------------------------------------------------------------------------
# Flipper Zero via BLE (transport brut)
# --------------------------------------------------------------------------
class FlipperBLE:
    SERVICE = "8fe5b3d5-2e7f-4a98-2a48-7acc60fe0000"
    TX_CHAR = "19ed82ae-ed21-4c9d-4145-228e61fe0000"  # Flipper -> PC (notify)
    RX_CHAR = "19ed82ae-ed21-4c9d-4145-228e62fe0000"  # PC -> Flipper (write)

    def __init__(self, address=None, name_prefix="Flipper"):
        self.address, self.prefix = address, name_prefix
        self.client = None
        self.rx_queue = asyncio.Queue()

    async def connect(self):
        from bleak import BleakClient, BleakScanner
        if not self.address:
            dev = await BleakScanner.find_device_by_filter(
                lambda d, ad: (d.name or "").startswith(self.prefix), timeout=10)
            if not dev:
                raise RuntimeError("Flipper BLE introuvable (BT activé ? appairé ?)")
            self.address = dev.address
        self.client = BleakClient(self.address)
        await self.client.connect()
        await self.client.start_notify(
            self.TX_CHAR, lambda _, data: self.rx_queue.put_nowait(bytes(data)))

    async def send(self, data: bytes, chunk=20):
        for i in range(0, len(data), chunk):
            await self.client.write_gatt_char(
                self.RX_CHAR, data[i:i + chunk], response=False)
            await asyncio.sleep(0.01)

    async def recv(self, timeout=3.0) -> bytes:
        return await asyncio.wait_for(self.rx_queue.get(), timeout)

    async def close(self):
        if self.client:
            await self.client.disconnect()


# --------------------------------------------------------------------------
# ESP32 (WiFi dev board ou autre) par câble série
# --------------------------------------------------------------------------
class ESP32:
    def __init__(self, port, baud=115200):
        self.ser = serial.Serial(port, baud, timeout=0.2)

    def send(self, line, wait=1.0):
        self.ser.write(line.encode() + b"\r\n")
        end, out = time.time() + wait, b""
        while time.time() < end:
            out += self.ser.read(512)
        return out.decode(errors="replace")

    def close(self):
        self.ser.close()


# --------------------------------------------------------------------------
# Exemple : "pré-exécution" sur PC puis envoi d'ordres
# --------------------------------------------------------------------------
if __name__ == "__main__":
    f = FlipperUSB()
    print(f.info())
    print(f.ls("/ext"))

    # logique calculée côté PC, puis envoyée au Flipper
    for addr in ("00", "01"):
        f.ir_tx("NEC", addr, "08")

    # ESP32 branché en USB (adapte le port : COM5, /dev/ttyUSB0...)
    # esp = ESP32("/dev/ttyUSB0")
    # print(esp.send("help"))
    f.close()