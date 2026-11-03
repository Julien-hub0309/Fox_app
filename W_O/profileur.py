import os
import re
import json
import time
import html
import random
import hashlib
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests
from rich.table import Table
from rich.panel import Panel

try:
    import phonenumbers
    from phonenumbers import PhoneNumberMatcher, PhoneNumberFormat
except ImportError:
    phonenumbers = None

try:
    import dns.resolver
except ImportError:
    dns = None

try:
    import socks  # noqa: F401  (requis par requests[socks])
    HAS_SOCKS = True
except ImportError:
    HAS_SOCKS = False


USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]

# Plateformes vérifiables. "marqueurs" = chaînes indiquant un profil absent.
PLATFORMS = [
    {"nom": "GitHub",      "url": "https://github.com/{u}",                  "marqueurs": ["page not found", "404"], "fiable": True},
    {"nom": "GitLab",      "url": "https://gitlab.com/{u}",                  "marqueurs": ["page not found", "404"], "fiable": True},
    {"nom": "Reddit",      "url": "https://www.reddit.com/user/{u}",         "marqueurs": ["page not found", "not found"], "fiable": True},
    {"nom": "Keybase",     "url": "https://keybase.io/{u}",                  "marqueurs": ["not found"], "fiable": True},
    {"nom": "Medium",      "url": "https://medium.com/@{u}",                 "marqueurs": ["404"], "fiable": True},
    {"nom": "Dev.to",      "url": "https://dev.to/{u}",                      "marqueurs": ["404"], "fiable": True},
    {"nom": "PyPI",        "url": "https://pypi.org/user/{u}/",              "marqueurs": ["404"], "fiable": True},
    {"nom": "npm",         "url": "https://www.npmjs.com/~{u}",              "marqueurs": ["404"], "fiable": True},
    {"nom": "Telegram",    "url": "https://t.me/{u}",                        "marqueurs": [], "fiable": False},
    {"nom": "Twitch",      "url": "https://www.twitch.tv/{u}",               "marqueurs": [], "fiable": False},
    {"nom": "Steam",       "url": "https://steamcommunity.com/id/{u}",       "marqueurs": ["profile not found"], "fiable": True},
    {"nom": "SoundCloud",  "url": "https://soundcloud.com/{u}",              "marqueurs": ["404"], "fiable": True},
    {"nom": "Pinterest",   "url": "https://www.pinterest.com/{u}/",          "marqueurs": ["404"], "fiable": False},
    {"nom": "Behance",     "url": "https://www.behance.net/{u}",             "marqueurs": ["404"], "fiable": True},
    {"nom": "Dribbble",    "url": "https://dribbble.com/{u}",                "marqueurs": ["404"], "fiable": True},
    {"nom": "Mastodon",    "url": "https://mastodon.social/@{u}",            "marqueurs": ["404"], "fiable": True},
    {"nom": "StackOverflow", "url": "https://stackoverflow.com/users/filter?search={u}", "marqueurs": [], "fiable": False},
    {"nom": "Instagram",   "url": "https://www.instagram.com/{u}/",          "marqueurs": [], "fiable": False},
    {"nom": "TikTok",      "url": "https://www.tiktok.com/@{u}",             "marqueurs": [], "fiable": False},
    {"nom": "Facebook",    "url": "https://www.facebook.com/{u}",            "marqueurs": [], "fiable": False},
]

EMAIL_DOMAINS = [
    "gmail.com", "outlook.com", "hotmail.fr", "hotmail.com", "yahoo.fr",
    "yahoo.com", "live.fr", "orange.fr", "free.fr", "sfr.fr", "laposte.net",
    "icloud.com", "protonmail.com", "wanadoo.fr",
]


class Profileur:
    """Profilage OSINT actif : nom + prénom [+ âge] -> traces, comptes, contacts."""

    REGION = os.getenv("PROFILEUR_REGION", "FR")
    MAX_WORKERS = int(os.getenv("PROFILEUR_MAX_WORKERS", "10"))
    TIMEOUT = 12

    def __init__(self, nom=None, prenom=None, age=None):
        self.nom = nom.upper().strip() if nom else None
        self.prenom = prenom.capitalize().strip() if prenom else None
        self.age = int(age) if age and str(age).isdigit() else None

        self.console = None
        self.session = None
        self.use_tor = os.getenv("PROFILEUR_USE_TOR") == "1"
        self.tor_actif = False
        self.verifier = True          # vérification HTTP des profils
        self.recherche_onion = True   # recherche Ahmia/.onion
        self.max_pages = 12           # pages à crawler pour extraction

        self.resultats = {
            "informations": {},
            "combinaisons": [],
            "emails_probables": [],
            "usernames_probables": [],
            "reseaux_sociaux": {},
            "profils_verifies": [],
            "profils_probables": [],
            "github": [],
            "gravatar": [],
            "mx_valides": [],
            "emails_trouves": [],
            "telephones_trouves": [],
            "resultats_moteurs": [],
            "resultats_onion": [],
            "archives": [],
            "fuites": [],
            "sources": [],
        }

    # ------------------------------------------------------------------ #
    #  Console / I-O
    # ------------------------------------------------------------------ #
    def set_console(self, console):
        self.console = console

    def _print(self, message, style=""):
        if self.console:
            self.console.print(f"[{style}]{message}[/{style}]" if style else message)
        else:
            print(re.sub(r"\[/?[^\]]+\]", "", message) if "[" in message else message)

    def _input(self, prompt):
        return self.console.input(prompt) if self.console else input(prompt)

    @staticmethod
    def _clean(text):
        return re.sub(r"\s+", " ", text or "").strip()

    # ------------------------------------------------------------------ #
    #  Session HTTP (+ Tor)
    # ------------------------------------------------------------------ #
    def _get_session(self):
        if self.session:
            return self.session

        session = requests.Session()
        session.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "fr,en;q=0.8",
        })

        if self.use_tor:
            if not HAS_SOCKS:
                self._print("[yellow]⚠ PySocks absent (pip install requests[socks]) — direct.[/yellow]")
            else:
                proxy = os.getenv("PROFILEUR_TOR_PROXY", "socks5h://127.0.0.1:9050")
                session.proxies = {"http": proxy, "https": proxy}
                if self._check_tor(session):
                    self.tor_actif = True
                    self._print("[green]✓ Tor actif — routage anonymisé[/green]")
                else:
                    self._print("[yellow]⚠ Tor injoignable — bascule en direct[/yellow]")
                    session.proxies = {}

        self.session = session
        return session

    def _check_tor(self, session):
        try:
            r = session.get("https://check.torproject.org/api/ip", timeout=15)
            return bool(r.json().get("IsTor"))
        except Exception:
            return False

    def _get(self, url, **kwargs):
        kwargs.setdefault("timeout", self.TIMEOUT)
        kwargs.setdefault("allow_redirects", True)
        try:
            return self._get_session().get(url, **kwargs)
        except Exception:
            return None

    def _parallel(self, funcs, workers=None):
        out = []
        workers = workers or self.MAX_WORKERS
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(fn) for fn in funcs]
            for fut in as_completed(futures):
                try:
                    res = fut.result()
                    if res:
                        out.append(res)
                except Exception:
                    continue
        return out

    # ------------------------------------------------------------------ #
    #  Générations (conservées + enrichies)
    # ------------------------------------------------------------------ #
    def generer_combinaisons(self):
        combos = []
        if self.nom and self.prenom:
            p, n = self.prenom, self.nom
            combos += [f"{p} {n}", f"{n} {p}", f"{p}{n}", f"{n}{p}",
                       f"{p}-{n}", f"{n}-{p}", f"{p}.{n}", f"{p}_{n}",
                       f"{p[0]}{n}", f"{p}{n[0]}", f"{p[0]}.{n}",
                       f"{p.lower()}.{n.lower()}", f"{p.lower()}{n.lower()}",
                       f"{n.lower()}{p.lower()}"]
            if self.age:
                annee = datetime.now().year - self.age
                combos += [f"{p}{annee}", f"{p}{str(annee)[2:]}",
                           f"{p.lower()}{annee}", f"{p}.{n}{str(annee)[2:]}"]
        self.resultats["combinaisons"] = list(dict.fromkeys(combos))
        return self.resultats["combinaisons"]

    def generer_emails_probables(self):
        emails = []
        if self.nom and self.prenom:
            p, n = self.prenom.lower(), self.nom.lower()
            formats = [f"{p}.{n}", f"{n}.{p}", f"{p}{n}", f"{n}{p}",
                       f"{p[0]}{n}", f"{p}{n[0]}", f"{p}_{n}", f"{n}_{p}",
                       f"{p}.{n[0]}", f"{p[0]}.{n}"]
            if self.age:
                annee = datetime.now().year - self.age
                formats += [f"{p}{annee}", f"{p}{str(annee)[2:]}",
                            f"{p}.{n}{str(annee)[2:]}"]
            for fmt in formats:
                for domain in EMAIL_DOMAINS:
                    emails.append(f"{fmt}@{domain}")
        self.resultats["emails_probables"] = list(dict.fromkeys(emails))[:40]
        return self.resultats["emails_probables"]

    def analyser_noms_utilisateur(self):
        usernames = []
        if self.nom and self.prenom:
            p, n = self.prenom.lower(), self.nom.lower()
            bases = [f"{p}{n}", f"{n}{p}", f"{p}.{n}", f"{n}.{p}",
                     f"{p[0]}{n}", f"{p}{n[0]}", f"{p}_{n}", f"{n}_{p}",
                     f"{p}", f"{n}"]
            usernames += bases
            if self.age:
                annee = datetime.now().year - self.age
                for base in bases[:4]:
                    usernames += [f"{base}{annee}", f"{base}{str(annee)[2:]}"]
        self.resultats["usernames_probables"] = list(dict.fromkeys(usernames))[:40]
        return self.resultats["usernames_probables"]

    def rechercher_google_dorks(self):
        dorks = []
        if self.nom and self.prenom:
            nc = f"{self.prenom} {self.nom}"
            dorks += [f'"{nc}"', f'"{nc}" site:facebook.com', f'"{nc}" site:linkedin.com',
                      f'"{nc}" site:instagram.com', f'"{nc}" site:twitter.com',
                      f'"{nc}" site:tiktok.com', f'"{nc}" filetype:pdf',
                      f'"{nc}" intitle:"profil"', f'"{nc}" inurl:profil',
                      f'"{nc}" email', f'"{nc}" @gmail.com', f'"{nc}" téléphone',
                      f'"{nc}" CV OR curriculum', f'"{nc}" site:pappers.fr']
            if self.age:
                annee = datetime.now().year - self.age
                dorks += [f'"{nc}" {self.age}', f'"{nc}" {annee}']
        return dorks

    def verifier_reseaux_sociaux(self):
        reseaux = {}
        if self.nom and self.prenom:
            p, n = self.prenom.lower(), self.nom.lower()
            reseaux = {
                "Facebook": f"https://www.facebook.com/public/{self.prenom}-{self.nom}",
                "LinkedIn": f"https://www.linkedin.com/pub/dir/{self.prenom}/{self.nom}",
                "Instagram": [f"https://www.instagram.com/{p}{n}/",
                              f"https://www.instagram.com/{n}.{p}/",
                              f"https://www.instagram.com/{p}.{n}/"],
                "Twitter/X": [f"https://twitter.com/{p}{n}",
                              f"https://twitter.com/{n}{p}",
                              f"https://twitter.com/{p}_{n}"],
                "TikTok": [f"https://www.tiktok.com/@{p}{n}",
                           f"https://www.tiktok.com/@{n}.{p}"],
                "GitHub": f"https://github.com/{p}{n}",
                "Reddit": f"https://www.reddit.com/user/{p}{n}",
            }
        self.resultats["reseaux_sociaux"] = reseaux
        return reseaux

    def rechercher_annuaires(self):
        if not self.nom or not self.prenom:
            return {}
        q = f"{self.prenom}+{self.nom}"
        return {
            "PagesBlanches": f"https://www.pagesblanches.fr/recherche?quoiqui={q}",
            "118000": f"https://www.118000.fr/recherche?text={q}",
            "PageJaunes": f"https://www.pagesjaunes.fr/recherche/{self.prenom}-{self.nom}",
            "Pappers": f"https://www.pappers.fr/recherche?q={q}",
            "Societe.com": f"https://www.societe.com/cgi-bin/search?champs={q}",
            "Mappy": f"https://fr.mappy.com/recherche/{self.prenom}-{self.nom}",
        }

    # ------------------------------------------------------------------ #
    #  VÉRIFICATION RÉELLE DES PROFILS
    # ------------------------------------------------------------------ #
    def verifier_profils(self):
        usernames = self.resultats["usernames_probables"][:14]
        if not usernames:
            return []

        tasks = []
        for platform in PLATFORMS:
            for u in usernames:
                tasks.append((platform, u))

        def check(item):
            platform, u = item
            url = platform["url"].format(u=u)
            r = self._get(url)
            if r is None:
                return None
            if r.status_code == 404:
                return None
            if r.status_code >= 400:
                return None
            body = r.text[:20000].lower()
            for marker in platform["marqueurs"]:
                if marker in body:
                    return None
            return {
                "plateforme": platform["nom"],
                "username": u,
                "url": url,
                "fiable": platform["fiable"],
                "statut": r.status_code,
            }

        trouves = self._parallel([lambda i=i: check(i) for i in tasks])

        # Dédup par (plateforme, username)
        vus = set()
        uniques = []
        for t in trouves:
            key = (t["plateforme"], t["username"])
            if key not in vus:
                vus.add(key)
                uniques.append(t)

        uniques.sort(key=lambda x: (not x["fiable"], x["plateforme"]))
        self.resultats["profils_verifies"] = [u for u in uniques if u["fiable"]]
        self.resultats["profils_probables"] = [u for u in uniques if not u["fiable"]]
        self.resultats["sources"] += [u["url"] for u in uniques]
        return uniques

    # ------------------------------------------------------------------ #
    #  MOTEURS DE RECHERCHE
    # ------------------------------------------------------------------ #
    def _ddg(self, query, limit=8):
        r = self._get("https://html.duckduckgo.com/html/", params={"q": query})
        if not r or r.status_code != 200:
            return []
        page = r.text
        titres = [self._clean(html.unescape(re.sub("<[^>]+>", "", m)))
                  for m in re.findall(r'result__a"[^>]*>(.*?)</a>', page, re.S)]
        extraits = [self._clean(html.unescape(re.sub("<[^>]+>", "", m)))
                    for m in re.findall(r'result__snippet"[^>]*>(.*?)</a>', page, re.S)]
        hrefs = [self._decode_ddg(h) for h in re.findall(r'result__a"[^>]*href="([^"]+)"', page)]
        out = []
        for i, t in enumerate(titres[:limit]):
            if t:
                out.append({"titre": t, "extrait": extraits[i] if i < len(extraits) else "",
                            "url": hrefs[i] if i < len(hrefs) else "", "moteur": "DuckDuckGo"})
        return out

    def _bing(self, query, limit=6):
        r = self._get("https://www.bing.com/search", params={"q": query, "count": limit})
        if not r or r.status_code != 200:
            return []
        out = []
        for block in re.findall(r'<li class="b_algo".*?</li>', r.text, re.S)[:limit]:
            m = re.search(r'<h2>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
            if not m:
                continue
            snip = re.search(r'<p[^>]*>(.*?)</p>', block, re.S)
            out.append({
                "titre": self._clean(html.unescape(re.sub("<[^>]+>", "", m.group(2)))),
                "extrait": self._clean(html.unescape(re.sub("<[^>]+>", "", snip.group(1)))) if snip else "",
                "url": html.unescape(m.group(1)), "moteur": "Bing",
            })
        return out

    def _mojeek(self, query, limit=6):
        r = self._get("https://www.mojeek.com/search", params={"q": query})
        if not r or r.status_code != 200:
            return []
        out = []
        for m in re.finditer(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', r.text, re.S):
            url = html.unescape(m.group(1))
            titre = self._clean(html.unescape(re.sub("<[^>]+>", "", m.group(2))))
            if "mojeek.com" in url or len(titre) < 8:
                continue
            out.append({"titre": titre, "extrait": "", "url": url, "moteur": "Mojeek"})
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _decode_ddg(href):
        if href.startswith("//"):
            href = "https:" + href
        if "duckduckgo.com/l/" in href:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            if "uddg" in qs:
                return urllib.parse.unquote(qs["uddg"][0])
        return href

    def rechercher_moteurs(self):
        queries = [f'"{self.prenom} {self.nom}"']
        if self.age:
            queries.append(f'"{self.prenom} {self.nom}" {self.age}')
        queries.append(f'"{self.prenom} {self.nom}" email OR contact')

        def run(q):
            res = []
            for fn in (self._ddg, self._bing, self._mojeek):
                try:
                    res += fn(q)
                except Exception:
                    continue
            return res

        resultats = []
        for res in self._parallel([lambda q=q: run(q) for q in queries]):
            resultats += res

        # Dédup par URL
        vus, uniques = set(), []
        for r in resultats:
            if r.get("url") and r["url"] not in vus:
                vus.add(r["url"])
                uniques.append(r)
        self.resultats["resultats_moteurs"] = uniques[:60]
        self.resultats["sources"] += [r["url"] for r in uniques[:40]]
        return uniques

    # ------------------------------------------------------------------ #
    #  TOR / ONION
    # ------------------------------------------------------------------ #
    def rechercher_onion(self):
        if not self.recherche_onion:
            return []
        query = urllib.parse.quote(f'"{self.prenom} {self.nom}"')
        r = self._get(f"https://ahmia.fi/search/?q={query}")
        if not r or r.status_code != 200:
            return []

        out, vus = [], set()
        for m in re.finditer(r'href="(https?://[a-z2-7]{16,56}\.onion[^"]*)"[^>]*>(.*?)</a>',
                             r.text, re.S | re.I):
            url = html.unescape(m.group(1))
            titre = self._clean(html.unescape(re.sub("<[^>]+>", "", m.group(2))))
            host = urllib.parse.urlparse(url).netloc
            if host in vus:
                continue
            vus.add(host)
            out.append({"titre": titre or host, "url": url, "moteur": "Ahmia (onion)"})

        self.resultats["resultats_onion"] = out[:25]
        if out:
            self._print(f"[magenta]✓ {len(out)} résultat(s) .onion via Ahmia[/magenta]")
        return out

    # ------------------------------------------------------------------ #
    #  GITHUB API (comptes réels par nom complet)
    # ------------------------------------------------------------------ #
    def rechercher_github(self):
        fullname = urllib.parse.quote(f'fullname:"{self.prenom} {self.nom}"')
        r = self._get(f"https://api.github.com/search/users?q={fullname}&per_page=5",
                      headers={"Accept": "application/vnd.github+json"})
        if not r or r.status_code != 200:
            return []

        comptes = []
        for item in (r.json().get("items") or [])[:3]:
            login = item.get("login")
            d = self._get(f"https://api.github.com/users/{login}",
                          headers={"Accept": "application/vnd.github+json"})
            if d and d.status_code == 200:
                j = d.json()
                comptes.append({
                    "login": login,
                    "url": j.get("html_url"),
                    "nom": j.get("name"),
                    "email": j.get("email"),
                    "localisation": j.get("location"),
                    "bio": j.get("bio"),
                    "blog": j.get("blog"),
                    "repos": j.get("public_repos"),
                })
                time.sleep(0.4)  # respect rate-limit non authentifié

        self.resultats["github"] = comptes
        if comptes:
            self._print(f"[green]✓ {len(comptes)} compte(s) GitHub correspondant(s)[/green]")
        return comptes

    # ------------------------------------------------------------------ #
    #  GRAVATAR + MX
    # ------------------------------------------------------------------ #
    def verifier_gravatar(self):
        emails = self.resultats["emails_probables"][:16]

        def check(email):
            h = hashlib.md5(email.lower().encode()).hexdigest()
            url = f"https://www.gravatar.com/avatar/{h}?d=404"
            r = self._get(url)
            if r is not None and r.status_code == 200:
                return {"email": email, "gravatar": url}
            return None

        trouves = [g for g in self._parallel([lambda e=e: check(e) for e in emails]) if g]
        self.resultats["gravatar"] = trouves
        if trouves:
            self._print(f"[green]✓ {len(trouves)} email(s) confirmé(s) par Gravatar[/green]")
        return trouves

    def verifier_mx(self):
        if not dns:
            return []
        domaines = sorted({e.split("@")[1] for e in self.resultats["emails_probables"]})

        def check(dom):
            try:
                rep = dns.resolver.resolve(dom, "MX", lifetime=6)
                return {"domaine": dom, "mx": sorted(str(x.exchange).rstrip(".") for x in rep)[:3]}
            except Exception:
                return None

        valides = [m for m in self._parallel([lambda d=d: check(d) for d in domaines]) if m]
        self.resultats["mx_valides"] = valides
        return valides

    # ------------------------------------------------------------------ #
    #  EXTRACTION depuis les pages trouvées
    # ------------------------------------------------------------------ #
    def extraire_des_pages(self):
        urls = [r["url"] for r in self.resultats["resultats_moteurs"][: self.max_pages]
                if r.get("url")]

        def analyse(url):
            r = self._get(url)
            if not r or r.status_code != 200:
                return None
            ctype = r.headers.get("Content-Type", "")
            if "html" not in ctype and "text" not in ctype:
                return None
            page = r.text[:400_000]
            body = re.sub(r"(?is)<(script|style|noscript|svg).*?</\1>", " ", page)
            body = self._clean(html.unescape(re.sub(r"(?s)<[^>]+>", " ", body)))

            emails = set(re.findall(r"[\w.\-+]+@[\w.\-]+\.\w{2,6}", body))
            phones = set()
            if phonenumbers:
                try:
                    for match in PhoneNumberMatcher(body, self.REGION):
                        if phonenumbers.is_valid_number(match.number):
                            phones.add(phonenumbers.format_number(
                                match.number, PhoneNumberFormat.INTERNATIONAL))
                except Exception:
                    pass
            return {"url": url, "emails": emails, "telephones": phones}

        pages = self._parallel([lambda u=u: analyse(u) for u in urls])

        emails, phones = set(), set()
        for p in pages:
            emails |= p["emails"]
            phones |= p["telephones"]

        # Filtre : écarte les emails de CDN/tracking génériques
        emails = {e for e in emails if not re.search(r"\.(png|jpg|jpeg|gif|webp)$", e, re.I)}
        self.resultats["emails_trouves"] = sorted(emails)[:40]
        self.resultats["telephones_trouves"] = sorted(phones)[:20]

        if emails:
            self._print(f"[green]✓ {len(emails)} email(s) extrait(s) des pages[/green]")
        if phones:
            self._print(f"[green]✓ {len(phones)} numéro(s) extrait(s) des pages[/green]")
        return pages

    # ------------------------------------------------------------------ #
    #  ARCHIVES + FUITES
    # ------------------------------------------------------------------ #
    def verifier_archives(self):
        urls = [u for u in self.resultats["sources"][:10]]
        out = []
        for url in urls:
            r = self._get("http://archive.org/wayback/available", params={"url": url})
            if not r or r.status_code != 200:
                continue
            try:
                snap = r.json().get("archived_snapshots", {}).get("closest")
                if snap:
                    out.append({"url": url, "archive": snap.get("url"), "date": snap.get("timestamp")})
            except Exception:
                continue
        self.resultats["archives"] = out
        return out

    def verifier_fuites(self):
        key = os.getenv("HIBP_API_KEY")
        if not key:
            return []
        out = []
        for email in (self.resultats["emails_probables"][:6] +
                      [g["email"] for g in self.resultats.get("gravatar", [])])[:8]:
            r = self._get(f"https://haveibeenpwned.com/api/v3/breachedaccount/{urllib.parse.quote(email)}",
                          headers={"hibp-api-key": key, "user-agent": "Profileur-OSINT"})
            if r is None:
                continue
            if r.status_code == 200:
                out.append({"email": email, "fuites": [b.get("Name") for b in r.json()]})
            time.sleep(1.6)  # rate-limit HIBP
        self.resultats["fuites"] = out
        return out

    # ------------------------------------------------------------------ #
    #  Orchestration
    # ------------------------------------------------------------------ #
    def executer_recherche_complete(self):
        etapes = [
            ("Génération des combinaisons", self.generer_combinaisons),
            ("Génération des emails probables", self.generer_emails_probables),
            ("Génération des pseudonymes", self.analyser_noms_utilisateur),
            ("Préparation des profils sociaux", self.verifier_reseaux_sociaux),
        ]
        for label, fn in etapes:
            self._print(f"[bold blue][*] {label}…[/bold blue]")
            fn()

        self._get_session()  # init réseau (+ Tor)

        if self.verifier:
            self._print("[bold blue][*] Vérification réelle des comptes…[/bold blue]")
            self.verifier_profils()

        self._print("[bold blue][*] Recherche multi-moteurs…[/bold blue]")
        self.rechercher_moteurs()

        self._print("[bold blue][*] Recherche GitHub…[/bold blue]")
        self.rechercher_github()

        self._print("[bold blue][*] Vérification Gravatar…[/bold blue]")
        self.verifier_gravatar()

        self._print("[bold blue][*] Vérification MX des domaines…[/bold blue]")
        self.verifier_mx()

        self._print("[bold blue][*] Extraction emails / téléphones des pages…[/bold blue]")
        self.extraire_des_pages()

        if self.recherche_onion:
            self._print("[bold magenta][*] Recherche TOR / onion (Ahmia)…[/bold magenta]")
            self.rechercher_onion()

        self._print("[bold blue][*] Vérification Wayback Machine…[/bold blue]")
        self.verifier_archives()

        self.verifier_fuites()

    # ------------------------------------------------------------------ #
    #  Affichage
    # ------------------------------------------------------------------ #
    def afficher_resultats(self):
        if not self.console:
            return self.afficher_resultats_texte()

        self.console.print(Panel.fit(
            f"[bold green]Résultats du profilage[/bold green]\n"
            f"[cyan]{self.prenom} {self.nom}[/cyan]"
            + (f" [dim](~{self.age} ans)[/dim]" if self.age else "")
            + (f"\n[magenta]Tor: {'actif' if self.tor_actif else 'inactif'}[/magenta]"),
            border_style="green",
        ))

        info = Table(title="Identité", show_header=False)
        info.add_column("Champ", style="cyan")
        info.add_column("Valeur", style="white")
        info.add_row("Nom", self.nom)
        info.add_row("Prénom", self.prenom)
        if self.age:
            info.add_row("Âge", str(self.age))
            info.add_row("Année naissance", str(datetime.now().year - self.age))
        self.console.print(info)

        # Comptes confirmés
        if self.resultats["profils_verifies"]:
            t = Table(title="✅ Comptes confirmés (existence vérifiée)", show_header=True)
            t.add_column("Plateforme", style="green")
            t.add_column("Username", style="white")
            t.add_column("URL", style="dim")
            for p in self.resultats["profils_verifies"][:20]:
                t.add_row(p["plateforme"], p["username"], p["url"])
            self.console.print(t)

        # Comptes probables
        if self.resultats["profils_probables"]:
            t = Table(title="🟡 Comptes probables (à confirmer)", show_header=True)
            t.add_column("Plateforme", style="yellow")
            t.add_column("Username", style="white")
            t.add_column("URL", style="dim")
            for p in self.resultats["profils_probables"][:20]:
                t.add_row(p["plateforme"], p["username"], p["url"])
            self.console.print(t)

        # GitHub
        if self.resultats["github"]:
            t = Table(title="🐙 GitHub (API)", show_header=True)
            t.add_column("Login", style="green")
            t.add_column("Nom", style="white")
            t.add_column("Localisation", style="cyan")
            t.add_column("Email", style="yellow")
            for g in self.resultats["github"]:
                t.add_row(g["login"], g.get("nom") or "—",
                          g.get("localisation") or "—", g.get("email") or "—")
            self.console.print(t)

        # Emails
        emails = (self.resultats["emails_trouves"]
                  + [g["email"] for g in self.resultats["gravatar"]]
                  + self.resultats["emails_probables"][:10])
        if emails:
            t = Table(title="📧 Emails (extraits + confirmés Gravatar + probables)",
                      show_header=True)
            t.add_column("Email", style="yellow")
            t.add_column("Statut", style="dim")
            for g in self.resultats["gravatar"]:
                t.add_row(g["email"], "✅ Gravatar confirmé")
            for e in self.resultats["emails_trouves"]:
                if e not in [g["email"] for g in self.resultats["gravatar"]]:
                    t.add_row(e, "🔎 trouvé sur une page")
            for e in self.resultats["emails_probables"][:10]:
                if e not in [g["email"] for g in self.resultats["gravatar"]] + self.resultats["emails_trouves"]:
                    t.add_row(e, "· probable")
            self.console.print(t)

        # Téléphones
        if self.resultats["telephones_trouves"]:
            t = Table(title="📞 Numéros trouvés", show_header=False)
            t.add_column("Numéro", style="green")
            for n in self.resultats["telephones_trouves"]:
                t.add_row(n)
            self.console.print(t)

        # Onion
        if self.resultats["resultats_onion"]:
            t = Table(title="🧅 Résultats TOR / onion (Ahmia)", show_header=True)
            t.add_column("Titre", style="magenta")
            t.add_column("URL .onion", style="dim")
            for o in self.resultats["resultats_onion"][:12]:
                t.add_row(o["titre"][:60], o["url"])
            self.console.print(t)

        # Sources
        if self.resultats["sources"]:
            self.console.print(f"\n[bold cyan]🔗 {len(self.resultats['sources'])} source(s) collectée(s)[/bold cyan]")

        # Dorks
        dorks = self.rechercher_google_dorks()
        if dorks:
            self.console.print("\n[bold cyan]🔎 Google Dorks[/bold cyan]")
            for i, dork in enumerate(dorks[:8], 1):
                url = f"https://www.google.com/search?q={urllib.parse.quote(dork)}"
                self.console.print(f"  {i}. [link={url}]{dork}[/link]")

        # Annuaires
        annuaires = self.rechercher_annuaires()
        if annuaires:
            self.console.print("\n[bold cyan]📖 Annuaires[/bold cyan]")
            for nom, url in annuaires.items():
                self.console.print(f"  • [link={url}]{nom}[/link]")

    def afficher_resultats_texte(self):
        print(f"\n{'=' * 60}\nRÉSULTATS DU PROFILAGE\n{'=' * 60}")
        print(f"Nom: {self.nom}\nPrénom: {self.prenom}")
        if self.age:
            print(f"Âge: {self.age} (né ~{datetime.now().year - self.age})")
        for section in ("profils_verifies", "emails_trouves", "telephones_trouves",
                        "resultats_onion"):
            print(f"\n--- {section} ---")
            for item in self.resultats.get(section, []):
                print(f"  {item}")

    # ------------------------------------------------------------------ #
    #  Sauvegarde
    # ------------------------------------------------------------------ #
    def sauvegarder_json(self):
        filename = (f"profil_{self.prenom}_{self.nom}_"
                    f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        rapport = {
            "date": datetime.now().isoformat(),
            "tor_actif": self.tor_actif,
            "cible": {
                "nom": self.nom,
                "prenom": self.prenom,
                "age": self.age,
                "annee_naissance_estimee": datetime.now().year - self.age if self.age else None,
            },
            "google_dorks": self.rechercher_google_dorks(),
            "annuaires": self.rechercher_annuaires(),
            **self.resultats,
        }
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(rapport, f, indent=2, ensure_ascii=False)
            self._print(f"\n[bold green]💾 Rapport sauvegardé : {filename}[/bold green]")
            return filename
        except Exception as e:
            self._print(f"\n[bold red]❌ Erreur : {e}[/bold red]")
            return None

    # ------------------------------------------------------------------ #
    #  Point d'entrée
    # ------------------------------------------------------------------ #
    def run_scan(self):
        try:
            from utile.display import console as main_console
            self.set_console(main_console)
        except Exception:
            pass

        self._print(Panel.fit(
            "[bold red]🕵️ PROFILEUR OSINT[/bold red]\n"
            "[dim]Recherche de traces en ligne"
            + (" + TOR" if self.use_tor else "") + "[/dim]",
            border_style="red",
        ))

        if not self.nom:
            self.nom = self._input("[bold yellow]➤ NOM : [/bold yellow]").strip().upper()
        if not self.prenom:
            self.prenom = self._input("[bold yellow]➤ PRÉNOM : [/bold yellow]").strip().capitalize()
        if not self.age:
            age_input = self._input("[bold yellow]➤ ÂGE (optionnel) : [/bold yellow]").strip()
            self.age = int(age_input) if age_input.isdigit() else None

        if not self.nom or not self.prenom:
            self._print("[bold red]❌ Nom et prénom requis[/bold red]")
            return

        self._print(f"\n[bold blue][*] Profilage de : {self.prenom} {self.nom}[/bold blue]")

        try:
            self.executer_recherche_complete()
            self.afficher_resultats()
        finally:
            if self._input("\n[bold yellow]➤ Sauvegarder en JSON ? (o/n) : [/bold yellow]").lower() == "o":
                self.sauvegarder_json()


PersonProfiler = Profileur