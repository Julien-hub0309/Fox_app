import socket
import urllib.request
import json
from core.base import JustradamusModule
from utile.display import console

class WebScanner(JustradamusModule):
    def scan_infra(self):
        console.print(f"[bold blue][🌐][/bold blue] Analyse d'infrastructure pour : {self.target}")
        results = {}
        try:
            # Résolution IP
            ip = socket.gethostbyname(self.target)
            results["IP"] = ip
            
            # FIX: remplace requests par urllib (stdlib pure, pas de dépendance externe)
            try:
                req = urllib.request.Request(
                    f"http://ip-api.com/json/{ip}",
                    headers={'User-Agent': 'Mozilla/5.0'}
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    geo = json.loads(resp.read().decode())
                    if geo.get("status") == "success":
                        results["Localisation"] = f"{geo.get('city')}, {geo.get('country')}"
                        results["ISP"] = geo.get("isp")
                        results["Organisation"] = geo.get("org")
            except Exception:
                results["Localisation"] = "Erreur API Géo"

            # Scan de ports
            open_ports = []
            for port in [21, 22, 80, 443, 8080]:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.5)
                    if s.connect_ex((ip, port)) == 0:
                        open_ports.append(port)

            # FIX: convertir la liste en string pour que display_results ne crashe pas
            results["Ports_Ouverts"] = ", ".join(map(str, open_ports)) if open_ports else "Aucun"

            self.save_finding("Web_Infra", results)
            self.display_results("Infrastructure Web", results)
            
        except socket.gaierror:
            console.print(f"[bold red][!] Impossible de résoudre le domaine : {self.target}[/bold red]")
        except Exception as e:
            console.print(f"[bold red][!] Erreur Web : {e}[/bold red]")