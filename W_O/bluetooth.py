import argparse
import asyncio
import csv
import json
import math
import os
import sys
import threading
import time
from datetime import datetime

try:
    from bleak import BleakScanner
except ImportError:
    print("Manquant : pip install bleak")
    sys.exit(1)

# ------------------------------------------------------------
#  Base constructeurs (Bluetooth SIG company identifiers)
#  Extrait — complétable : https://bitbucket.org/bluetooth-SIG/public
# ------------------------------------------------------------
COMPANY_IDS = {
    0x0006: "Microsoft", 0x000A: "CSR", 0x000F: "Broadcom",
    0x004C: "Apple", 0x0075: "Samsung", 0x0087: "Garmin",
    0x00E0: "Google", 0x0157: "Anhui Huami (Amazfit)",
    0x0171: "Amazon", 0x01DA: "Logitech", 0x038F: "Xiaomi",
    0x03C2: "Tile", 0x0499: "Ruuvi", 0x05A7: "Sonos",
    0x0157: "Huami", 0x018E: "Bose", 0x009E: "Bose",
    0x027D: "Huawei", 0x01AB: "Fitbit", 0x02E5: "Sennheiser",
    0x0656: "Meta (Facebook)", 0x0555: "Chipolo",
}

# Types de paquets "Continuity" Apple (préfixe 0x004C)
APPLE_TYPES = {
    0x01: "Apple (handoff/other)",
    0x02: "iBeacon",
    0x05: "AirDrop",
    0x07: "AirPods / Beats",
    0x09: "AirPlay",
    0x0A: "AirPlay Target",
    0x0C: "Handoff",
    0x0D: "Apple (nearby-info, 13)",
    0x0E: "Apple (13-inch T2 / unknown)",
    0x0F: "Apple (nearby)",
    0x10: "Apple Nearby Info",
    0x12: "Find My (AirTag / réseau Localiser)",
}

def decode_apple(payload: bytes):
    """Décode un paquet constructeur Apple (Continuity)."""
    if not payload:
        return None
    ptype = payload[0]
    label = APPLE_TYPES.get(ptype, f"Apple (type 0x{ptype:02x})")
    info = {"apple_type": label}

    if ptype == 0x02 and len(payload) >= 23:      # iBeacon
        uuid = payload[2:18].hex()
        uuid_fmt = f"{uuid[0:8]}-{uuid[8:12]}-{uuid[12:16]}-{uuid[16:20]}-{uuid[20:]}"
        info["ibeacon_uuid"] = uuid_fmt
        info["ibeacon_major"] = int.from_bytes(payload[18:20], "big")
        info["ibeacon_minor"] = int.from_bytes(payload[20:22], "big")
        info["ibeacon_txpower"] = int.from_bytes(payload[22:23], "big", signed=True)

    if ptype == 0x12 and len(payload) >= 3:       # Find My
        status = payload[1]
        info["findmy_status"] = status
        info["findmy_battery"] = (status >> 6) & 0x03   # 0 plein -> 3 vide
        if len(payload) >= 30:
            info["findmy_key_prefix"] = payload[2:6].hex()

    return info

def rssi_to_distance(rssi, tx_power=-59, n=2.0):
    """Estimation grossière de distance (mètres)."""
    try:
        return round(10 ** ((tx_power - rssi) / (10 * n)), 2)
    except Exception:
        return None

def is_random_address(address: str) -> bool:
    """True si l'adresse MAC est aléatoire (bits forts de l'octet de poids fort à 1)."""
    try:
        return int(address.split(":")[0], 16) >= 0xC0
    except (ValueError, IndexError):
        return False

def analyze(device, adv):
    """Transforme une détection brute en fiche OSINT."""
    rec = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "address": device.address,
        "name": adv.local_name or device.name or "",
        "rssi": adv.rssi,
        "tx_power": adv.tx_power,
        "distance_m": rssi_to_distance(adv.rssi, adv.tx_power or -59),
        "services": ",".join(adv.service_uuids or []),
        "vendor": "",
        "type": "",
        "mfg_hex": "",
        "randomized": is_random_address(device.address),
    }

    for cid, data in (adv.manufacturer_data or {}).items():
        vendor = COMPANY_IDS.get(cid, f"0x{cid:04X}")
        rec["vendor"] = vendor
        rec["mfg_hex"] = data.hex()
        if cid == 0x004C:
            info = decode_apple(data)
            if info:
                rec["type"] = info.get("apple_type", "")
                rec.update({k: v for k, v in info.items() if k != "apple_type"})
        elif cid == 0x03C2:
            rec["type"] = "Balise Tile"
        elif cid == 0x0555:
            rec["type"] = "Balise Chipolo"
        else:
            rec["type"] = f"mfg:{vendor}"
        break

    if not rec["type"]:
        if adv.service_uuids:
            rec["type"] = "service-advertiser"
        else:
            rec["type"] = "inconnu"

    return rec

def pretty(rec):
    bits = [f"{rec['rssi']}dBm", f"~{rec['distance_m']}m"]
    if rec["vendor"]:
        bits.append(rec["vendor"])
    if rec["type"]:
        bits.append(rec["type"])
    tag = "  [!]" if rec.get("is_new") else ""
    name = rec["name"] or "(sans nom)"
    print(f"{rec['address']}  {name:<28} {' | '.join(bits)}{tag}")

class Hunter:
    def __init__(self, args):
        self.args = args
        self.seen = {}          # address -> rec
        self.known = set()
        self.new_devices = []
        self.start = time.time()
        if args.known and os.path.exists(args.known):
            self.known = set(json.load(open(args.known)))
        self.csvw = None
        if args.csv:
            new = not os.path.exists(args.csv)
            self.csvf = open(args.csv, "a", newline="")
            self.csvw = csv.DictWriter(self.csvf, fieldnames=[
                "timestamp", "address", "name", "rssi", "tx_power",
                "distance_m", "vendor", "type", "services", "mfg_hex"])
            if new:
                self.csvw.writeheader()

    async def handle(self, device, adv):
        rec = analyze(device, adv)
        if rec["rssi"] < self.args.rssi_min:
            return

        first = rec["address"] not in self.seen
        rec["is_new"] = first
        self.seen[rec["address"]] = rec

        if first:
            if self.known and rec["address"] not in self.known:
                self.new_devices.append(rec["address"])
                print("\033[93m[NOUVEAU]\033[0m ", end="")
            pretty(rec)
        elif self.args.verbose:
            pretty(rec)

        if self.csvw:
            row = {k: rec.get(k, "") for k in self.csvw.fieldnames}
            self.csvw.writerow(row)
            self.csvf.flush()

        if self.args.json:
            print(json.dumps(rec, ensure_ascii=False))

    async def run(self):
        print(f"Scan BLE {self.args.duration}s (seuil RSSI {self.args.rssi_min} dBm)…\n")
        scanner = BleakScanner(detection_callback=self.handle)
        await scanner.start()
        if self.args.watch:
            try:
                while True:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                pass
        else:
            await asyncio.sleep(self.args.duration)
        await scanner.stop()

        print(f"\n{len(self.seen)} appareils uniques en {time.time()-self.start:.0f}s.")
        if self.new_devices:
            print(f"\033[93m{len(self.new_devices)} appareil(s) inconnu(s) :\033[0m "
                  + ", ".join(self.new_devices))

        if self.args.out_json:
            with open(self.args.out_json, "w") as f:
                json.dump(list(self.seen.values()), f, indent=2, ensure_ascii=False)
            print(f"Fiches écrites -> {self.args.out_json}")

        if self.args.known:
            with open(self.args.known, "w") as f:
                json.dump(sorted(set(self.known) | set(self.seen)), f)

def _run_coro(coro):
    """Exécute une coroutine en gérant le cas où une boucle asyncio tourne déjà.

    - Cas normal (script lancé seul) : pas de boucle en cours -> asyncio.run().
    - Cas appelé depuis une app async (ex : Watch Fox / Textual) : une boucle
      tourne déjà, et asyncio.run() planterait. On exécute alors dans un thread
      dédié, qui possède sa propre boucle d'événements.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # Aucune boucle en cours : comportement standard.
        return asyncio.run(coro)

    box: dict = {"result": None, "error": None}

    def work():
        try:
            box["result"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    th = threading.Thread(target=work, daemon=True)
    th.start()
    th.join()
    if box["error"] is not None:
        raise box["error"]
    return box["result"]

def main():
    p = argparse.ArgumentParser(description="OSINT Bluetooth Low Energy")
    p.add_argument("--duration", type=float, default=20, help="durée du scan (s)")
    p.add_argument("--watch", action="store_true", help="scan continu")
    p.add_argument("--rssi-min", type=int, default=-95, help="seuil RSSI")
    p.add_argument("--csv", help="journal CSV (append)")
    p.add_argument("--out-json", help="exporter les fiches en JSON")
    p.add_argument("--json", action="store_true", help="afficher chaque détection en JSON")
    p.add_argument("--verbose", action="store_true", help="réafficher les répétitions")
    p.add_argument("--known", help="fichier de MAC connues -> alerte sur les nouvelles")
    args = p.parse_args()

    try:
        _run_coro(Hunter(args).run())
    except KeyboardInterrupt:
        print("\nArrêt.")

if __name__ == "__main__":
    main()