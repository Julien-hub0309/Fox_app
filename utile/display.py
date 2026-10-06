import urllib.request
import socket
from rich.console import Console
from rich.theme import Theme
from rich.panel import Panel

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
    except:
        return "Indisponible"

def get_hostname():
    try:
        return socket.gethostname()
    except:
        return "Inconnu"

def print_banner():
    user_ip = get_public_ip()
    host_name = get_hostname()
    
    banner_text = (
        "[bold cyan]🦊 Watch Fox 🦊[/bold cyan]\n"
        "[dim]Intelligence & Investigation Framework[/dim]\n"
        "──────────────────────────────────────────\n"
        f"[bold magenta]Device :[/bold magenta] [white]{host_name}[/white]\n"
        f"[bold magenta]IPv4   :[/bold magenta] [white]{user_ip}[/white]"
    )
    
    banner = Panel.fit(banner_text, border_style="orange1") # Bordure orange
    console.print(banner)
