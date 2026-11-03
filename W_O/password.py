import math
import secrets
import string
from utile.display import console

class PasswordAnalyzer:
    def __init__(self, target=None):
        # target n'est pas forcément utile ici mais garde la structure pour la cohérence
        self.target = target

    def generer_robuste(self, longueur=16):
        caracteres = string.ascii_letters + string.digits + string.punctuation
        while True:
            mdp = ''.join(secrets.choice(caracteres) for _ in range(longueur))
            if (any(c.islower() for c in mdp) and any(c.isupper() for c in mdp)
                and any(c.isdigit() for c in mdp) and any(c in string.punctuation for c in mdp)):
                return mdp

    def evaluer(self, mdp):
        jeu = 0
        if any(c.islower() for c in mdp): jeu += 26
        if any(c.isupper() for c in mdp): jeu += 26
        if any(c.isdigit() for c in mdp): jeu += 10
        if any(c in string.punctuation for c in mdp): jeu += 32
        
        longueur = len(mdp)
        entropie = longueur * math.log2(jeu) if jeu > 0 else 0
        tentatives_par_seconde = 10_000_000_000
        secondes = (jeu ** longueur) / tentatives_par_seconde
        return {"entropie": entropie, "temps": secondes}

    def run_scan(self):
        # On demande le mot de passe ici si non fourni au début
        mdp = console.input("[bold yellow]➤ Entrez le mot de passe à tester : [/bold yellow]")
        analyse = self.evaluer(mdp)
        
        console.print(f"\n[bold cyan]--- Analyse de sécurité ---[/bold cyan]")
        console.print(f"Entropie : [bold]{analyse['entropie']:.2f} bits[/bold]")
        
        if analyse['entropie'] < 60:
            console.print("[bold red]⚠️ SÉCURITÉ INSUFFISANTE[/bold red]")
            suggestion = self.generer_robuste()
            console.print(f"👉 Suggestion : [bold green]{suggestion}[/bold green]")
        else:
            console.print("[bold green]✅ Mot de passe robuste[/bold green]")