import os
import re
import ssl
import json
import socket
import tempfile
import urllib.parse
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from core.base import JustradamusModule
from utile.display import console

try:
    from rich.table import Table
    from rich.panel import Panel
except ImportError:
    Table = None
    Panel = None

try:
    import dns.resolver  # noqa: F401 (optionnel, pour AXFR)
    HAS_DNS = True
except ImportError:
    HAS_DNS = False


USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) Justradamus-WebScanner"

# Ports courants -> service
COMMON_PORTS = {
    20: "ftp-data", 21: "ftp", 22: "ssh", 23: "telnet", 25: "smtp", 53: "dns",
    69: "tftp", 80: "http", 110: "pop3", 111: "rpcbind", 119: "nntp", 123: "ntp",
    135: "msrpc", 137: "netbios-ns", 139: "netbios-ssn", 143: "imap", 161: "snmp",
    389: "ldap", 443: "https", 445: "smb", 465: "smtps", 500: "isakmp", 514: "syslog",
    587: "smtp-sub", 636: "ldaps", 873: "rsync", 993: "imaps", 995: "pop3s",
    1080: "socks", 1433: "mssql", 1521: "oracle", 2049: "nfs", 2082: "cpanel",
    2083: "cpanel-ssl", 2375: "docker", 3000: "node/grafana", 3306: "mysql",
    3389: "rdp", 4443: "https-alt", 5000: "upnp/flask", 5432: "postgres",
    5672: "amqp", 5900: "vnc", 5984: "couchdb", 6379: "redis", 7001: "weblogic",
    8000: "http-alt", 8008: "http-alt", 8080: "http-proxy", 8081: "http-alt",
    8443: "https-alt", 8888: "http-alt", 9000: "php-fpm", 9090: "cockpit",
    9200: "elasticsearch", 9300: "elasticsearch", 10000: "webmin",
    11211: "memcached", 15672: "rabbitmq-mgmt", 27017: "mongodb",
}

SECURITY_HEADERS = [
    "strict-transport-security", "content-security-policy",
    "x-content-type-options", "x-frame-options", "referrer-policy",
    "permissions-policy", "x-xss-protection", "cross-origin-opener-policy",
    "cross-origin-embedder-policy",
]

WAF_SIGNATURES = {
    "cloudflare": "Cloudflare", "cf-ray": "Cloudflare",
    "akamai": "Akamai", "x-akamai": "Akamai",
    "fastly": "Fastly", "x-served-by": "Fastly",
    "sucuri": "Sucuri", "x-sucuri-id": "Sucuri",
    "incap_ses": "Imperva/Incapsula", "visid_incap": "Imperva/Incapsula",
    "awsalb": "AWS ALB", "x-amz-cf-id": "AWS CloudFront",
    "x-azure-ref": "Azure Front Door", "x-msedge-ref": "Azure",
    "x-github-request-id": "GitHub Pages", "x-vercel": "Vercel",
    "x-netlify": "Netlify", "x-shopify": "Shopify",
}

TECH_SIGNATURES = {
    "wordpress": "WordPress", "wp-content": "WordPress", "wp-includes": "WordPress",
    "drupal": "Drupal", "joomla": "Joomla", "shopify": "Shopify",
    "react": "React", "vue": "Vue.js", "angular": "Angular", "next": "Next.js",
    "jquery": "jQuery", "bootstrap": "Bootstrap", "tailwind": "Tailwind",
    "nginx": "Nginx", "apache": "Apache", "iis": "IIS", "litespeed": "LiteSpeed",
    "php": "PHP", "asp.net": "ASP.NET", "django": "Django", "rails": "Rails",
    "cloudflare": "Cloudflare", "google-analytics": "Google Analytics",
    "gtag": "Google Tag", "matomo": "Matomo", "sentry": "Sentry",
}


class WebScanner(JustradamusModule):

    PORT_TIMEOUT = float(os.getenv("WEB_PORT_TIMEOUT", "0.8"))
    MAX_WORKERS = int(os.getenv("WEB_MAX_WORKERS", "200"))
    HTTP_TIMEOUT = 10
    EXTENDED = os.getenv("WEB_EXTENDED_PORTS") == "1"
    RESOLVE_SUBS = os.getenv("WEB_RESOLVE_SUBS") == "1"

    SSL_CTX = ssl.create_default_context()
    SSL_CTX.check_hostname = False
    SSL_CTX.verify_mode = ssl.CERT_NONE

    # ------------------------------------------------------------------ #
    #  Point d'entrée
    # ------------------------------------------------------------------ #
    def scan_infra(self):
        domain = self._normalize()
        if not domain:
            console.print("[bold red][!] Cible vide[/bold red]")
            return

        console.print(f"[bold blue][🌐][/bold blue] Reconnaissance d'infrastructure : {domain}")

        results = {"cible": domain, "horodatage": datetime.utcnow().isoformat() + "Z"}

        # 1) DNS
        console.print("[dim]  → résolution DNS…[/dim]")
        results["dns"] = self._dns_records(domain)
        ipv4 = [a for a in results["dns"].get("A", [])]
        ipv6 = [a for a in results["dns"].get("AAAA", [])]
        results["ip"] = ipv4
        results["ipv6"] = ipv6

        if not ipv4 and not ipv6:
            console.print(f"[bold red][!] Domaine non résolu : {domain}[/bold red]")
            self.save_finding("Web_Infra", results)
            self._render(results)
            return

        ip = ipv4[0] if ipv4 else ipv6[0]

        # 2) PTR + WHOIS + géo
        console.print("[dim]  → reverse DNS / whois / géolocalisation…[/dim]")
        results["reverse_dns"] = self._reverse_dns(ip)
        results["whois_domaine"] = self._whois_domain(domain)
        results["whois_ip"] = self._whois_ip(ip)
        results["geoip"] = self._geoip(ip)

        # 3) Ports
        console.print("[dim]  → scan de ports…[/dim]")
        results["ports_ouverts"] = self._scan_ports(ip)

        # 4) HTTP / TLS
        console.print("[dim]  → analyse HTTP / TLS…[/dim]")
        results["tls"] = self._tls_info(domain)
        http_info = self._http_probe(domain)
        results["http"] = http_info
        results["entetes_securite"] = self._audit_headers(http_info)
        results["cdn_waf"] = self._detect_waf(http_info)
        results["technologies"] = self._detect_tech(http_info)

        # 5) Sous-domaines + reverse IP
        console.print("[dim]  → sous-domaines / reverse IP…[/dim]")
        results["sous_domaines"] = self._subdomains(domain)
        results["reverse_ip"] = self._reverse_ip(ip)

        # 6) well-known
        results["well_known"] = self._well_known(domain)

        # 7) Score
        results["score_exposition"] = self._exposure_score(results)

        self.save_finding("Web_Infra", results)
        self._render(results)

    # ------------------------------------------------------------------ #
    #  Utilitaires
    # ------------------------------------------------------------------ #
    def _normalize(self):
        t = (getattr(self, "target", "") or "").strip()
        t = re.sub(r"^[a-z]+://", "", t, flags=re.I)
        t = t.split("/")[0].split("?")[0].split(":")[0].strip().rstrip(".")
        try:
            return t.encode("idna").decode("ascii")
        except Exception:
            return t.lower()

    def _http(self, url, method="GET", timeout=None, max_bytes=250_000, headers=None):
        req = urllib.request.Request(url, method=method)
        req.add_header("User-Agent", USER_AGENT)
        req.add_header("Accept", "*/*")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.HTTP_TIMEOUT,
                                        context=self.SSL_CTX) as r:
                return {"status": r.status, "headers": dict(r.headers),
                        "body": r.read(max_bytes), "url": r.geturl(), "erreur": None}
        except urllib.error.HTTPError as e:
            return {"status": e.code, "headers": dict(e.headers),
                    "body": e.read(max_bytes), "url": url, "erreur": None}
        except Exception as e:
            return {"status": None, "headers": {}, "body": b"", "url": url, "erreur": str(e)}

    def _parallel(self, funcs, workers=None):
        out = []
        with ThreadPoolExecutor(max_workers=workers or self.MAX_WORKERS) as pool:
            for fut in as_completed([pool.submit(f) for f in funcs]):
                try:
                    r = fut.result()
                    if r:
                        out.append(r)
                except Exception:
                    continue
        return out

    # ------------------------------------------------------------------ #
    #  DNS (via DoH, sans dépendance)
    # ------------------------------------------------------------------ #
    def _doh(self, name, rtype):
        url = f"https://dns.google/resolve?name={urllib.parse.quote(name)}&type={rtype}"
        r = self._http(url, timeout=8)
        if r["status"] != 200 or not r["body"]:
            return []
        try:
            data = json.loads(r["body"].decode())
        except Exception:
            return []
        return [a.get("data", "").rstrip(".") for a in data.get("Answer", [])]

    def _dns_records(self, domain):
        records = {}
        for rtype in ("A", "AAAA", "MX", "NS", "TXT", "CNAME", "SOA"):
            vals = self._doh(domain, rtype)
            if vals:
                records[rtype] = vals[:15]
        return records

    def _reverse_dns(self, ip):
        try:
            return socket.gethostbyaddr(ip)[0]
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    #  WHOIS
    # ------------------------------------------------------------------ #
    def _whois_query(self, server, query, port=43, timeout=8):
        try:
            with socket.create_connection((server, port), timeout=timeout) as s:
                s.sendall((query + "\r\n").encode())
                chunks = []
                while True:
                    data = s.recv(4096)
                    if not data:
                        break
                    chunks.append(data)
                return b"".join(chunks).decode("utf-8", "replace")
        except Exception as e:
            return f"__ERR__{e}"

    def _whois_server(self, tld):
        fallback = {
            "com": "whois.verisign-grs.com", "net": "whois.verisign-grs.com",
            "org": "whois.pir.org", "fr": "whois.nic.fr", "io": "whois.nic.io",
            "co": "whois.nic.co", "de": "whois.denic.de", "uk": "whois.nic.uk",
            "be": "whois.dns.be", "ch": "whois.nic.ch", "eu": "whois.eu",
            "info": "whois.afilias.net", "dev": "whois.nic.google",
        }
        resp = self._whois_query("whois.iana.org", tld)
        if resp and "__ERR__" not in resp:
            m = re.search(r"^refer:\s*(\S+)", resp, re.M)
            if m:
                return m.group(1)
        return fallback.get(tld)

    def _parse_whois(self, text):
        if not text or "__ERR__" in text:
            return {"erreur": text.replace("__ERR__", "") if text else "vide"}
        wanted = {
            "registrar": r"^\s*registrar:?\s*(.+)$",
            "registrant": r"^\s*(?:registrant|holder|org(?:anisation)?):?\s*(.+)$",
            "creation": r"^\s*(?:creation date|created|created on|registered on):?\s*(.+)$",
            "expiration": r"^\s*(?:expiry date|expiration date|expires|expiry|paid-till|renewal date):?\s*(.+)$",
            "updated": r"^\s*(?:updated date|last updated|last-update|changed):?\s*(.+)$",
            "status": r"^\s*(?:domain status|status):?\s*(.+)$",
            "nameserver": r"^\s*(?:name server|nserver|nameserver):?\s*(.+)$",
        }
        out = {}
        for key, pattern in wanted.items():
            vals = re.findall(pattern, text, re.M | re.I)
            vals = [v.strip() for v in vals if v.strip()]
            if vals:
                out[key] = vals[:6] if key in ("status", "nameserver") else vals[0]
        # expires dans X jours
        if isinstance(out.get("expiration"), str):
            out["expiration_iso"] = out["expiration"][:10]
        return out or {"info": "aucun champ parsé"}

    def _whois_domain(self, domain):
        tld = domain.rsplit(".", 1)[-1]
        server = self._whois_server(tld)
        if not server:
            return {"erreur": f"pas de serveur WHOIS pour .{tld}"}
        text = self._whois_query(server, domain)
        return self._parse_whois(text)

    def _whois_ip(self, ip):
        resp = self._whois_query("whois.arin.net", f"n + {ip}")
        if "__ERR__" in resp:
            return {"erreur": resp.replace("__ERR__", "")}
        out = {}
        for key, pattern in {
            "organisation": r"^\s*OrgName:\s*(.+)$",
            "netrange": r"^\s*NetRange:\s*(.+)$",
            "pays": r"^\s*Country:\s*(.+)$",
            "cidr": r"^\s*CIDR:\s*(.+)$",
        }.items():
            m = re.search(pattern, resp, re.M | re.I)
            if m:
                out[key] = m.group(1).strip()
        return out or {"info": "whois IP vide (délégué à un RIR)"}

    # ------------------------------------------------------------------ #
    #  Géo
    # ------------------------------------------------------------------ #
    def _geoip(self, ip):
        r = self._http(f"http://ip-api.com/json/{ip}?fields=status,country,regionName,city,isp,org,as,timezone")
        if r["status"] == 200 and r["body"]:
            try:
                j = json.loads(r["body"].decode())
                if j.get("status") == "success":
                    return {
                        "pays": j.get("country"), "region": j.get("regionName"),
                        "ville": j.get("city"), "isp": j.get("isp"),
                        "organisation": j.get("org"), "asn": j.get("as"),
                        "fuseau": j.get("timezone"),
                    }
            except Exception:
                pass
        r2 = self._http(f"https://ipwho.is/{ip}")
        if r2["status"] == 200 and r2["body"]:
            try:
                j = json.loads(r2["body"].decode())
                if j.get("success"):
                    return {
                        "pays": j.get("country"), "ville": j.get("city"),
                        "isp": (j.get("connection") or {}).get("isp"),
                        "organisation": (j.get("connection") or {}).get("org"),
                        "asn": (j.get("connection") or {}).get("asn"),
                    }
            except Exception:
                pass
        return {"erreur": "géolocalisation indisponible"}

    # ------------------------------------------------------------------ #
    #  Ports
    # ------------------------------------------------------------------ #
    def _port_list(self):
        if self.EXTENDED:
            ports = set(COMMON_PORTS) | set(range(1, 1025))
        else:
            ports = set(COMMON_PORTS)
        return sorted(ports)

    def _scan_ports(self, ip):
        def check(port):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(self.PORT_TIMEOUT)
            try:
                if s.connect_ex((ip, port)) == 0:
                    return {"port": port, "service": COMMON_PORTS.get(port, "inconnu"),
                            "banniere": self._banner(s, port)}
            except Exception:
                pass
            finally:
                s.close()
            return None

        ports = self._port_list()
        resultats = [r for r in self._parallel([lambda p=p: check(p) for p in ports]) if r]
        resultats.sort(key=lambda x: x["port"])
        return resultats

    def _banner(self, sock, port):
        try:
            if port in (80, 3000, 5000, 8000, 8008, 8080, 8081, 8888, 9000):
                sock.sendall(b"HEAD / HTTP/1.0\r\nHost: x\r\nUser-Agent: x\r\n\r\n")
            elif port in (443, 4443, 8443, 2083, 2087):
                return "TLS/SSL"
            sock.settimeout(1.5)
            data = sock.recv(300)
            line = data.decode("utf-8", "replace").splitlines()
            return line[0].strip()[:120] if line else ""
        except Exception:
            return ""

    # ------------------------------------------------------------------ #
    #  TLS
    # ------------------------------------------------------------------ #
    def _tls_info(self, domain):
        try:
            pem = ssl.get_server_certificate((domain, 443), timeout=8)
        except Exception as e:
            return {"erreur": str(e)}

        info = {}
        tmp = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as f:
                f.write(pem)
                tmp = f.name
            cert = ssl._ssl._test_decode_cert(tmp)
            info["sujet"] = dict(x[0] for x in cert.get("subject", []))
            info["emetteur"] = dict(x[0] for x in cert.get("issuer", []))
            info["debut"] = cert.get("notBefore")
            info["expiration"] = cert.get("notAfter")
            info["san"] = [v for k, v in cert.get("subjectAltName", []) if k == "DNS"][:30]
            try:
                exp = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
                info["jours_restants"] = (exp - datetime.utcnow()).days
            except Exception:
                pass
        except Exception as e:
            info["erreur"] = str(e)
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except Exception:
                    pass

        # Versions TLS supportées
        info["versions_supportees"] = self._tls_versions(domain)
        return info

    def _tls_versions(self, domain):
        versions = {}
        mapping = {
            "TLSv1.2": ssl.TLSVersion.TLSv1_2 if hasattr(ssl, "TLSVersion") else None,
            "TLSv1.3": ssl.TLSVersion.TLSv1_3 if hasattr(ssl, "TLSVersion") else None,
        }
        for label, ver in mapping.items():
            if ver is None:
                continue
            try:
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                ctx.minimum_version = ver
                ctx.maximum_version = ver
                with socket.create_connection((domain, 443), timeout=6) as sock:
                    with ctx.wrap_socket(sock, server_hostname=domain):
                        versions[label] = True
            except Exception:
                versions[label] = False
        return versions

    # ------------------------------------------------------------------ #
    #  HTTP / en-têtes
    # ------------------------------------------------------------------ #
    def _http_probe(self, domain):
        out = {}
        for scheme in ("https", "http"):
            r = self._http(f"{scheme}://{domain}/", method="GET", max_bytes=120_000)
            if r["status"] is None:
                out[scheme] = {"erreur": r["erreur"]}
                continue
            headers = {k.lower(): v for k, v in r["headers"].items()}
            body = r["body"].decode("utf-8", "replace")
            title = ""
            m = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
            if m:
                title = re.sub(r"\s+", " ", m.group(1)).strip()[:150]
            out[scheme] = {
                "statut": r["status"],
                "url_finale": r["url"],
                "titre": title,
                "serveur": headers.get("server"),
                "techno_header": headers.get("x-powered-by") or headers.get("x-generator"),
                "cookies": list(re.findall(r"(?im)^set-cookie:\s*([^=;]+)", "\n".join(
                    f"{k}: {v}" for k, v in r["headers"].items())))[:15],
                "entetes": headers,
                "taille": len(r["body"]),
            }
        return out

    def _audit_headers(self, http_info):
        audit = {}
        for scheme, data in http_info.items():
            if "entetes" not in data:
                continue
            present = {h: data["entetes"].get(h) for h in SECURITY_HEADERS if h in data["entetes"]}
            manquants = [h for h in SECURITY_HEADERS if h not in data["entetes"]]
            audit[scheme] = {"presents": present, "manquants": manquants,
                             "note": f"{len(present)}/{len(SECURITY_HEADERS)}"}
        return audit

    def _detect_waf(self, http_info):
        trouve = set()
        for data in http_info.values():
            blob = " ".join(f"{k}:{v}" for k, v in data.get("entetes", {}).items()).lower()
            blob += " " + " ".join(data.get("cookies", [])).lower()
            for sig, name in WAF_SIGNATURES.items():
                if sig in blob:
                    trouve.add(name)
        return sorted(trouve) or ["aucun CDN/WAF identifié"]

    def _detect_tech(self, http_info):
        trouve = set()
        for data in http_info.values():
            blob = (data.get("entetes", {}).get("server", "") + " " +
                    (data.get("techno_header") or "") + " " + data.get("titre", "")).lower()
            for sig, name in TECH_SIGNATURES.items():
                if sig in blob:
                    trouve.add(name)
        return sorted(trouve)

    # ------------------------------------------------------------------ #
    #  Sous-domaines / reverse IP
    # ------------------------------------------------------------------ #
    def _subdomains(self, domain):
        subs = set()
        r = self._http(f"https://crt.sh/?q=%25.{urllib.parse.quote(domain)}&output=json", timeout=25)
        if r["status"] == 200 and r["body"]:
            try:
                for entry in json.loads(r["body"].decode()):
                    for name in (entry.get("name_value") or "").split("\n"):
                        name = name.strip().lower().lstrip("*.")
                        if name.endswith(domain):
                            subs.add(name)
            except Exception:
                pass

        r2 = self._http(f"https://api.hackertarget.com/hostsearch/?q={urllib.parse.quote(domain)}", timeout=15)
        if r2["status"] == 200 and r2["body"]:
            for line in r2["body"].decode().splitlines():
                if "," in line:
                    subs.add(line.split(",")[0].strip().lower())

        subs = sorted(s for s in subs if s and s != domain)[:120]
        result = [{"sous_domaine": s} for s in subs]

        if self.RESOLVE_SUBS and subs:
            def resolve(item):
                try:
                    item["ip"] = socket.gethostbyname(item["sous_domaine"])
                except Exception:
                    return None
                return item
            result = [x for x in self._parallel([lambda i=i: resolve(i) for i in result],
                                                workers=40) if x]
        return result

    def _reverse_ip(self, ip):
        r = self._http(f"https://api.hackertarget.com/reverseiplookup/?q={ip}", timeout=15)
        if r["status"] == 200 and r["body"]:
            txt = r["body"].decode().strip()
            if "error" not in txt.lower():
                return [{"domaine": d} for d in txt.splitlines()[:50]]
        return []

    # ------------------------------------------------------------------ #
    #  well-known
    # ------------------------------------------------------------------ #
    def _well_known(self, domain):
        out = {}
        checks = {
            "robots.txt": f"https://{domain}/robots.txt",
            "sitemap.xml": f"https://{domain}/sitemap.xml",
            "security.txt": f"https://{domain}/.well-known/security.txt",
        }
        for name, url in checks.items():
            r = self._http(url, max_bytes=60_000)
            if r["status"] == 200 and r["body"]:
                body = r["body"].decode("utf-8", "replace")
                if name == "robots.txt":
                    out[name] = {"statut": 200, "disallow": list(
                        dict.fromkeys(re.findall(r"(?im)^disallow:\s*(\S+)", body)))[:20]}
                else:
                    out[name] = {"statut": 200, "taille": len(body)}
        return out

    # ------------------------------------------------------------------ #
    #  Score
    # ------------------------------------------------------------------ #
    def _exposure_score(self, results):
        score = 0
        risques = []
        ports = [p["port"] for p in results.get("ports_ouverts", [])]
        sensibles = {23: "telnet", 21: "ftp", 3306: "mysql", 5432: "postgres",
                     6379: "redis", 27017: "mongodb", 9200: "elasticsearch",
                     5900: "vnc", 2375: "docker", 11211: "memcached"}
        for p in ports:
            if p in sensibles:
                score += 8
                risques.append(f"port {p} ({sensibles[p]}) exposé")
        if not results.get("tls") or results["tls"].get("erreur"):
            score += 10
            risques.append("pas de TLS détecté sur 443")
        else:
            jours = results["tls"].get("jours_restants")
            if jours is not None and jours < 15:
                score += 10
                risques.append(f"certificat expire dans {jours} jours")
            if results["tls"].get("versions_supportees", {}).get("TLSv1.2") is False:
                pass
        for scheme, audit in results.get("entetes_securite", {}).items():
            manquants = audit.get("manquants", [])
            if "strict-transport-security" in manquants:
                score += 6
                risques.append("HSTS absent")
            if "content-security-policy" in manquants:
                score += 4
                risques.append("CSP absente")
        return {"score": min(score, 100), "risques": risques[:12]}

    # ------------------------------------------------------------------ #
    #  Affichage
    # ------------------------------------------------------------------ #
    def _render(self, results):
        if not Table:
            flat = {k: (str(v)[:300]) for k, v in results.items()}
            self.display_results("Infrastructure Web", flat)
            return

        console.print()
        console.print(Panel.fit(
            f"[bold cyan]{results['cible']}[/bold cyan]  →  {', '.join(results.get('ip') or ['?'])}",
            title="🌐 Web Infra", border_style="cyan",
        ))

        dns = results.get("dns", {})
        if dns:
            t = Table(title="DNS", show_header=False, box=None)
            t.add_column("Type", style="green", no_wrap=True)
            t.add_column("Valeurs", style="white")
            for rtype, vals in dns.items():
                t.add_row(rtype, ", ".join(vals[:4]) + ("…" if len(vals) > 4 else ""))
            if results.get("reverse_dns"):
                t.add_row("PTR", results["reverse_dns"])
            console.print(t)

        geo = results.get("geoip", {})
        who = results.get("whois_domaine", {})
        info = Table(title="Enregistrement & hébergement", show_header=False, box=None)
        info.add_column("Champ", style="green", no_wrap=True)
        info.add_column("Valeur", style="white")
        for label, key in [("Pays", "pays"), ("Ville", "ville"), ("ISP", "isp"),
                           ("Organisation", "organisation"), ("ASN", "asn")]:
            if geo.get(key):
                info.add_row(label, str(geo[key]))
        for label, key in [("Registrar", "registrar"), ("Titulaire", "registrant"),
                           ("Créé", "creation"), ("Expire", "expiration"),
                           ("Nameservers", "nameserver")]:
            if who.get(key):
                v = who[key]
                info.add_row(label, ", ".join(v) if isinstance(v, list) else str(v))
        console.print(info)

        ports = results.get("ports_ouverts", [])
        if ports:
            t = Table(title=f"🔌 Ports ouverts ({len(ports)})", show_header=True)
            t.add_column("Port", style="yellow")
            t.add_column("Service", style="green")
            t.add_column("Bannière", style="dim")
            for p in ports:
                t.add_row(str(p["port"]), p["service"], p["banniere"] or "—")
            console.print(t)

        tls = results.get("tls", {})
        if tls and not tls.get("erreur"):
            console.print(f"\n[bold]🔒 TLS[/bold] — émetteur: {tls.get('emetteur', {}).get('commonName')}"
                          f" · expire: {tls.get('expiration')} ({tls.get('jours_restants')} j)")

        if results.get("cdn_waf"):
            console.print(f"[bold]🛡  CDN/WAF :[/bold] {', '.join(results['cdn_waf'])}")
        if results.get("technologies"):
            console.print(f"[bold]🧩 Technologies :[/bold] {', '.join(results['technologies'])}")

        audit = results.get("entetes_securite", {})
        if audit:
            t = Table(title="🛡  En-têtes de sécurité", show_header=True)
            t.add_column("Schéma", style="cyan")
            t.add_column("Présents", style="green")
            t.add_column("Manquants", style="red")
            for scheme, a in audit.items():
                t.add_row(scheme, a["note"], ", ".join(a["manquants"][:6]) or "—")
            console.print(t)

        subs = results.get("sous_domaines", [])
        if subs:
            console.print(f"\n[bold]📡 {len(subs)} sous-domaine(s)[/bold] : " +
                          ", ".join(s["sous_domaine"] for s in subs[:20]))

        wk = results.get("well_known", {})
        if wk:
            console.print("[bold]📄 Fichiers trouvés :[/bold] " + ", ".join(wk.keys()))

        score = results.get("score_exposition", {})
        if score.get("risques"):
            console.print(Panel(
                f"[bold yellow]Score d'exposition : {score['score']}/100[/bold yellow]\n" +
                "\n".join(f"  • {r}" for r in score["risques"]),
                border_style="yellow", title="⚠️  Exposition"))