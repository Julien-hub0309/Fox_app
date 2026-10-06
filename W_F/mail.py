import hashlib
import requests
import dns.resolver
from urllib.parse import quote_plus
from core.base import JustradamusModule
from core.config import get_random_header, TIMEOUT
from utile.display import console
from rich.panel import Panel
from rich.table import Table

class EmailOSINT(JustradamusModule):
    def __init__(self, target, proxy=None):
        # On initialise la classe parente
        super().__init__(target, proxy)
        # On s'assure que self.proxy est défini au cas où JustradamusModule ne le ferait pas
        self.proxy = proxy 
        self.email = target.lower().strip()
        self.username = self.email.split('@')[0] if '@' in self.email else self.email
        self.domain = self.email.split('@')[1] if '@' in self.email else ''
        self.found = []
        self.not_found = []
        self.errors = []

    def _get(self, url):
        headers = get_random_header()
        # L'erreur arrivait ici car self.proxy n'existait pas
        proxy = self.proxy 
        try:
            r = requests.get(url, headers=headers, proxies=proxy, timeout=TIMEOUT, allow_redirects=True)
            return r
        except Exception:
            return None

    def _print_found(self, source, info=""):
        console.print(f"[success][✓][/success] [bold]{source}[/bold] [white]{info}[/white]")
        self.found.append(f"{source}: {info}")

    def _print_not_found(self, source):
        console.print(f"[error][✗][/error] {source}")
        self.not_found.append(source)

    def _print_error(self, source):
        console.print(f"[warning][!][/warning] {source}: Timeout/Erreur")
        self.errors.append(source)

    def _print_section(self, title):
        console.print(f"\n[bold cyan][★ {title} ★][/bold cyan]")

    def check_hibp_web(self):
        r = self._get(f"https://haveibeenpwned.com/unifiedsearch/{quote_plus(self.email)}")
        if r and r.status_code == 200:
            try:
                data = r.json()
                breaches = [b['Name'] for b in data.get('Breaches', [])]
                if breaches:
                    self._print_found("Have I Been Pwned", f"{len(breaches)} fuites: {', '.join(breaches[:3])}")
                    return
            except Exception:
                pass
        self._print_not_found("Have I Been Pwned")

    def check_leakcheck(self):
        r = self._get(f"https://leakcheck.io/api/public?check={quote_plus(self.email)}")
        if r and r.status_code == 200:
            try:
                data = r.json()
                if data.get('found'):
                    self._print_found("LeakCheck", f"{data.get('count', 0)} fuites")
                    return
            except Exception:
                pass
        self._print_not_found("LeakCheck")

    def check_psbdmp(self):
        r = self._get(f"https://psbdmp.ws/api/v3/search/{quote_plus(self.email)}")
        if r and r.status_code == 200:
            try:
                data = r.json()
                if data.get('count', 0) > 0:
                    self._print_found("Psbdmp.ws", f"{data['count']} dumps")
                    return
            except Exception:
                pass
        self._print_not_found("Psbdmp.ws")

    def check_breachdirectory(self):
        r = self._get(f"https://breachdirectory.org/api.php?query={quote_plus(self.email)}")
        if r and r.status_code == 200:
            try:
                data = r.json()
                if data.get('found') == 'true':
                    self._print_found("BreachDirectory", f"{data.get('count', 0)} résultats")
                    return
            except Exception:
                pass
        self._print_not_found("BreachDirectory")

    def check_emailrep(self):
        r = self._get(f"https://emailrep.io/{quote_plus(self.email)}")
        if r and r.status_code == 200:
            try:
                data = r.json()
                rep = data.get('reputation', 'unknown')
                susp = " [SUSPICIOUS]" if data.get('suspicious') else ""
                self._print_found("EmailRep", f"Rep: {rep}{susp}")
                return
            except Exception:
                pass
        self._print_not_found("EmailRep")

    def check_gravatar(self):
        email_hash = hashlib.md5(self.email.encode('utf-8').lower().strip()).hexdigest()
        r = self._get(f"https://www.gravatar.com/avatar/{email_hash}?d=404")
        if r and r.status_code != 404:
            self._print_found("Gravatar", f"https://www.gravatar.com/{email_hash}")
            return
        self._print_not_found("Gravatar")

    def check_dns(self):
        try:
            records = dns.resolver.resolve(self.domain, 'MX')
            mx_hosts = [str(r.exchange) for r in records]
            self._print_found("DNS/MX", f"Serveurs: {', '.join(mx_hosts[:2])}")
        except Exception:
            self._print_not_found("DNS/MX")

    def _check_social(self, site, url, not_found_texts=None):
        r = self._get(url)
        if r and r.status_code == 200:
            if not_found_texts:
                content = r.text.lower()
                for text in not_found_texts:
                    if text.lower() in content:
                        self._print_not_found(site)
                        return
            self._print_found(site, url)
            return
        self._print_not_found(site)

    def check_twitter(self):
        self._check_social("Twitter/X",
            f"https://nitter.net/{self.username.replace('.', '').replace('_', '')}",
            ["this user does not exist", "not found"])

    def check_reddit(self):
        self._check_social("Reddit",
            f"https://www.reddit.com/user/{self.username}/about.json",
            ["not found"])

    def check_github(self):
        gh_user = self.username.replace('.', '-').replace('_', '-')
        r = self._get(f"https://api.github.com/users/{gh_user}")
        if r and r.status_code == 200:
            try:
                data = r.json()
                self._print_found("GitHub", f"{data.get('html_url')} ({data.get('public_repos')} repos)")
                return
            except Exception:
                pass
        self._print_not_found("GitHub")

    def check_medium(self):
        self._check_social("Medium",
            f"https://medium.com/@{self.username}",
            ["not found", "404"])

    def check_steam(self):
        self._check_social("Steam",
            f"https://steamcommunity.com/id/{self.username}",
            ["the specified profile could not be found"])

    def check_onlyfans(self):
        self._check_social("OnlyFans",
            f"https://onlyfans.com/{self.username}",
            ["not found", "404"])

    def check_fansly(self):
        self._check_social("Fansly",
            f"https://fansly.com/{self.username}",
            ["not found", "404"])

    def check_chaturbate(self):
        self._check_social("Chaturbate",
            f"https://chaturbate.com/{self.username}/",
            ["not found", "404", "page not found"])

    def check_manyvids(self):
        self._check_social("ManyVids",
            f"https://www.manyvids.com/Profile/{self.username}/",
            ["not found", "404"])

    def run_scan(self):
        console.print(Panel.fit(
            f"[bold cyan]🔍 OSINT EMAIL SCANNER[/bold cyan]\n"
            f"[dim]Cible: [/dim][bold white]{self.email}[/bold white]\n"
            f"[dim]Utilisateur: [/dim][white]{self.username}[/white] | "
            f"[dim]Domaine: [/dim][white]{self.domain}[/white]",
            border_style="cyan"
        ))

        self._print_section("FUITES DE DONNÉES")
        self.check_hibp_web()
        self.check_leakcheck()
        self.check_psbdmp()
        self.check_breachdirectory()

        self._print_section("RÉPUTATION & VÉRIFICATIONS")
        self.check_emailrep()
        self.check_gravatar()
        self.check_dns()

        self._print_section("RÉSEAUX SOCIAUX & TECH")
        self.check_twitter()
        self.check_reddit()
        self.check_github()
        self.check_medium()
        self.check_steam()

        self._print_section("🔞 PLATEFORMES ADULTES")
        self.check_onlyfans()
        self.check_fansly()
        self.check_chaturbate()
        self.check_manyvids()

        summary = {
            "email": self.email,
            "username": self.username,
            "domain": self.domain,
            "found": self.found,
            "not_found": self.not_found,
            "errors": self.errors,
            "total_found": len(self.found)
        }
        path = self.save_finding("Email_Intel", summary)

        table = Table(box=None, show_header=False)
        table.add_column("", style="bold")
        table.add_column("")
        table.add_row("[green]✓ Trouvé[/green]", str(len(self.found)))
        table.add_row("[red]✗ Non trouvé[/red]", str(len(self.not_found)))
        table.add_row("[yellow]! Erreurs[/yellow]", str(len(self.errors)))
        table.add_row("[dim]💾 Rapport[/dim]", path)
        console.print(Panel(table, title="[bold]RÉSUMÉ[/bold]", border_style="bright_blue"))