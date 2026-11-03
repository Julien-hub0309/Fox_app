import base64
import os

import requests

from utile.display import console


class URLAnalyzer:
    """Analyse d'URL via VirusTotal.
    La clé API se lit dans la variable d'environnement VT_API_KEY
    (jamais en dur dans le code)."""

    def __init__(self, url):
        self.url = url
        self.api_key = os.environ.get("VT_API_KEY", "")

    def scan(self):
        """Renvoie le dict de stats VirusTotal (utilisé par l'interface)."""
        if not self.api_key:
            raise RuntimeError("Clé absente : définis la variable VT_API_KEY")
        url_id = base64.urlsafe_b64encode(self.url.encode()).decode().strip("=")
        r = requests.get(f"https://www.virustotal.com/api/v3/urls/{url_id}",
                         headers={"x-apikey": self.api_key}, timeout=15)
        if r.status_code == 404:
            raise RuntimeError("URL inconnue de VirusTotal (jamais analysée)")
        if r.status_code != 200:
            raise RuntimeError(f"Erreur API VirusTotal ({r.status_code})")
        return r.json()["data"]["attributes"]["last_analysis_stats"]

    def run_scan(self):
        """Mode CLI : conservé pour compatibilité."""
        console.print(f"[bold blue][*] Analyse VirusTotal pour : {self.url}[/bold blue]")
        try:
            stats = self.scan()
        except Exception as e:
            console.print(f"[bold red]❌ {e}[/bold red]")
            return
        console.print(f"\n[green]✅ Safe : {stats['harmless']}[/green] | "
                      f"[yellow]⚠️ Suspect : {stats['suspicious']}[/yellow] | "
                      f"[red]🚫 Malveillant : {stats['malicious']}[/red]")
        if stats["malicious"] > 0:
            console.print("[bold red]🚨 VERDICT : DANGEREUX ![/bold red]")
        else:
            console.print("[bold green]✔️ VERDICT : LÉGITIME.[/bold green]")