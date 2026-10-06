import re
import requests
from core.base import JustradamusModule
from core.config import get_random_header, TIMEOUT
from utile.display import console
from rich.panel import Panel
from rich.table import Table


class UsernameOSINT(JustradamusModule):
    def __init__(self, target, proxy=None):
        super().__init__(target, proxy)
        # Correction : On définit explicitement l'attribut proxy
        self.proxy = proxy 
        self.username = target.lower().strip().replace('@', '')
        self.clean = re.sub(r'[^a-zA-Z0-9_-]', '', self.username)
        self.found = []
        self.not_found = []
        self.errors = []

    def _print_section(self, title):
        console.print(f"\n[bold cyan][★ {title} ★][/bold cyan]")

    def check_site(self, site_name, url_template, not_found_texts=None):
        """Méthode générique pour vérifier un site."""
        url = url_template.format(username=self.username, clean=self.clean)
        headers = get_random_header()
        # Désormais self.proxy est bien défini
        proxy = self.proxy
        try:
            r = requests.get(url, headers=headers, proxies=proxy, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code == 200:
                if not_found_texts:
                    content = r.text.lower()
                    for text in not_found_texts:
                        if text.lower() in content:
                            console.print(f"[error][✗][/error] {site_name}")
                            self.not_found.append(site_name)
                            return
                console.print(f"[success][✓][/success] [bold]{site_name:<15}[/bold] [white]{url}[/white]")
                self.found.append((site_name, url))
                return
            console.print(f"[error][✗][/error] {site_name}")
            self.not_found.append(site_name)
        except Exception:
            console.print(f"[warning][!][/warning] {site_name}: Timeout/Block")
            self.errors.append(site_name)

    # ==================== RÉSEAUX SOCIAUX ====================

    def check_twitter(self):
        self.check_site("Twitter/X", "https://nitter.net/{username}",
                        ["this user does not exist", "not found"])

    def check_instagram(self):
        self.check_site("Instagram", "https://www.instagram.com/{username}/",
                        ["not found", "unavailable", "doesn't exist"])

    def check_tiktok(self):
        self.check_site("TikTok", "https://www.tiktok.com/@{username}",
                        ["couldn't find this account", "not found"])

    def check_facebook(self):
        self.check_site("Facebook", "https://www.facebook.com/{username}",
                        ["this content isn't available", "not found"])

    def check_reddit(self):
        self.check_site("Reddit", "https://www.reddit.com/user/{username}/",
                        ["not found", "sorry"])

    def check_youtube(self):
        self.check_site("YouTube", "https://www.youtube.com/@{username}",
                        ["not found", "404"])

    def check_twitch(self):
        self.check_site("Twitch", "https://www.twitch.tv/{username}",
                        ["sorry", "not found"])

    def check_pinterest(self):
        self.check_site("Pinterest", "https://www.pinterest.com/{username}/",
                        ["not found", "sorry"])

    def check_snapchat(self):
        self.check_site("Snapchat", "https://snapchat.com/add/{username}",
                        ["not found", "explore"])

    def check_tumblr(self):
        self.check_site("Tumblr", "https://{username}.tumblr.com",
                        ["not found", "404"])

    def check_mastodon(self):
        self.check_site("Mastodon", "https://mastodon.social/@{username}",
                        ["not found", "404"])

    # ==================== DEV & TECH ====================

    def check_github(self):
        self.check_site("GitHub", "https://github.com/{username}",
                        ["not found", "404"])

    def check_gitlab(self):
        self.check_site("GitLab", "https://gitlab.com/{username}",
                        ["not found", "404", "doesn't exist"])

    def check_bitbucket(self):
        self.check_site("Bitbucket", "https://bitbucket.org/{username}/",
                        ["not found", "404"])

    def check_devto(self):
        self.check_site("Dev.to", "https://dev.to/{username}",
                        ["not found", "404"])

    def check_dockerhub(self):
        self.check_site("Docker Hub", "https://hub.docker.com/u/{username}",
                        ["not found", "404"])

    def check_npm(self):
        self.check_site("NPM", "https://www.npmjs.com/~{username}",
                        ["not found", "404"])

    def check_pypi(self):
        self.check_site("PyPI", "https://pypi.org/user/{username}/",
                        ["not found", "404", "page not found"])

    def check_codepen(self):
        self.check_site("CodePen", "https://codepen.io/{username}",
                        ["not found", "404"])

    def check_replit(self):
        self.check_site("Replit", "https://replit.com/@{username}",
                        ["not found", "404"])

    def check_kaggle(self):
        self.check_site("Kaggle", "https://www.kaggle.com/{username}",
                        ["not found", "404"])

    def check_leetcode(self):
        self.check_site("LeetCode", "https://leetcode.com/{username}/",
                        ["not found", "404"])

    def check_hackerrank(self):
        self.check_site("HackerRank", "https://www.hackerrank.com/{username}",
                        ["not found", "404"])

    def check_hackthebox(self):
        self.check_site("HackTheBox", "https://app.hackthebox.com/users/{username}",
                        ["not found", "404"])

    # ==================== BLOG & CONTENU ====================

    def check_medium(self):
        self.check_site("Medium", "https://medium.com/@{username}",
                        ["not found", "404"])

    def check_substack(self):
        self.check_site("Substack", "https://{username}.substack.com",
                        ["not found", "404"])

    def check_deviantart(self):
        self.check_site("DeviantArt", "https://www.deviantart.com/{username}",
                        ["not found", "404"])

    def check_vimeo(self):
        self.check_site("Vimeo", "https://vimeo.com/{username}",
                        ["not found", "404"])

    def check_flickr(self):
        self.check_site("Flickr", "https://www.flickr.com/people/{username}/",
                        ["not found", "404"])

    def check_dailymotion(self):
        self.check_site("Dailymotion", "https://www.dailymotion.com/{username}",
                        ["not found", "404"])

    # ==================== GAMING ====================

    def check_steam(self):
        self.check_site("Steam", "https://steamcommunity.com/id/{username}",
                        ["the specified profile could not be found"])

    def check_minecraft(self):
        self.check_site("NameMC", "https://namemc.com/profile/{username}",
                        ["not found", "no profile"])

    def check_roblox(self):
        self.check_site("Roblox", "https://www.roblox.com/user.aspx?username={username}",
                        ["not found", "page cannot be found"])

    def check_chesscom(self):
        self.check_site("Chess.com", "https://www.chess.com/member/{username}",
                        ["not found", "404"])

    def check_lichess(self):
        self.check_site("Lichess", "https://lichess.org/@/{username}",
                        ["not found", "404"])

    def check_spotify(self):
        self.check_site("Spotify", "https://open.spotify.com/user/{username}",
                        ["not found", "404"])

    def check_soundcloud(self):
        self.check_site("SoundCloud", "https://soundcloud.com/{username}",
                        ["not found", "404"])

    # ==================== PROFILS & BIO ====================

    def check_aboutme(self):
        self.check_site("About.me", "https://about.me/{username}",
                        ["there is no one", "not found"])

    def check_linktree(self):
        self.check_site("Linktree", "https://linktr.ee/{username}",
                        ["not found", "doesn't exist"])

    def check_carrd(self):
        self.check_site("Carrd", "https://{username}.carrd.co",
                        ["not found", "404"])

    def check_keybase(self):
        self.check_site("Keybase", "https://keybase.io/{username}",
                        ["not found", "404"])

    def check_gravatar(self):
        self.check_site("Gravatar", "https://gravatar.com/{username}",
                        ["not found", "404"])

    def check_slideshare(self):
        self.check_site("SlideShare", "https://www.slideshare.net/{username}",
                        ["not found", "404"])

    # ==================== DONS ====================

    def check_patreon(self):
        self.check_site("Patreon", "https://www.patreon.com/{username}",
                        ["not found", "404"])

    def check_ko_fi(self):
        self.check_site("Ko-fi", "https://ko-fi.com/{username}",
                        ["not found", "404"])

    def check_buymeacoffee(self):
        self.check_site("BuyMeACoffee", "https://www.buymeacoffee.com/{username}",
                        ["not found", "404"])

    def check_tipeee(self):
        self.check_site("Tipeee", "https://fr.tipeee.com/{username}",
                        ["not found", "404"])

    def check_producthunt(self):
        self.check_site("Product Hunt", "https://www.producthunt.com/@{username}",
                        ["not found", "404"])

    # ==================== ADULTES ====================

    def check_onlyfans(self):
        self.check_site("OnlyFans", "https://onlyfans.com/{username}",
                        ["not found", "404"])

    def check_fansly(self):
        self.check_site("Fansly", "https://fansly.com/{username}",
                        ["not found", "404"])

    def check_manyvids(self):
        self.check_site("ManyVids", "https://www.manyvids.com/Profile/{username}/",
                        ["not found", "404"])

    def check_chaturbate(self):
        self.check_site("Chaturbate", "https://chaturbate.com/{username}/",
                        ["not found", "404", "page not found"])

    def check_pornhub(self):
        self.check_site("Pornhub", "https://www.pornhub.com/users/{username}",
                        ["not found", "doesn't exist"])

    def check_xvideos(self):
        self.check_site("XVideos", "https://www.xvideos.com/profiles/{username}",
                        ["not found", "404"])

    def check_cam4(self):
        self.check_site("Cam4", "https://www.cam4.com/{username}",
                        ["not found", "404"])

    def check_stripchat(self):
        self.check_site("StripChat", "https://stripchat.com/{username}",
                        ["not found", "404"])

    def check_bongacams(self):
        self.check_site("BongaCams", "https://fr.bongacams.com/profile/{username}",
                        ["not found", "404"])

    # ==================== SCAN PRINCIPAL ====================

    def run_scan(self):
        console.print(Panel.fit(
            f"[bold cyan]🔍 OSINT USERNAME SCANNER[/bold cyan]\n"
            f"[dim]Pseudo cible: [/dim][bold white]{self.username}[/bold white]",
            border_style="cyan"
        ))

        self._print_section("RÉSEAUX SOCIAUX")
        self.check_twitter()
        self.check_instagram()
        self.check_tiktok()
        self.check_facebook()
        self.check_reddit()
        self.check_youtube()
        self.check_twitch()
        self.check_pinterest()
        self.check_snapchat()
        self.check_tumblr()
        self.check_mastodon()

        self._print_section("DEVELOPPEMENT & TECH")
        self.check_github()
        self.check_gitlab()
        self.check_bitbucket()
        self.check_devto()
        self.check_dockerhub()
        self.check_npm()
        self.check_pypi()
        self.check_codepen()
        self.check_replit()
        self.check_kaggle()
        self.check_leetcode()
        self.check_hackerrank()
        self.check_hackthebox()

        self._print_section("BLOG & CONTENU")
        self.check_medium()
        self.check_substack()
        self.check_deviantart()
        self.check_vimeo()
        self.check_flickr()
        self.check_dailymotion()

        self._print_section("GAMING")
        self.check_steam()
        self.check_minecraft()
        self.check_roblox()
        self.check_chesscom()
        self.check_lichess()
        self.check_spotify()
        self.check_soundcloud()

        self._print_section("PROFILS & BIO LINKS")
        self.check_aboutme()
        self.check_linktree()
        self.check_carrd()
        self.check_keybase()
        self.check_gravatar()
        self.check_slideshare()

        self._print_section("DONS & CROWDFUNDING")
        self.check_patreon()
        self.check_ko_fi()
        self.check_buymeacoffee()
        self.check_tipeee()
        self.check_producthunt()

        self._print_section("🔞 PLATEFORMES ADULTES")
        self.check_onlyfans()
        self.check_fansly()
        self.check_manyvids()
        self.check_chaturbate()
        self.check_pornhub()
        self.check_xvideos()
        self.check_cam4()
        self.check_stripchat()
        self.check_bongacams()

        # Sauvegarde
        summary = {
            "username": self.username,
            "found": [{"site": s, "url": u} for s, u in self.found],
            "not_found": self.not_found,
            "errors": self.errors,
            "total_found": len(self.found)
        }
        path = self.save_finding("Username_Intel", summary)

        # Résumé
        total = len(self.found) + len(self.not_found) + len(self.errors)
        table = Table(box=None, show_header=False)
        table.add_column("", style="bold")
        table.add_column("")
        table.add_row("[green]✓ Profils trouvés[/green]", str(len(self.found)))
        table.add_row("[red]✗ Non trouvés[/red]", str(len(self.not_found)))
        table.add_row("[yellow]! Erreurs[/yellow]", str(len(self.errors)))
        table.add_row("[white]Total testé[/white]", str(total))
        table.add_row("[dim]💾 Rapport[/dim]", path)
        console.print(Panel(table, title="[bold]RÉSULTATS[/bold]", border_style="bright_blue"))

        if self.found:
            console.print("\n[bold green]LIENS DIRECTS:[/bold green]")
            for site, url in self.found[:10]:
                console.print(f"[green]{site:<15}[/green] [white]{url}[/white]")
            if len(self.found) > 10:
                console.print(f"[yellow]... et {len(self.found) - 10} autres[/yellow]")