import requests
import base64
from utile.display import console

class URLAnalyzer:
    def __init__(self, url):
        self.url = url
        self.api_key = "b5c670ae139caa20e28ad1adad49ffb858cd0655450d4798686d1e3a4741ced6"

    def run_scan(self):
        console.print(f"[bold blue][*] Analyse VirusTotal pour : {self.url}[/bold blue]")
        url_id = base64.urlsafe_b64encode(self.url.encode()).decode().strip("=")
        endpoint = f"https://www.virustotal.com/api/v3/urls/{url_id}"
        headers = {"x-apikey": self.api_key}

        response = requests.get(endpoint, headers=headers)
        if response.status_code != 200:
            console.print("[bold red]❌ Erreur API ou URL non trouvée.[/bold red]")
            return

        stats = response.json()['data']['attributes']['last_analysis_stats']
        console.print(f"\n[green]✅ Safe : {stats['harmless']}[/green] | [yellow]⚠️ Suspect : {stats['suspicious']}[/yellow] | [red]🚫 Malveillant : {stats['malicious']}[/red]")

        if stats['malicious'] > 0:
            console.print("[bold red]🚨 VERDICT : DANGEREUX ![/bold red]")
        else:
            console.print("[bold green]✔️ VERDICT : LÉGITIME.[/bold green]")