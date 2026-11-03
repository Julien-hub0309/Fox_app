import argparse
import base64
import json
import os
import queue
import socket
import ssl
import sys
import threading
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime


# ============================================================
#  Contexte / état partagé
# ============================================================
class Ctx:
    def __init__(self, args):
        self.timeout = args.timeout
        self.form = args.form
        self.method = args.method
        self.success = args.success
        self.fail = args.fail
        self.dn = args.dn
        self.ssl = args.ssl
        self.delay = args.delay


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.found = []
        self.tried = 0
        self.stop = False


STATE = State()


def log(msg, level="info"):
    c = {"info": "\033[0m", "good": "\033[92m",
         "warn": "\033[93m", "err": "\033[91m"}
    print(f"{c.get(level,'')}[{datetime.now():%H:%M:%S}] {msg}\033[0m", flush=True)


# ============================================================
#  DES pur-python (nécessaire pour VNC)
# ============================================================
_IP = [58,50,42,34,26,18,10,2,60,52,44,36,28,20,12,4,62,54,46,38,30,22,14,6,
       64,56,48,40,32,24,16,8,57,49,41,33,25,17,9,1,59,51,43,35,27,19,11,3,
       61,53,45,37,29,21,13,5,63,55,47,39,31,23,15,7]
_FP = [40,8,48,16,56,24,64,32,39,7,47,15,55,23,63,31,38,6,46,14,54,22,62,30,
       37,5,45,13,53,21,61,29,36,4,44,12,52,20,60,28,35,3,43,11,51,19,59,27,
       34,2,42,10,50,18,58,26,33,1,41,9,49,17,57,25]
_E = [32,1,2,3,4,5,4,5,6,7,8,9,8,9,10,11,12,13,12,13,14,15,16,17,
      16,17,18,19,20,21,20,21,22,23,24,25,24,25,26,27,28,29,28,29,30,31,32,1]
_P = [16,7,20,21,29,12,28,17,1,15,23,26,5,18,31,10,2,8,24,14,32,27,3,9,
      19,13,30,6,22,11,4,25]
_PC1 = [57,49,41,33,25,17,9,1,58,50,42,34,26,18,10,2,59,51,43,35,27,19,11,3,
        60,52,44,36,63,55,47,39,31,23,15,7,62,54,46,38,30,22,14,6,61,53,45,37,
        29,21,13,5,28,20,12,4]
_PC2 = [14,17,11,24,1,5,3,28,15,6,21,10,23,19,12,4,26,8,16,7,27,20,13,2,
        41,52,31,37,47,55,30,40,51,45,33,48,44,49,39,56,34,53,46,42,50,36,29,32]
_SHIFTS = [1,1,2,2,2,2,2,2,1,2,2,2,2,2,2,1]
_S = [
 [14,4,13,1,2,15,11,8,3,10,6,12,5,9,0,7, 0,15,7,4,14,2,13,1,10,6,12,11,9,5,3,8,
  4,1,14,8,13,6,2,11,15,12,9,7,3,10,5,0, 15,12,8,2,4,9,1,7,5,11,3,14,10,0,6,13],
 [15,1,8,14,6,11,3,4,9,7,2,13,12,0,5,10, 3,13,4,7,15,2,8,14,12,0,1,10,6,9,11,5,
  0,14,7,11,10,4,13,1,5,8,12,6,9,3,2,15, 13,8,10,1,3,15,4,2,11,6,7,12,0,5,14,9],
 [10,0,9,14,6,3,15,5,1,13,12,7,11,4,2,8, 13,7,0,9,3,4,6,10,2,8,5,14,12,11,15,1,
  13,6,4,9,8,15,3,0,11,1,2,12,5,10,14,7, 1,10,13,0,6,9,8,7,4,15,14,3,11,5,2,12],
 [7,13,14,3,0,6,9,10,1,2,8,5,11,12,4,15, 13,8,11,5,6,15,0,3,4,7,2,12,1,10,14,9,
  10,6,9,0,12,11,7,13,15,1,3,14,5,2,8,4, 3,15,0,6,10,1,13,8,9,4,5,11,12,7,2,14],
 [2,12,4,1,7,10,11,6,8,5,3,15,13,0,14,9, 14,11,2,12,4,7,13,1,5,0,15,10,3,9,8,6,
  4,2,1,11,10,13,7,8,15,9,12,5,6,3,0,14, 11,8,12,7,1,14,2,13,6,15,0,9,10,4,5,3],
 [12,1,10,15,9,2,6,8,0,13,3,4,14,7,5,11, 10,15,4,2,7,12,9,5,6,1,13,14,0,11,3,8,
  9,14,15,5,2,8,12,3,7,0,4,10,1,13,11,6, 4,3,2,12,9,5,15,10,11,14,1,7,6,0,8,13],
 [4,11,2,14,15,0,8,13,3,12,9,7,5,10,6,1, 13,0,11,7,4,9,1,10,14,3,5,12,2,15,8,6,
  1,4,11,13,12,3,7,14,10,15,6,8,0,5,9,2, 6,11,13,8,1,4,10,7,9,5,0,15,14,2,3,12],
 [13,2,8,4,6,15,11,1,10,9,3,14,5,0,12,7, 1,15,13,8,10,3,7,4,12,5,6,11,0,14,9,2,
  7,11,4,1,9,12,14,2,0,6,10,13,15,3,5,8, 2,1,14,7,4,10,8,13,15,12,9,0,3,5,6,11],
]


def _perm(block, nbits, table):
    out = 0
    for pos in table:
        out = (out << 1) | ((block >> (nbits - pos)) & 1)
    return out


def _feistel(r, subkey):
    x = _perm(r, 32, _E) ^ subkey
    out = 0
    for i in range(8):
        six = (x >> (42 - 6 * i)) & 0x3F
        row = ((six >> 4) & 2) | (six & 1)
        col = (six >> 1) & 0xF
        out = (out << 4) | _S[i][row * 16 + col]
    return _perm(out, 32, _P)


def _des_block(key, block):
    k = _perm(key, 64, _PC1)
    c, d = (k >> 28) & 0xFFFFFFF, k & 0xFFFFFFF
    subkeys = []
    for sh in _SHIFTS:
        c = ((c << sh) | (c >> (28 - sh))) & 0xFFFFFFF
        d = ((d << sh) | (d >> (28 - sh))) & 0xFFFFFFF
        subkeys.append(_perm((c << 28) | d, 56, _PC2))
    b = _perm(block, 64, _IP)
    l, r = (b >> 32) & 0xFFFFFFFF, b & 0xFFFFFFFF
    for sk in subkeys:
        l, r = r, l ^ _feistel(r, sk)
    return _perm((r << 32) | l, 64, _FP)


def vnc_des(key8, data8):
    k = 0
    for byte in key8:
        k = (k << 8) | int(f"{byte:08b}"[::-1], 2)
    return _des_block(k, int.from_bytes(data8, "big")).to_bytes(8, "big")


# ============================================================
#  Implémentations de protocoles
#  signature : fn(host, port, user, password, ctx) -> bool
# ============================================================
def _ssh(host, port, u, p, ctx):
    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(host, port=port, username=u, password=p, timeout=ctx.timeout,
                  banner_timeout=ctx.timeout, auth_timeout=ctx.timeout,
                  allow_agent=False, look_for_keys=False)
        c.close()
        return True
    except paramiko.AuthenticationException:
        return False
    except Exception:
        return False


def _ftp(host, port, u, p, ctx):
    import ftplib
    try:
        f = ftplib.FTP()
        f.connect(host, port, timeout=ctx.timeout)
        f.login(u, p)
        f.quit()
        return True
    except ftplib.error_perm:
        return False
    except Exception:
        return False


def _telnet(host, port, u, p, ctx):
    def strip_iac(data):
        out, i = b"", 0
        while i < len(data):
            if data[i] == 255 and i + 2 < len(data):
                i += 3
            else:
                out += data[i:i+1]; i += 1
        return out
    try:
        s = socket.create_connection((host, port), timeout=ctx.timeout)
        s.settimeout(ctx.timeout)
        buf = b""

        def expect(words):
            nonlocal buf
            while True:
                try:
                    chunk = s.recv(512)
                except socket.timeout:
                    return False
                if not chunk:
                    return False
                buf += strip_iac(chunk)
                low = buf.lower()
                if any(w in low for w in words):
                    return True

        if expect([b"login", b"username", b"user:"]):
            s.sendall((u + "\n").encode())
        else:
            s.close(); return False
        if expect([b"password", b"passwd", b"pass:"]):
            s.sendall((p + "\n").encode())
        else:
            s.close(); return False
        ok = expect([b"$", b"#", b">", b"welcome", b"incorrect", b"denied", b"fail"])
        s.close()
        return ok
    except Exception:
        return False


def _smtp(host, port, u, p, ctx):
    import smtplib
    try:
        c = smtplib.SMTP_SSL(host, port, timeout=ctx.timeout) if ctx.ssl \
            else smtplib.SMTP(host, port, timeout=ctx.timeout)
        c.login(u, p)
        c.quit()
        return True
    except smtplib.SMTPAuthenticationError:
        return False
    except Exception:
        return False


def _imap(host, port, u, p, ctx):
    import imaplib
    try:
        c = imaplib.IMAP4_SSL(host, port) if ctx.ssl else imaplib.IMAP4(host, port)
        c.login(u, p)
        c.logout()
        return True
    except imaplib.IMAP4.error:
        return False
    except Exception:
        return False


def _pop3(host, port, u, p, ctx):
    import poplib
    try:
        c = poplib.POP3_SSL(host, port) if ctx.ssl else poplib.POP3(host, port)
        c.user(u)
        c.pass_(p)
        c.quit()
        return True
    except poplib.error_proto:
        return False
    except Exception:
        return False


def _http_basic(url, port, u, p, ctx):
    sslctx = ssl._create_unverified_context()
    req = urllib.request.Request(url)
    req.add_header("Authorization",
                   "Basic " + base64.b64encode(f"{u}:{p}".encode()).decode())
    try:
        r = urllib.request.urlopen(req, timeout=ctx.timeout, context=sslctx)
        return r.status == 200
    except urllib.error.HTTPError as e:
        return e.code == 200
    except Exception:
        return False


def _http_form(url, port, u, p, ctx):
    sslctx = ssl._create_unverified_context()
    body = ctx.form.replace("^USER^", urllib.parse.quote(u)) \
                   .replace("^PASS^", urllib.parse.quote(p))
    try:
        if ctx.method.upper() == "POST":
            req = urllib.request.Request(url, data=body.encode())
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        else:
            req = urllib.request.Request(url + ("&" if "?" in url else "?") + body)
        r = urllib.request.urlopen(req, timeout=ctx.timeout, context=sslctx)
        text = r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "ignore")
    except Exception:
        return False
    if ctx.fail:
        return ctx.fail not in text
    if ctx.success:
        return ctx.success in text
    return True


def _redis(host, port, u, p, ctx):
    try:
        s = socket.create_connection((host, port), timeout=ctx.timeout)
        s.settimeout(ctx.timeout)
        cmd = f"AUTH {u} {p}\r\n" if u else f"AUTH {p}\r\n"
        s.sendall(cmd.encode())
        resp = s.recv(128)
        s.close()
        return resp.startswith(b"+OK")
    except Exception:
        return False


def _mysql(host, port, u, p, ctx):
    try:
        import pymysql as drv
    except ImportError:
        import MySQLdb as drv
    try:
        c = drv.connect(host=host, port=port, user=u, password=p,
                        connect_timeout=int(ctx.timeout))
        c.close()
        return True
    except Exception:
        return False


def _postgres(host, port, u, p, ctx):
    import psycopg2
    try:
        c = psycopg2.connect(host=host, port=port, user=u, password=p,
                             connect_timeout=int(ctx.timeout))
        c.close()
        return True
    except Exception:
        return False


def _mongo(host, port, u, p, ctx):
    import pymongo
    try:
        cli = pymongo.MongoClient(host, port, username=u, password=p,
                                  serverSelectionTimeoutMS=int(ctx.timeout * 1000))
        cli.admin.command("ping")
        cli.close()
        return True
    except Exception:
        return False


def _ldap(host, port, u, p, ctx):
    from ldap3 import Server, Connection, ALL
    user = ctx.dn.replace("^USER^", u) if ctx.dn else u
    try:
        srv = Server(host, port=port, get_info=ALL)
        c = Connection(srv, user=user, password=p, auto_bind=True,
                       receive_timeout=ctx.timeout)
        c.unbind()
        return True
    except Exception:
        return False


def _vnc(host, port, u, p, ctx):
    def recvn(s, n):
        data = b""
        while len(data) < n:
            chunk = s.recv(n - len(data))
            if not chunk:
                raise EOFError
            data += chunk
        return data
    try:
        s = socket.create_connection((host, port), timeout=ctx.timeout)
        s.settimeout(ctx.timeout)
        recvn(s, 12)                       # version serveur
        s.sendall(b"RFB 003.008\n")
        ntypes = recvn(s, 1)[0]
        if ntypes == 0:
            reason_len = int.from_bytes(recvn(s, 4), "big")
            recvn(s, reason_len)
            s.close(); return False
        types = recvn(s, ntypes)
        if 2 in types:                     # VNC auth
            s.sendall(b"\x02")
            challenge = recvn(s, 16)
            key = (p + "\x00" * 8)[:8].encode()
            resp = vnc_des(key, challenge[:8]) + vnc_des(key, challenge[8:])
            s.sendall(resp)
            status = int.from_bytes(recvn(s, 4), "big")
            s.close()
            return status == 0
        else:                              # security type none
            s.sendall(b"\x01")
            res = recvn(s, 4)
            s.close()
            return res == b"\x00\x00\x00\x00"
    except Exception:
        return False


def _rdp(host, port, u, p, ctx):
    """Best-effort via aardwolf (API susceptible de varier selon version)."""
    import asyncio
    from aardwolf.commons.iosettings import RDPIOSettings
    from aardwolf.commons.factory import RDPConnectionFactory

    async def go():
        st = RDPIOSettings()
        st.rdp_port = port
        st.rdp_timeout = ctx.timeout
        fac = RDPConnectionFactory.from_url(f"rdp+ntlm-password://{u}:{p}@{host}:{port}")
        fac.iosettings = st
        conn = fac.connect()
        await conn.connect()
        await conn.disconnect()
    try:
        asyncio.run(go())
        return True
    except Exception:
        return False


# ============================================================
#  Registre de protocoles
# ============================================================
PROTOCOLS = {
    "ssh":        {"port": 22,   "fn": _ssh,        "deps": ("paramiko",)},
    "ftp":        {"port": 21,   "fn": _ftp,        "deps": ()},
    "telnet":     {"port": 23,   "fn": _telnet,     "deps": ()},
    "smtp":       {"port": 25,   "fn": _smtp,       "deps": ()},
    "smtps":      {"port": 465,  "fn": _smtp,       "deps": (), "ssl": True},
    "imap":       {"port": 143,  "fn": _imap,       "deps": ()},
    "imaps":      {"port": 993,  "fn": _imap,       "deps": (), "ssl": True},
    "pop3":       {"port": 110,  "fn": _pop3,       "deps": ()},
    "pop3s":      {"port": 995,  "fn": _pop3,       "deps": (), "ssl": True},
    "http-basic": {"port": 80,   "fn": _http_basic, "deps": ()},
    "http-form":  {"port": 80,   "fn": _http_form,  "deps": ()},
    "redis":      {"port": 6379, "fn": _redis,      "deps": ()},
    "mysql":      {"port": 3306, "fn": _mysql,      "deps": ("pymysql",)},
    "postgres":   {"port": 5432, "fn": _postgres,   "deps": ("psycopg2",)},
    "mongo":      {"port": 27017, "fn": _mongo,     "deps": ("pymongo",)},
    "ldap":       {"port": 389,  "fn": _ldap,       "deps": ("ldap3",)},
    "vnc":        {"port": 5900, "fn": _vnc,        "deps": ()},
    "rdp":        {"port": 3389, "fn": _rdp,        "deps": ("aardwolf",)},
}


# ============================================================
#  CLI : parseur + normalisation des arguments d'entrée
# ============================================================
DEFAULT_PROTO = os.environ.get("MINIHYDRA_PROTO", "ssh")
if DEFAULT_PROTO not in PROTOCOLS:
    DEFAULT_PROTO = "ssh"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="brute_force",
        description="mini-hydra v2 — brute forcer multi-protocoles",
        formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("proto", nargs="?", default=DEFAULT_PROTO,
                   choices=sorted(PROTOCOLS))
    p.add_argument("target", nargs="?", default="",
                   help="hôte/IP ou URL (http-*)")

    g = p.add_mutually_exclusive_group()
    g.add_argument("-l", "--login")
    g.add_argument("-L", "--userlist")
    g.add_argument("-C", "--combos", help="fichier 'login:password'")

    g2 = p.add_mutually_exclusive_group()
    g2.add_argument("-p", "--password")
    g2.add_argument("-P", "--passlist")

    p.add_argument("-e", default="",
                   help="essais supplémentaires : n=vide, s=login, r=inversé")
    p.add_argument("-t", type=int, default=16, help="threads (défaut 16)")
    p.add_argument("-s", "--port", type=int)
    p.add_argument("-M", "--multi", help="fichier de plusieurs cibles")
    p.add_argument("-f", action="store_true", help="stop au premier hit")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("-o", "--out", help="écrire les hits dans un fichier")
    p.add_argument("--resume", help="fichier d'état pour reprise")
    p.add_argument("--delay", type=float, default=0.0, help="pause entre essais")
    p.add_argument("--timeout", type=float, default=8.0)
    p.add_argument("--ssl", action="store_true", help="forcer TLS (imap/pop3/smtp)")
    # http-form
    p.add_argument("-F", "--form", help="template 'user=^USER^&pass=^PASS^'")
    p.add_argument("-X", "--method", "-M2", dest="method",
                   default="POST", choices=["POST", "GET"])
    p.add_argument("-S", "--success", help="chaîne de succès")
    p.add_argument("--fail", help="chaîne d'échec")
    # ldap
    p.add_argument("-D", "--dn", help="template DN 'uid=^USER^,ou=...,dc=...'")
    return p


def _split_spec(spec: str):
    """'proto://cible' | 'proto:cible' | 'cible' -> (proto|None, cible)."""
    for sep in ("://", ":"):
        if sep in spec:
            head, _, tail = spec.partition(sep)
            if head in PROTOCOLS and tail:
                return head, tail
    if spec in PROTOCOLS:
        return spec, ""
    return None, spec


def _guess_proto(target: str) -> str:
    t = target.strip().lower()
    if t.startswith(("http://", "https://")):
        return "http-form" if ("=" in t or "?" in t) else "http-basic"
    return DEFAULT_PROTO


def normalize_args(args=None) -> argparse.Namespace:
    """
    Tolère plusieurs formes d'entrée :
      - None           -> lecture de sys.argv
      - Namespace      -> complété avec les valeurs par défaut manquantes
      - str            -> interprétée comme cible (ou 'proto://cible')
      - list/tuple     -> interprétée comme une ligne d'arguments
    """
    parser = build_parser()

    if args is None:
        return parser.parse_args(sys.argv[1:])

    if isinstance(args, argparse.Namespace):
        for key, val in vars(parser.parse_args([])).items():
            if not hasattr(args, key):
                setattr(args, key, val)
        return args

    tokens = [args] if isinstance(args, str) else [str(a) for a in args]

    if len(tokens) == 1:
        proto, target = _split_spec(tokens[0])
        proto = proto or _guess_proto(target)
        tokens = [proto, target] if target else [proto]
    elif tokens and tokens[0] not in PROTOCOLS:
        tokens = [DEFAULT_PROTO] + tokens

    return parser.parse_args(tokens)


# ============================================================
#  Chargement des listes / combos
# ============================================================
def load_lines(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return [l.strip() for l in f if l.strip() and not l.startswith("#")]


def build_combos(args):
    if args.combos:
        combos = []
        for line in load_lines(args.combos):
            if ":" in line:
                u, p = line.split(":", 1)
                combos.append((u, p))
        return combos

    users = load_lines(args.userlist) if args.userlist else [args.login or ""]
    passes = load_lines(args.passlist) if args.passlist else [args.password or ""]

    if args.password is None and not args.passlist:
        passes = [""]

    out = []
    for u in users:
        for p in passes:
            out.append((u, p))
        if args.e:                       # -e nsr façon hydra
            if "n" in args.e:
                out.append((u, ""))
            if "s" in args.e:
                out.append((u, u))
            if "r" in args.e:
                out.append((u, u[::-1]))
    return out


# ============================================================
#  Moteur
# ============================================================
def worker(proto, target, port, q, ctx, args, done, state_path):
    fn = PROTOCOLS[proto]["fn"]
    while not STATE.stop:
        try:
            idx, user, password = q.get_nowait()
        except queue.Empty:
            return
        ok = fn(target, port, user, password, ctx)

        with STATE.lock:
            STATE.tried += 1
            done.add(idx)
            if ok:
                STATE.found.append((target, port, user, password))
                line = (f"[{port}][{proto}] host: {target}   "
                        f"login: {user}   password: {password}")
                log("TROUVÉ -> " + line, "good")
                if args.out:
                    with open(args.out, "a") as fh:
                        fh.write(line + "\n")
                if args.f:
                    STATE.stop = True
            elif args.verbose:
                log(f"échec {user}:{password}")
        if ctx.delay:
            time.sleep(ctx.delay)
        q.task_done()


def run(args):
    # Le lanceur externe (Fox_app) appelle run(target) : args peut être
    # une chaîne, un Namespace, une liste d'argv, ou None.
    args = normalize_args(args)

    if args.proto not in PROTOCOLS:
        log(f"protocole inconnu : {args.proto}", "err")
        sys.exit(2)

    if not args.multi and not args.target:
        log("aucune cible fournie (format : 'proto cible' ou 'proto://cible').",
            "err")
        sys.exit(2)

    spec = PROTOCOLS[args.proto]
    for dep in spec["deps"]:
        try:
            __import__(dep)
        except ImportError:
            log(f"protocole '{args.proto}' requiert : pip install {dep}", "err")
            sys.exit(1)

    if args.proto == "http-form" and not args.form:
        log("http-form requiert -F (template du formulaire).", "err")
        sys.exit(1)

    if "ssl" in spec:
        args.ssl = True

    targets = load_lines(args.multi) if args.multi else [args.target]
    port = args.port or spec["port"]
    combos = build_combos(args)
    if not combos:
        log("Aucun couple user/pass.", "err")
        sys.exit(1)

    # reprise
    done = set()
    if args.resume and os.path.exists(args.resume):
        done = set(json.load(open(args.resume)))
        log(f"Reprise : {len(done)} combinaisons déjà testées.")

    ctx = Ctx(args)
    grand_start = time.time()
    total_found = 0

    for target in targets:
        STATE.stop = False
        q = queue.Queue()
        for i, (u, p) in enumerate(combos):
            q.put((i, u, p))

        log(f"Cible {target}:{port} | proto {args.proto} | "
            f"{len(combos)} combos | {args.t} threads")

        threads = []
        for _ in range(min(args.t, len(combos))):
            th = threading.Thread(target=worker,
                                  args=(args.proto, target, port, q, ctx,
                                        args, done, args.resume))
            th.daemon = True
            th.start()
            threads.append(th)
        for th in threads:
            th.join()

        if args.resume:
            json.dump(sorted(done), open(args.resume, "w"))
        total_found += len(STATE.found)
        STATE.found = []

    dur = time.time() - grand_start
    log(f"Terminé en {dur:.2f}s — {STATE.tried} essais "
        f"({STATE.tried / max(dur, 0.001):.1f}/s) — {total_found} valides")


def main(args=None):
    run(args)


if __name__ == "__main__":
    main(build_parser().parse_args())