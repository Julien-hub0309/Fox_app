import argparse
import json
import re
import sys
import unicodedata
from urllib.parse import quote_plus, unquote
from urllib.request import Request, urlopen

# --------------------------------------------------------------------------
#  BASE LOCALE — catégories, puis sites .onion
# --------------------------------------------------------------------------

CATEGORIES = {
    "recherche":    ["moteur", "recherche", "search", "engine", "annuaire",
                     "directory", "index", "google", "duckduckgo", "ahmia", "torch"],
    "social":       ["social", "reseau", "forum", "discussion", "facebook",
                     "reddit", "twitter", "communaute", "imageboard"],
    "presse":       ["presse", "news", "actualite", "journal", "journalisme",
                     "media", "bbc", "nytimes", "propublica", "guardian", "dw"],
    "email":        ["email", "mail", "messagerie", "courriel", "protonmail",
                     "riseup", "keybase", "chiffre", "pgp"],
    "donnees":      ["base", "donnee", "database", "db", "bd", "leak", "fuite",
                     "breach", "pwned", "dump", "dataset", "scraping", "archive",
                     "archives", "bibliotheque", "livre", "scientifique"],
    "darknet":      ["darknet", "dark", "web", "marche", "market", "onion",
                     "hidden", "wiki", "deepweb", "profond"],
    "privacy":      ["prive", "privacy", "anonymat", "anonyme", "tor", "vpn",
                     "chiffrement", "securite", "opsec", "anti-surveillance"],
    "dev":          ["dev", "developpement", "logiciel", "software", "code",
                     "programmation", "linux", "os", "git", "package", "apt"],
    "gouvernement": ["gouvernement", "government", "etat", "cia", "renseignement",
                     "espionnage", "institution", "officiel"],
    "crypto":       ["crypto", "bitcoin", "blockchain", "monnaie", "coin",
                     "wallet", "defi", "ethereum"],
    "adult":        ["adulte", "porn", "porno", "xxx", "nsfw", "18"],
}

SITES = [
    # ---- recherche / annuaires ----
    {"nom": "Ahmia", "cats": ["recherche", "darknet"],
     "url": "http://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion",
     "desc": "Moteur de recherche qui indexe les services .onion"},
    {"nom": "Torch", "cats": ["recherche", "darknet"],
     "url": "http://xmh57jrknzkhv6y3ls3ubitzfqnkrwxhopf5aygthi7d6rplyvk3noyd.onion",
     "desc": "Vieux moteur de recherche du réseau Tor, index très large"},
    {"nom": "DuckDuckGo (Tor)", "cats": ["recherche"],
     "url": "https://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion",
     "desc": "Version Tor du moteur généraliste, sans tracking"},
    {"nom": "The Hidden Wiki", "cats": ["darknet", "recherche", "annuaire"],
     "url": "http://zqktlwiuavvvqqt4ybvgvi7tyo4hjl5xgfuvpdf6otjiycgwqbym2qad.onion",
     "desc": "Annuaire historique du dark web, liens par catégories"},

    # ---- réseaux sociaux / forums ----
    {"nom": "Facebook", "cats": ["social"],
     "url": "https://www.facebookwkhpilnemxj7asaniu7vnjjbiltxjqhye3mhbshg7kx5tfyd.onion",
     "desc": "Miroir Tor officiel de Facebook"},
    {"nom": "Reddit", "cats": ["social", "forum"],
     "url": "https://www.reddittorjg6rue252oqsxryoxengawnmo46qy4kyii5wtqnwfj4ooad.onion",
     "desc": "Miroir Tor officiel de Reddit"},
    {"nom": "Twitter / X", "cats": ["social"],
     "url": "https://twitter3e4tixl4xyajtrzo62zg5vztmjuricljdp2c5kshju4avyoid.onion",
     "desc": "Miroir Tor de Twitter (service expiré en 2023, encore listé)"},

    # ---- presse ----
    {"nom": "BBC News", "cats": ["presse"],
     "url": "https://www.bbcnewsd73hkzno2ini43t4gblxvycyac5aw4gnv7t2rccijh7745uqd.onion",
     "desc": "Miroir Tor de la BBC, utile en zone censurée"},
    {"nom": "New York Times", "cats": ["presse"],
     "url": "https://nytimesn7cgmftshazwhfgzm37qxb44r64ytbb2dj3x62d2lljsciiyd.onion",
     "desc": "Miroir Tor du NYT"},
    {"nom": "ProPublica", "cats": ["presse"],
     "url": "https://p53lf57qovyuvwsc6xnrppyply3vtqm7l6pcobkmyqsiofyeznfu5uqd.onion",
     "desc": "Journalisme d'investigation, premier média à s'être mis sur Tor"},
    {"nom": "Deutsche Welle", "cats": ["presse"],
     "url": "https://dwnewsgngmhlplxy6o2twtfgjnrnjxbegbwqx6wnotdhkzt562tszfid.onion",
     "desc": "Miroir Tor de la radio publique allemande"},
    {"nom": "The Guardian (SecureDrop)", "cats": ["presse"],
     "url": "https://xp44cagis447k3lpb4wwhcqukix6cgqokbuys24vmxmbzmaq2gjvc2yd.onion",
     "desc": "Boîte à scoops anonyme du Guardian via SecureDrop"},

    # ---- email / messagerie ----
    {"nom": "ProtonMail", "cats": ["email", "privacy"],
     "url": "https://protonmailrmez3lotccipshtkleegetolb73fuirgj7r4o4vfu7ozyd.onion",
     "desc": "Email chiffré suisse, accessible sans sortir de Tor"},
    {"nom": "Riseup", "cats": ["email", "privacy"],
     "url": "https://vww6ybal4bd7szmgncyruucpgfkqahzddi37ktceo3ah7ngmcopnpyyd.onion",
     "desc": "Email et outils militants, liste d'adresses signée cryptographiquement"},
    {"nom": "Keybase", "cats": ["email", "privacy"],
     "url": "https://keybase5wmilwokqirssclfnsqrjdsi7jdir5wy7y7iu3tanwmtp6oid.onion",
     "desc": "Messagerie et preuve d'identité, accessible via Tor"},

    # ---- fuites / bases de données ----
    {"nom": "BreachForums", "cats": ["donnees", "leak", "forum", "darknet"],
     "url": "https://breached65xqh64s7xbkvqgg7bmj4nj7656hcb7x4g42x753r7zmejqd.onion",
     "desc": "Forum de référence pour les fuites de bases de données"},

    # ---- archives ----
    {"nom": "Internet Archive", "cats": ["donnees", "archives", "presse"],
     "url": "https://archiveiya74codqgiixo33q62qlrqtkgber57h5456jw5gv2v2ffcpad.onion",
     "desc": "Wayback Machine et bibliothèque numérique, en .onion"},

    # ---- privacy / dev ----
    {"nom": "The Tor Project", "cats": ["privacy", "dev"],
     "url": "http://2gzyxa5ihm7nsggfxnu52rck2vv4rvmdlkiu3zzui5du4xyclen53wid.onion",
     "desc": "Site officiel du projet Tor, docs et téléchargements"},

    # ---- gouvernement ----
    {"nom": "CIA", "cats": ["gouvernement"],
     "url": "https://ciadotgov4sjwlzihbbgxnqg3xiyrg7so2r2o3lt5wz5ypk4sxyjstad.onion",
     "desc": "Portail .onion de la CIA (World Factbook, dépôt de dossiers)"},
]

# --------------------------------------------------------------------------
#  Normalisation & scoring
# --------------------------------------------------------------------------

STOPWORDS = {
    "de", "du", "des", "la", "le", "les", "un", "une", "et", "ou", "pour",
    "sur", "en", "au", "aux", "d", "l", "a", "the", "of", "and", "in", "on",
    "site", "sites", "onion", "lien", "liens", "tor", "web",
}


def normaliser(txt: str) -> str:
    """Minuscule + suppression des accents + ponctuation -> espaces."""
    txt = unicodedata.normalize("NFKD", txt)
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    txt = txt.lower()
    return re.sub(r"[^a-z0-9]+", " ", txt).strip()


def tokeniser(txt: str) -> list:
    return [t for t in normaliser(txt).split()
            if t not in STOPWORDS and len(t) > 1]


def score(site: dict, tokens: list) -> int:
    """Score de pertinence d'un site pour la requête."""
    sac = normaliser(" ".join([site["nom"], site["desc"], " ".join(site["cats"])]))
    sac += " " + normaliser(" ".join(
        " ".join(CATEGORIES[c]) for c in site["cats"] if c in CATEGORIES))
    mots = set(sac.split())

    total = 0
    for t in tokens:
        if t in mots:
            total += 3
        elif len(t) >= 4 and any(
            (m.startswith(t) or t.startswith(m)) for m in mots if len(m) >= 4
        ):
            total += 1
    return total


def chercher_en_local(requete: str, limite: int) -> list:
    tokens = tokeniser(requete)
    if not tokens:
        return []
    resultats = []
    for site in SITES:
        s = score(site, tokens)
        if s > 0:
            resultats.append((s, site))
    resultats.sort(key=lambda x: -x[0])
    return [s for _, s in resultats[:limite]]


# --------------------------------------------------------------------------
#  Recherche en ligne (Ahmia / OnionSearchEngine) — pas besoin de Tor
# --------------------------------------------------------------------------

MOTEURS = [
    ("Ahmia", "https://ahmia.fi/search/?q={q}"),
    ("OnionSearchEngine", "https://onionsearchengine.com/search.php?search={q}"),
]

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Firefox/128.0")


def extraire_onions(html: str) -> list:
    """Extrait et dédoublonne toutes les adresses .onion d'une page."""
    html = unquote(html).lower()
    trouves = re.findall(r"(?<![a-z2-7])([a-z2-7]{16,56}\.onion)", html)
    vus, uniques = set(), []
    for t in trouves:
        if t not in vus:
            vus.add(t)
            uniques.append(t)
    return uniques


def chercher_en_ligne(requete: str, limite: int) -> dict:
    q = quote_plus(requete)
    par_moteur = {}
    for nom, gabarit in MOTEURS:
        try:
            req = Request(gabarit.format(q=q), headers={"User-Agent": UA})
            with urlopen(req, timeout=20) as rep:
                html = rep.read().decode("utf-8", errors="ignore")
            par_moteur[nom] = extraire_onions(html)[:limite]
        except Exception as e:  # réseau, DNS, TLS, 5xx...
            par_moteur[nom] = {"erreur": str(e)}
    return par_moteur


# --------------------------------------------------------------------------
#  Affichage
# --------------------------------------------------------------------------

def couleur(code, txt, actif):
    return "\033[%sm%s\033[0m" % (code, txt) if actif else txt


def afficher_local(requete, resultats, tty):
    if not resultats:
        print("  Aucun site .onion connu ne correspond à « %s »." % requete)
        print("  Astuce : relance avec --online pour interroger Ahmia.")
        return
    for site in resultats:
        print("  %s  %s" % (
            couleur("1;36", site["nom"].ljust(26), tty),
            couleur("33", site["url"], tty)))
        print("      %s" % couleur("2", site["desc"], tty))


def afficher_en_ligne(requete, par_moteur, tty):
    total = 0
    for moteur, res in par_moteur.items():
        print("\n  [%s]" % couleur("1;35", moteur, tty))
        if isinstance(res, dict):  # erreur
            print("    ! %s" % res["erreur"])
            continue
        if not res:
            print("    (aucun résultat)")
            continue
        for url in res:
            total += 1
            print("    http://%s" % couleur("33", url, tty))
    return total


# --------------------------------------------------------------------------
#  Programme principal
# --------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(
        description="Trouve des adresses .onion à partir d'un thème.")
    p.add_argument("theme", nargs="*", help="thème recherché (ex: « fuites bases de données »)")
    p.add_argument("--online", action="store_true",
                   help="interroge aussi Ahmia et OnionSearchEngine")
    p.add_argument("--local-only", action="store_true", help="désactive la base locale")
    p.add_argument("--limit", type=int, default=10, help="nombre max de résultats (défaut: 10)")
    p.add_argument("--json", action="store_true", help="sortie JSON")
    p.add_argument("--list", action="store_true", help="liste toute la base locale")
    args = p.parse_args()

    tty = sys.stdout.isatty()

    if args.list:
        for site in SITES:
            print("%-26s %-70s  [%s]" % (site["nom"], site["url"], ",".join(site["cats"])))
        return

    requete = " ".join(args.theme).strip()
    if not requete:
        requete = input("Thème à rechercher : ").strip()
    if not requete:
        p.error("aucun thème fourni")

    local = [] if args.local_only else chercher_en_local(requete, args.limit)

    if args.json:
        sortie = {"requete": requete, "local": local}
        if args.online:
            sortie["online"] = chercher_en_ligne(requete, args.limit)
        print(json.dumps(sortie, ensure_ascii=False, indent=2))
        return

    print("\n%s" % couleur("1", "Thème : %s" % requete, tty))

    if not args.local_only:
        print("\n%s" % couleur("1;34", "— Base locale —", tty))
        afficher_local(requete, local, tty)

    if args.online:
        print("\n%s" % couleur("1;34", "— Recherche en ligne —", tty))
        afficher_en_ligne(requete, chercher_en_ligne(requete, args.limit), tty)
    elif not args.local_only:
        print("\n%s" % couleur("2", "(ajoute --online pour interroger Ahmia)", tty))

    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()