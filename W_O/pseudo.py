# -*- coding: utf-8 -*-
"""
UsernameOSINT — scanner de pseudonyme multi-plateformes pour Justradamus.

Améliorations majeures :
  * Scan PARALLÈLE (ThreadPoolExecutor) au lieu de séquentiel.
  * Détection FIABLE par API officielle (JSON/XML) quand elle existe :
    plus de faux positifs liés aux pages de login/soft-404.
  * Gestion explicite des redirections, 404/410, soft-404 (titre + marqueurs).
  * Extraction de MÉTADONNÉES : nom réel, bio, avatar, followers, localisation.
  * VARIANTES de pseudo (points/underscores/chiffres) sur les plateformes fiables.
  * Vérification Wayback Machine des profils trouvés.
  * Support proxy (str ou dict) + Tor (socks5) + retry automatique.
  * Export JSON / CSV / HTML + `return` des résultats.

Env :
  PSEUDO_WORKERS      défaut 16
  PSEUDO_TIMEOUT      défaut 12
  PSEUDO_VARIANTS=1   active le scan des variantes
  PSEUDO_PROXY        proxy (http:// ou socks5://) si non passé en argument
"""

import os
import re
import csv
import json
import time
import html as html_lib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from xml.etree import ElementTree

import requests
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.retry import Retry
except ImportError:
    Retry = None

from core.base import JustradamusModule
from core.config import get_random_header, TIMEOUT
from utile.display import console
from rich.panel import Panel
from rich.table import Table


# ===================================================================== #
#  Registre des plateformes
#  fiable=True  -> détection robuste (API ou marqueur net)
#  api          -> endpoint officiel pour une vérification fiable
# ===================================================================== #
def _meta(d, *keys):
    out = {}
    for k in keys:
        v = d.get(k) if isinstance(d, dict) else None
        if v:
            out[k] = v if not isinstance(v, str) else v[:200]
    return out


SITES = [
    # ---------------------- Réseaux sociaux ---------------------- #
    {"nom": "Bluesky", "cat": "Réseaux sociaux", "url": "https://bsky.app/profile/{u}.bsky.social",
     "api_url": "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor={u}.bsky.social",
     "api_ok": lambda d: bool(d.get("handle")), "fiable": True,
     "api_meta": lambda d: _meta(d, "displayName", "description", "avatar")},
    {"nom": "Mastodon", "cat": "Réseaux sociaux", "url": "https://mastodon.social/@{u}",
     "api_url": "https://mastodon.social/api/v1/accounts/lookup?acct={u}",
     "api_ok": lambda d: bool(d.get("username")), "fiable": True,
     "api_meta": lambda d: _meta(d, "display_name", "note", "avatar", "followers_count")},
    {"nom": "Telegram", "cat": "Réseaux sociaux", "url": "https://t.me/{u}",
     "marqueurs": ["tgme_page_title"], "fiable": True},
    {"nom": "Threads", "cat": "Réseaux sociaux", "url": "https://www.threads.net/@{u}",
     "marqueurs": ["not found", "page not found"], "fiable": False},
    {"nom": "Twitter/X", "cat": "Réseaux sociaux", "url": "https://nitter.net/{u}",
     "marqueurs": ["user does not exist", "not found"], "fiable": False, "nitter": True},
    {"nom": "Instagram", "cat": "Réseaux sociaux", "url": "https://www.instagram.com/{u}/",
     "marqueurs": ["sorry, this page isn't available", "page not found", "not found"], "fiable": False},
    {"nom": "TikTok", "cat": "Réseaux sociaux", "url": "https://www.tiktok.com/@{u}",
     "marqueurs": ["couldn't find this account", "page not found"], "fiable": False},
    {"nom": "Facebook", "cat": "Réseaux sociaux", "url": "https://www.facebook.com/{u}",
     "marqueurs": ["this content isn't available", "page not found"], "fiable": False},
    {"nom": "VK", "cat": "Réseaux sociaux", "url": "https://vk.com/{u}",
     "marqueurs": ["page not found", "not found"], "fiable": False},
    {"nom": "Reddit", "cat": "Réseaux sociaux", "url": "https://www.reddit.com/user/{u}/",
     "api_url": "https://www.reddit.com/user/{u}/about.json",
     "api_ok": lambda d: bool(d.get("data", {}).get("name")), "fiable": True,
     "api_meta": lambda d: _meta(d.get("data", {}), "name", "total_karma", "icon_img")},
    {"nom": "Pinterest", "cat": "Réseaux sociaux", "url": "https://www.pinterest.com/{u}/",
     "marqueurs": ["page not found", "not found"], "fiable": False},
    {"nom": "Tumblr", "cat": "Réseaux sociaux", "url": "https://{u}.tumblr.com",
     "marqueurs": ["there's nothing here", "not found", "404"], "fiable": False},
    {"nom": "Snapchat", "cat": "Réseaux sociaux", "url": "https://www.snapchat.com/add/{u}",
     "marqueurs": ["not found", "page not found"], "fiable": False},
    {"nom": "YouTube", "cat": "Réseaux sociaux", "url": "https://www.youtube.com/@{u}",
     "marqueurs": ["this page isn't available", "404", "not found"], "fiable": False},

    # ---------------------- Dev & Tech ---------------------- #
    {"nom": "GitHub", "cat": "Dev & Tech", "url": "https://github.com/{u}",
     "api_url": "https://api.github.com/users/{u}",
     "api_ok": lambda d: bool(d.get("login")), "fiable": True,
     "api_meta": lambda d: _meta(d, "name", "bio", "location", "blog", "followers", "public_repos")},
    {"nom": "GitLab", "cat": "Dev & Tech", "url": "https://gitlab.com/{u}",
     "api_url": "https://gitlab.com/api/v4/users?username={u}",
     "api_ok": lambda d: bool(d) and isinstance(d, list), "fiable": True,
     "api_meta": lambda d: _meta(d[0], "name", "web_url") if d else {}},
    {"nom": "Bitbucket", "cat": "Dev & Tech", "url": "https://bitbucket.org/{u}/",
     "api_url": "https://api.bitbucket.org/2.0/users/{u}",
     "api_ok": lambda d: bool(d.get("display_name")), "fiable": True,
     "api_meta": lambda d: _meta(d, "display_name", "created_on")},
    {"nom": "Codeberg", "cat": "Dev & Tech", "url": "https://codeberg.org/{u}",
     "marqueurs": ["404", "not found"], "fiable": True},
    {"nom": "HackerNews", "cat": "Dev & Tech", "url": "https://news.ycombinator.com/user?id={u}",
     "api_url": "https://hacker-news.firebaseio.com/v0/user/{u}.json",
     "api_ok": lambda d: bool(d), "fiable": True,
     "api_meta": lambda d: _meta(d, "karma", "created")},
    {"nom": "Dev.to", "cat": "Dev & Tech", "url": "https://dev.to/{u}",
     "api_url": "https://dev.to/api/users/by_username?url={u}",
     "api_ok": lambda d: bool(d.get("username")), "fiable": True,
     "api_meta": lambda d: _meta(d, "name", "summary", "location")},
    {"nom": "Docker Hub", "cat": "Dev & Tech", "url": "https://hub.docker.com/u/{u}",
     "api_url": "https://hub.docker.com/v2/users/{u}/",
     "api_ok": lambda d: bool(d.get("username")), "fiable": True,
     "api_meta": lambda d: _meta(d, "full_name", "location", "company")},
    {"nom": "npm", "cat": "Dev & Tech", "url": "https://www.npmjs.com/~{u}",
     "api_url": "https://registry.npmjs.org/-/user/org.couchdb.user:{u}",
     "api_ok": lambda d: bool(d.get("name")), "fiable": True,
     "api_meta": lambda d: _meta(d, "name", "email")},
    {"nom": "PyPI", "cat": "Dev & Tech", "url": "https://pypi.org/user/{u}/",
     "marqueurs": ["page not found", "404"], "fiable": True},
    {"nom": "HuggingFace", "cat": "Dev & Tech", "url": "https://huggingface.co/{u}",
     "api_url": "https://huggingface.co/api/users/{u}/overview",
     "api_ok": lambda d: bool(d.get("user")), "fiable": True,
     "api_meta": lambda d: _meta(d, "fullname", "orgs")},
    {"nom": "Keybase", "cat": "Dev & Tech", "url": "https://keybase.io/{u}",
     "api_url": "https://keybase.io/_/api/1.0/user/lookup.json?username={u}",
     "api_ok": lambda d: bool(d.get("them")), "fiable": True},
    {"nom": "CodePen", "cat": "Dev & Tech", "url": "https://codepen.io/{u}",
     "marqueurs": ["page not found", "404"], "fiable": True},
    {"nom": "Replit", "cat": "Dev & Tech", "url": "https://replit.com/@{u}",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "Kaggle", "cat": "Dev & Tech", "url": "https://www.kaggle.com/{u}",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "LeetCode", "cat": "Dev & Tech", "url": "https://leetcode.com/{u}/",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "HackerRank", "cat": "Dev & Tech", "url": "https://www.hackerrank.com/{u}",
     "api_url": "https://www.hackerrank.com/rest/contests/master/hackers/{u}/profile",
     "api_ok": lambda d: bool(d.get("model")), "fiable": True},
    {"nom": "TryHackMe", "cat": "Dev & Tech", "url": "https://tryhackme.com/p/{u}",
     "api_url": "https://tryhackme.com/api/user/exist/{u}",
     "api_ok": lambda d: bool(d.get("exists")), "fiable": True},
    {"nom": "HackTheBox", "cat": "Dev & Tech", "url": "https://app.hackthebox.com/users/{u}",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "StackOverflow", "cat": "Dev & Tech", "url": "https://stackoverflow.com/users/filter?search={u}",
     "marqueurs": ["no users matched", "not found"], "fiable": False},
    {"nom": "SourceForge", "cat": "Dev & Tech", "url": "https://sourceforge.net/u/{u}/profile",
     "marqueurs": ["not found", "404"], "fiable": True},

    # ---------------------- Blog & contenu ---------------------- #
    {"nom": "Medium", "cat": "Blog & contenu", "url": "https://medium.com/@{u}",
     "marqueurs": ["page not found", "404"], "fiable": True},
    {"nom": "Substack", "cat": "Blog & contenu", "url": "https://{u}.substack.com",
     "marqueurs": ["page not found", "404"], "fiable": False},
    {"nom": "DeviantArt", "cat": "Blog & contenu", "url": "https://www.deviantart.com/{u}",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "Vimeo", "cat": "Blog & contenu", "url": "https://vimeo.com/{u}",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "Flickr", "cat": "Blog & contenu", "url": "https://www.flickr.com/people/{u}/",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "Dailymotion", "cat": "Blog & contenu", "url": "https://www.dailymotion.com/{u}",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "Behance", "cat": "Blog & contenu", "url": "https://www.behance.net/{u}",
     "marqueurs": ["not found", "404"], "fiable": True},
    {"nom": "Dribbble", "cat": "Blog & contenu", "url": "https://dribbble.com/{u}",
     "marqueurs": ["not found", "404"], "fiable": True},
    {"nom": "Letterboxd", "cat": "Blog & contenu", "url": "https://letterboxd.com/{u}/",
     "marqueurs": ["not found", "404"], "fiable": True},
    {"nom": "Goodreads", "cat": "Blog & contenu", "url": "https://www.goodreads.com/{u}",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "VSCO", "cat": "Blog & contenu", "url": "https://vsco.co/{u}/gallery",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "Odysee", "cat": "Blog & contenu", "url": "https://odysee.com/@{u}",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "Rumble", "cat": "Blog & contenu", "url": "https://rumble.com/user/{u}",
     "marqueurs": ["not found", "404"], "fiable": False},

    # ---------------------- Gaming ---------------------- #
    {"nom": "Steam", "cat": "Gaming", "url": "https://steamcommunity.com/id/{u}",
     "api_url": "https://steamcommunity.com/id/{u}?xml=1", "api_kind": "xml",
     "api_ok": lambda t: "<steamID>" in t, "fiable": True},
    {"nom": "Roblox", "cat": "Gaming", "url": "https://www.roblox.com/user.aspx?username={u}",
     "api_url": "https://users.roblox.com/v1/usernames/users", "api_method": "POST",
     "api_body": lambda u: {"usernames": [u], "excludeBannedUsers": False},
     "api_ok": lambda d: bool(d.get("data")), "fiable": True,
     "api_meta": lambda d: _meta(d["data"][0], "displayName") if d.get("data") else {}},
    {"nom": "Chess.com", "cat": "Gaming", "url": "https://www.chess.com/member/{u}",
     "api_url": "https://api.chess.com/pub/player/{u}",
     "api_ok": lambda d: bool(d.get("username")), "fiable": True,
     "api_meta": lambda d: _meta(d, "name", "followers", "country")},
    {"nom": "Lichess", "cat": "Gaming", "url": "https://lichess.org/@/{u}",
     "api_url": "https://lichess.org/api/user/{u}",
     "api_ok": lambda d: bool(d.get("username")), "fiable": True},
    {"nom": "NameMC", "cat": "Gaming", "url": "https://namemc.com/profile/{u}",
     "marqueurs": ["not found", "no profile"], "fiable": False},

    # ---------------------- Musique ---------------------- #
    {"nom": "Spotify", "cat": "Musique", "url": "https://open.spotify.com/user/{u}",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "SoundCloud", "cat": "Musique", "url": "https://soundcloud.com/{u}",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "Last.fm", "cat": "Musique", "url": "https://www.last.fm/user/{u}",
     "marqueurs": ["not found", "404"], "fiable": True},
    {"nom": "Bandcamp", "cat": "Musique", "url": "https://{u}.bandcamp.com",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "Mixcloud", "cat": "Musique", "url": "https://www.mixcloud.com/{u}/",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "Genius", "cat": "Musique", "url": "https://genius.com/{u}",
     "marqueurs": ["not found", "404"], "fiable": False},

    # ---------------------- Profils & bio ---------------------- #
    {"nom": "About.me", "cat": "Profils & bio", "url": "https://about.me/{u}",
     "marqueurs": ["there is no one", "not found"], "fiable": False},
    {"nom": "Linktree", "cat": "Profils & bio", "url": "https://linktr.ee/{u}",
     "marqueurs": ["not found", "doesn't exist"], "fiable": False},
    {"nom": "Carrd", "cat": "Profils & bio", "url": "https://{u}.carrd.co",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "Gravatar", "cat": "Profils & bio", "url": "https://gravatar.com/{u}",
     "api_url": "https://www.gravatar.com/{u}.json",
     "api_ok": lambda d: bool(d.get("entry")), "fiable": True,
     "api_meta": lambda d: _meta(d["entry"][0], "displayName", "profileUrl") if d.get("entry") else {}},
    {"nom": "SlideShare", "cat": "Profils & bio", "url": "https://www.slideshare.net/{u}",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "AniList", "cat": "Profils & bio", "url": "https://anilist.co/user/{u}/",
     "marqueurs": ["not found", "404"], "fiable": True},
    {"nom": "MyAnimeList", "cat": "Profils & bio", "url": "https://myanimelist.net/profile/{u}",
     "marqueurs": ["not found", "404"], "fiable": False},

    # ---------------------- Freelance / business ---------------------- #
    {"nom": "Fiverr", "cat": "Freelance", "url": "https://www.fiverr.com/{u}",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "Upwork", "cat": "Freelance", "url": "https://www.upwork.com/freelancers/{u}",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "Product Hunt", "cat": "Freelance", "url": "https://www.producthunt.com/@{u}",
     "marqueurs": ["not found", "404"], "fiable": False},

    # ---------------------- Dons ---------------------- #
    {"nom": "Patreon", "cat": "Dons", "url": "https://www.patreon.com/{u}",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "Ko-fi", "cat": "Dons", "url": "https://ko-fi.com/{u}",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "BuyMeACoffee", "cat": "Dons", "url": "https://www.buymeacoffee.com/{u}",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "Tipeee", "cat": "Dons", "url": "https://fr.tipeee.com/{u}",
     "marqueurs": ["not found", "404"], "fiable": False},

    # ---------------------- Adultes ---------------------- #
    {"nom": "OnlyFans", "cat": "Adultes", "url": "https://onlyfans.com/{u}",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "Fansly", "cat": "Adultes", "url": "https://fansly.com/{u}",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "ManyVids", "cat": "Adultes", "url": "https://www.manyvids.com/Profile/{u}/",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "Chaturbate", "cat": "Adultes", "url": "https://chaturbate.com/{u}/",
     "marqueurs": ["not found", "404", "page not found"], "fiable": False},
    {"nom": "Pornhub", "cat": "Adultes", "url": "https://www.pornhub.com/users/{u}",
     "marqueurs": ["not found", "doesn't exist"], "fiable": False},
    {"nom": "XVideos", "cat": "Adultes", "url": "https://www.xvideos.com/profiles/{u}",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "Cam4", "cat": "Adultes", "url": "https://www.cam4.com/{u}",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "StripChat", "cat": "Adultes", "url": "https://stripchat.com/{u}",
     "marqueurs": ["not found", "404"], "fiable": False},
    {"nom": "BongaCams", "cat": "Adultes", "url": "https://fr.bongacams.com/profile/{u}",
     "marqueurs": ["not found", "404"], "fiable": False},
]

NITTER_INSTANCES = ["https://nitter.net", "https://nitter.poast.org", "https://nitter.1d4.us"]


class UsernameOSINT(JustradamusModule):

    MAX_WORKERS = int(os.getenv("PSEUDO_WORKERS", "16"))
    TIMEOUT_HTTP = float(os.getenv("PSEUDO_TIMEOUT", str(TIMEOUT)))
    SCAN_VARIANTS = os.getenv("PSEUDO_VARIANTS") == "1"
    EXTRA_HTML = 40_000

    def __init__(self, target, proxy=None):
        super().__init__(target, proxy)
        self.username = target.lower().strip().replace("@", "")
        self.clean = re.sub(r"[^a-zA-Z0-9_-]", "", self.username)

        # Normalisation du proxy (str OU dict acceptés)
        proxy = proxy or os.getenv("PSEUDO_PROXY")
        if isinstance(proxy, str):
            self.proxies = {"http": proxy, "https": proxy}
        elif isinstance(proxy, dict):
            self.proxies = proxy
        else:
            self.proxies = None

        self.found = []          # (site, url) — compat
        self.not_found = []
        self.errors = []
        self.details = []        # dicts enrichis
        self.variants_trouves = {}

        self.session = self._build_session()

    # ------------------------------------------------------------------ #
    #  Session
    # ------------------------------------------------------------------ #
    def _build_session(self):
        s = requests.Session()
        s.headers.update(get_random_header())
        if Retry:
            retry = Retry(total=2, backoff_factor=0.5,
                          status_forcelist=[429, 500, 502, 503, 504],
                          allowed_methods=["GET", "POST"])
            adapter = HTTPAdapter(max_retries=retry, pool_connections=32, pool_maxsize=32)
            s.mount("https://", adapter)
            s.mount("http://", adapter)
        return s

    def _get(self, url, method="GET", **kw):
        try:
            return self.session.request(
                method, url, headers=get_random_header(), proxies=self.proxies,
                timeout=self.TIMEOUT_HTTP, allow_redirects=True, **kw)
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    #  Variantes de pseudo
    # ------------------------------------------------------------------ #
    def generer_variantes(self):
        u = self.username
        v = {u}
        for sep in (".", "_", "-"):
            if sep in u:
                v.add(u.replace(sep, ""))
                v.add(u.replace(sep, "_"))
                v.add(u.replace(sep, "."))
        stripped = re.sub(r"\d+$", "", u)
        if stripped and stripped != u:
            v.add(stripped)
        v.discard("")
        return sorted(v)[:6]

    # ------------------------------------------------------------------ #
    #  Détection d'une plateforme
    # ------------------------------------------------------------------ #
    def _check(self, site, username):
        result = {
            "site": site["nom"], "categorie": site["cat"], "username": username,
            "fiable": site.get("fiable", False), "url": site["url"].format(u=username),
            "statut": None, "meta": {},
        }

        # --- 1) API fiable si disponible ---
        if site.get("api_url"):
            api_url = site["api_url"].format(u=username)
            kw = {}
            if site.get("api_method") == "POST":
                body = site["api_body"](username) if site.get("api_body") else {}
                kw["json"] = body
                api_url = api_url  # url fixe pour POST
            r = self._get(api_url, method=site.get("api_method", "GET"), **kw)
            if r is None:
                result["statut"] = "error"
                return result
            if r.status_code in (404, 410):
                result["statut"] = "not_found"
                return result
            if 200 <= r.status_code < 300:
                try:
                    if site.get("api_kind") == "xml":
                        ok = site["api_ok"](r.text)
                        payload = r.text
                    else:
                        payload = r.json()
                        ok = site["api_ok"](payload)
                except Exception:
                    ok = False
                    payload = None
                if ok:
                    result["statut"] = "found"
                    if site.get("api_meta") and payload is not None:
                        try:
                            result["meta"] = site["api_meta"](payload) or {}
                        except Exception:
                            pass
                    return result
                result["statut"] = "not_found"
                return result
            if r.status_code in (401, 403, 429):
                result["statut"] = "error"
                return result

        # --- 2) Fallback HTML avec détection soft-404 ---
        if site.get("nitter"):
            r = None
            for base in NITTER_INSTANCES:
                r = self._get(f"{base}/{username}")
                if r is not None and r.status_code == 200:
                    break
        else:
            r = self._get(site["url"].format(u=username))

        if r is None:
            result["statut"] = "error"
            return result
        if r.status_code in (404, 410):
            result["statut"] = "not_found"
            return result
        if r.status_code != 200:
            result["statut"] = "error"
            return result

        body = r.text[: self.EXTRA_HTML]
        low = body.lower()

        # Titre = source fiable de soft-404
        titre = ""
        m = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
        if m:
            titre = re.sub(r"\s+", " ", html_lib.unescape(m.group(1))).strip()[:150]
            low += " " + titre.lower()

        for marker in site.get("marqueurs", []):
            if marker.lower() in low:
                result["statut"] = "not_found"
                return result

        # Heuristique soft-404 générique
        if re.search(r"\b(404|page not found|not found)\b", titre.lower()):
            result["statut"] = "not_found"
            return result

        result["statut"] = "found"
        result["meta"] = self._extract_meta(body, titre)
        return result

    def _extract_meta(self, body, titre):
        meta = {}
        if titre:
            meta["titre"] = titre
        m = re.search(r'<meta[^>]+(?:property|name)="(?:og:description|description)"[^>]+content="([^"]*)"', body, re.I)
        if m:
            meta["description"] = html_lib.unescape(m.group(1))[:200]
        m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]*)"', body, re.I)
        if m:
            meta["avatar"] = m.group(1)
        return meta

    # ------------------------------------------------------------------ #
    #  Compat : ancien check_site
    # ------------------------------------------------------------------ #
    def check_site(self, site_name, url_template, not_found_texts=None):
        site = {"nom": site_name, "cat": "divers", "url": url_template,
                "marqueurs": not_found_texts or [], "fiable": False}
        res = self._check(site, self.username)
        self._record(res)

    def _record(self, res):
        if res["statut"] == "found":
            self.found.append((res["site"], res["url"]))
            self.details.append(res)
            console.print(f"[green][✓][/green] [bold]{res['site']:<16}[/bold] [white]{res['url']}[/white]")
        elif res["statut"] == "not_found":
            self.not_found.append(res["site"])
            console.print(f"[red][✗][/red] {res['site']}")
        else:
            self.errors.append(res["site"])
            console.print(f"[yellow][!][/yellow] {res['site']}: bloqué/timeout")

    # ------------------------------------------------------------------ #
    #  Scan
    # ------------------------------------------------------------------ #
    def run_scan(self):
        console.print(Panel.fit(
            f"[bold cyan]🔍 OSINT USERNAME SCANNER[/bold cyan]\n"
            f"[dim]Pseudo cible : [/dim][bold white]{self.username}[/bold white]\n"
            f"[dim]{len(SITES)} plateformes · {self.MAX_WORKERS} threads"
            + (" · Tor/proxy actif" if self.proxies else "") + "[/dim]",
            border_style="cyan",
        ))

        categories = {}
        for s in SITES:
            categories.setdefault(s["cat"], []).append(s)

        def scan_site(site):
            return self._check(site, self.username)

        for cat, sites in categories.items():
            console.print(f"\n[bold cyan][★ {cat} ★][/bold cyan]")
            with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as pool:
                for res in pool.map(scan_site, sites):
                    self._record(res)

        # Variantes
        if self.SCAN_VARIANTS:
            self._scan_variants()

        # Archives des profils trouvés
        self._verifier_archives()

        self._afficher_resume()
        return self.get_resultats()

    def _scan_variants(self):
        console.print("\n[bold cyan][★ VARIANTES DE PSEUDO ★][/bold cyan]")
        fiables = [s for s in SITES if s.get("fiable") and s.get("api_url")]
        variantes = [v for v in self.generer_variantes() if v != self.username]
        for var in variantes:
            trouve = []
            with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as pool:
                for res in pool.map(lambda s: self._check(s, var), fiables):
                    if res["statut"] == "found":
                        trouve.append(res["site"])
            if trouve:
                self.variants_trouves[var] = trouve
                console.print(f"  [yellow]{var}[/yellow] → " + ", ".join(trouve))

    def _verifier_archives(self):
        for res in self.details[:15]:
            try:
                r = self._get("http://archive.org/wayback/available", params={"url": res["url"]})
                if r and r.status_code == 200:
                    snap = r.json().get("archived_snapshots", {}).get("closest")
                    if snap:
                        res["archive"] = snap.get("url")
                        res["archive_date"] = snap.get("timestamp")
            except Exception:
                continue

    # ------------------------------------------------------------------ #
    #  Affichage
    # ------------------------------------------------------------------ #
    def _afficher_resume(self):
        total = len(self.found) + len(self.not_found) + len(self.errors)
        table = Table(box=None, show_header=False)
        table.add_column("", style="bold")
        table.add_column("")
        table.add_row("[green]✓ Profils trouvés[/green]", str(len(self.found)))
        table.add_row("[red]✗ Non trouvés[/red]", str(len(self.not_found)))
        table.add_row("[yellow]! Erreurs[/yellow]", str(len(self.errors)))
        table.add_row("[white]Total testé[/white]", str(total))
        console.print(Panel(table, title="[bold]RÉSULTATS[/bold]", border_style="bright_blue"))

        if self.details:
            console.print("\n[bold green]PROFILS AVEC MÉTADONNÉES :[/bold green]")
            t = Table(show_header=True)
            t.add_column("Site", style="green")
            t.add_column("Détail", style="white")
           