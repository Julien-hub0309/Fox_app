import requests
import json
import os
from concurrent.futures import ThreadPoolExecutor
from core.config import get_random_header, TIMEOUT

class OSINTScanner:
    def __init__(self, target, proxy=None):
        self.target = target
        self.proxy = {"http": proxy, "https": proxy} if proxy else None
        # Cette ligne appelle la méthode ci-dessous
        self.services = self._load_services() 

    def _load_services(self):
        """Charge la base de données des sites depuis le fichier JSON."""
        # On définit le chemin vers data/sites.json
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(base_path, "data", "sites.json")
        
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[!] Erreur lors de la lecture du JSON : {e}")
                return {}
        else:
            print(f"[!] Fichier de configuration introuvable : {path}")
            return {}

    def check_site(self, name, info):
        """Vérifie l'existence avec détection de faux positifs[cite: 6]."""
        url = info["url"].format(self.target)
        try:
            response = requests.get(
                url, 
                headers=get_random_header(), 
                proxies=self.proxy, 
                timeout=TIMEOUT,
                allow_redirects=True
            )
            
            if response.status_code == 200:
                # Si le texte d'erreur est présent, on considère que le compte n'existe pas[cite: 6]
                if info["error_body"] and info["error_body"].lower() in response.text.lower():
                    return name, url, False
                return name, url, True
            return name, url, False
        except Exception:
            return name, url, None

    def start_scan(self):
        """Exécution parallèle du scan[cite: 6]."""
        results = []
        if not self.services:
            return results

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(self.check_site, n, i) for n, i in self.services.items()]
            for future in futures:
                results.append(future.result())
        return results