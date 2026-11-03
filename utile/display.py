import urllib.request
import socket
from rich.console import Console
from rich.theme import Theme
from rich.panel import Panel
from rich.markup import escape

# Thème personnalisé avec l'orange pour les scans
custom_theme = Theme({
    "info": "bold cyan",
    "warning": "bold orange1", # Couleur Orange
    "error": "bold red",
    "success": "bold green",
    "target": "bold magenta"
})

console = Console(theme=custom_theme)

def get_public_ip():
    try:
        return urllib.request.urlopen('https://api4.ipify.org', timeout=3).read().decode('utf8')
    except Exception:
        return "Indisponible"

def get_hostname():
    try:
        return socket.gethostname()
    except Exception:
        return "Inconnu"

def build_banner_body(host_name, user_ip, flipper=None, esp32=None):
    """Contenu (markup rich) de la bannière Watch Fox.
    Partagé entre le mode CLI (print_banner) et l'accueil de l'interface Textual.
    `flipper` / `esp32` : markup du statut de la liaison (None = ligne masquée)."""
    lines = [
        "[bold cyan]🦊 Watch Fox 🦊[/bold cyan]",
        "[dim]Intelligence & Investigation Framework[/dim]",
        "──────────────────────────────────────────",
        f"[bold magenta]Device :[/bold magenta] [white]{escape(str(host_name))}[/white]",
        f"[bold magenta]IPv4   :[/bold magenta] [white]{escape(str(user_ip))}[/white]",
    ]
    if flipper is not None:
        lines.append(f"[bold magenta]Flipper:[/bold magenta] {flipper}")
    if esp32 is not None:
        lines.append(f"[bold magenta]ESP32  :[/bold magenta] {esp32}")
    return "\n".join(lines)

def make_banner(host_name, user_ip, flipper=None, esp32=None):
    return Panel.fit(build_banner_body(host_name, user_ip, flipper, esp32),
                     border_style="orange1")  # Bordure orange

def print_banner():
    console.print(make_banner(get_hostname(), get_public_ip()))