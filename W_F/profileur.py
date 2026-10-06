import requests
import re
import json
import time
import random
import urllib.parse
from datetime import datetime
from rich.table import Table
from rich.panel import Panel


class Profileur:
    """Module de profilage de personne via OSINT"""
    
    def __init__(self, nom=None, prenom=None, age=None):
        self.nom = nom.upper() if nom else None
        self.prenom = prenom.capitalize() if prenom else None
        self.age = int(age) if age and str(age).isdigit() else None
        self.console = None
        self.resultats = {
            "informations": {},
            "reseaux_sociaux": {},
            "emails_probables": [],
            "usernames_probables": [],
            "photos": [],
            "localisations": [],
            "profils_trouves": []
        }

    def set_console(self, console):
        """Définit la console Rich"""
        self.console = console

    def _print(self, message, style=""):
        """Affiche un message"""
        if self.console:
            if style:
                self.console.print(f"[{style}]{message}[/{style}]")
            else:
                self.console.print(message)
        else:
            print(message)

    def _input(self, prompt):
        """Demande une entrée"""
        if self.console:
            return self.console.input(prompt)
        return input(prompt)

    def generer_combinaisons(self):
        """Génère différentes combinaisons de recherche"""
        combinaisons = []
        
        if self.nom and self.prenom:
            # Combinaisons basiques
            combinaisons.append(f"{self.prenom} {self.nom}")
            combinaisons.append(f"{self.nom} {self.prenom}")
            
            # Sans espaces
            combinaisons.append(f"{self.prenom}{self.nom}")
            combinaisons.append(f"{self.nom}{self.prenom}")
            
            # Avec tirets
            combinaisons.append(f"{self.prenom}-{self.nom}")
            combinaisons.append(f"{self.nom}-{self.prenom}")
            
            # Avec points
            combinaisons.append(f"{self.prenom}.{self.nom}")
            
            # Username style
            combinaisons.append(f"{self.prenom.lower()}.{self.nom.lower()}")
            combinaisons.append(f"{self.prenom.lower()}{self.nom.lower()}")
            combinaisons.append(f"{self.nom.lower()}{self.prenom.lower()}")
            
            # Initiales
            combinaisons.append(f"{self.prenom[0]}{self.nom}")
            combinaisons.append(f"{self.prenom}{self.nom[0]}")
            combinaisons.append(f"{self.prenom[0]}.{self.nom}")
            
            # Avec âge si disponible
            if self.age:
                annee_naissance = datetime.now().year - self.age
                combinaisons.append(f"{self.prenom}{annee_naissance}")
                combinaisons.append(f"{self.prenom}{str(annee_naissance)[2:]}")
        
        return list(set(combinaisons))

    def generer_emails_probables(self):
        """Génère des emails probables"""
        domaines = ['gmail.com', 'outlook.com', 'hotmail.com', 'yahoo.fr', 
                  'yahoo.com', 'live.fr', 'orange.fr', 'free.fr', 'sfr.fr']
        
        emails = []
        
        if self.nom and self.prenom:
            formats = [
                f"{self.prenom.lower()}.{self.nom.lower()}",
                f"{self.nom.lower()}.{self.prenom.lower()}",
                f"{self.prenom.lower()}{self.nom.lower()}",
                f"{self.nom.lower()}{self.prenom.lower()}",
                f"{self.prenom[0].lower()}{self.nom.lower()}",
                f"{self.prenom.lower()}{self.nom[0].lower()}",
                f"{self.prenom.lower()}_{self.nom.lower()}",
                f"{self.nom.lower()}_{self.prenom.lower()}",
            ]
            
            if self.age:
                annee = datetime.now().year - self.age
                formats.append(f"{self.prenom.lower()}{annee}")
                formats.append(f"{self.prenom.lower()}{str(annee)[2:]}")
            
            for fmt in formats:
                for domaine in domaines:
                    emails.append(f"{fmt}@{domaine}")
        
        self.resultats["emails_probables"] = emails[:20]
        return emails[:20]

    def analyser_noms_utilisateur(self):
        """Génère des noms d'utilisateur probables"""
        usernames = []
        
        if self.nom and self.prenom:
            bases = [
                f"{self.prenom.lower()}{self.nom.lower()}",
                f"{self.nom.lower()}{self.prenom.lower()}",
                f"{self.prenom.lower()}.{self.nom.lower()}",
                f"{self.nom.lower()}.{self.prenom.lower()}",
                f"{self.prenom[0].lower()}{self.nom.lower()}",
                f"{self.prenom.lower()}{self.nom[0].lower()}",
                f"{self.prenom.lower()}_{self.nom.lower()}",
            ]
            
            if self.age:
                annee = datetime.now().year - self.age
                for base in bases[:3]:
                    usernames.append(f"{base}{annee}")
                    usernames.append(f"{base}{str(annee)[2:]}")
            
            usernames.extend(bases)
        
        self.resultats["usernames_probables"] = list(set(usernames))
        return self.resultats["usernames_probables"]

    def rechercher_google_dorks(self):
        """Génère des Google Dorks pour la recherche"""
        dorks = []
        
        if self.nom and self.prenom:
            nom_complet = f"{self.prenom} {self.nom}"
            
            # Dorks de base
            dorks.append(f'"{nom_complet}"')
            dorks.append(f'"{nom_complet}" site:facebook.com')
            dorks.append(f'"{nom_complet}" site:linkedin.com')
            dorks.append(f'"{nom_complet}" site:instagram.com')
            dorks.append(f'"{nom_complet}" site:twitter.com')
            dorks.append(f'"{nom_complet}" site:tiktok.com')
            
            # Dorks avancés
            dorks.append(f'"{nom_complet}" filetype:pdf')
            dorks.append(f'"{nom_complet}" intitle:"profil"')
            dorks.append(f'"{nom_complet}" inurl:profil')
            
            # Si âge connu
            if self.age:
                annee = datetime.now().year - self.age
                dorks.append(f'"{nom_complet}" {self.age}')
                dorks.append(f'"{nom_complet}" {annee}')
        
        return dorks

    def verifier_reseaux_sociaux(self):
        """Génère les URLs des réseaux sociaux"""
        reseaux = {}
        
        if self.nom and self.prenom:
            reseaux = {
                "Facebook": f"https://www.facebook.com/public/{self.prenom}-{self.nom}",
                "LinkedIn": f"https://www.linkedin.com/pub/dir/{self.prenom}/{self.nom}",
                "Instagram": [
                    f"https://www.instagram.com/{self.prenom.lower()}{self.nom.lower()}/",
                    f"https://www.instagram.com/{self.nom.lower()}.{self.prenom.lower()}/",
                    f"https://www.instagram.com/{self.prenom.lower()}.{self.nom.lower()}/"
                ],
                "Twitter/X": [
                    f"https://twitter.com/{self.prenom.lower()}{self.nom.lower()}",
                    f"https://twitter.com/{self.nom.lower()}{self.prenom.lower()}",
                    f"https://twitter.com/{self.prenom.lower()}_{self.nom.lower()}"
                ],
                "TikTok": [
                    f"https://www.tiktok.com/@{self.prenom.lower()}{self.nom.lower()}",
                    f"https://www.tiktok.com/@{self.nom.lower()}.{self.prenom.lower()}"
                ],
                "GitHub": f"https://github.com/{self.prenom.lower()}{self.nom.lower()}",
                "Reddit": f"https://www.reddit.com/user/{self.prenom.lower()}{self.nom.lower()}"
            }
        
        self.resultats["reseaux_sociaux"] = reseaux
        return reseaux

    def rechercher_annuaires(self):
        """URLs des annuaires français"""
        if not self.nom or not self.prenom:
            return {}
            
        return {
            "PagesBlanches": f"https://www.pagesblanches.fr/recherche?quoiqui={self.prenom}+{self.nom}",
            "118000": f"https://www.118000.fr/recherche?text={self.prenom}+{self.nom}",
            "PageJaunes": f"https://www.pagesjaunes.fr/recherche/{self.prenom}-{self.nom}",
            "Mappy": f"https://fr.mappy.com/recherche/{self.prenom}-{self.nom}"
        }

    def executer_recherche_complete(self):
        """Exécute toutes les recherches"""
        self._print("[bold blue][*] Génération des combinaisons...[/bold blue]")
        self.generer_combinaisons()
        time.sleep(0.3)
        
        self._print("[bold blue][*] Génération des emails probables...[/bold blue]")
        self.generer_emails_probables()
        time.sleep(0.3)
        
        self._print("[bold blue][*] Analyse des noms d'utilisateur...[/bold blue]")
        self.analyser_noms_utilisateur()
        time.sleep(0.3)
        
        self._print("[bold blue][*] Recherche réseaux sociaux...[/bold blue]")
        self.verifier_reseaux_sociaux()
        time.sleep(0.3)
        
        self._print("[bold blue][*] Préparation des Google Dorks...[/bold blue]")
        self.rechercher_google_dorks()

    def afficher_resultats(self):
        """Affiche les résultats avec Rich"""
        if not self.console:
            return self.afficher_resultats_texte()
        
        # Panel principal
        self.console.print(Panel.fit(
            f"[bold green]Résultats du profilage[/bold green]\n"
            f"[cyan]{self.prenom} {self.nom}[/cyan]" + 
            (f" [dim](~{self.age} ans)[/dim]" if self.age else ""),
            border_style="green"
        ))
        
        # Informations de base
        table_info = Table(title="Informations de base", show_header=False)
        table_info.add_column("Champ", style="cyan")
        table_info.add_column("Valeur", style="white")
        
        table_info.add_row("Nom", self.nom)
        table_info.add_row("Prénom", self.prenom)
        if self.age:
            table_info.add_row("Âge", str(self.age))
            table_info.add_row("Année naissance", str(datetime.now().year - self.age))
        
        self.console.print(table_info)
        
        # Combinaisons
        if self.resultats.get("combinaisons"):
            table_combo = Table(title="Combinaisons de recherche", show_header=False)
            table_combo.add_column("N°", style="dim", width=3)
            table_combo.add_column("Combinaison", style="green")
            
            for i, combo in enumerate(self.generer_combinaisons()[:10], 1):
                table_combo.add_row(str(i), combo)
            self.console.print(table_combo)
        
        # Emails probables
        if self.resultats.get("emails_probables"):
            table_emails = Table(title="Emails probables", show_header=False)
            table_emails.add_column("N°", style="dim", width=3)
            table_emails.add_column("Email", style="yellow")
            
            for i, email in enumerate(self.resultats["emails_probables"][:10], 1):
                table_emails.add_row(str(i), email)
            self.console.print(table_emails)
        
        # Usernames
        if self.resultats.get("usernames_probables"):
            table_users = Table(title="Noms d'utilisateur probables", show_header=False)
            table_users.add_column("N°", style="dim", width=3)
            table_users.add_column("Username", style="magenta")
            
            for i, username in enumerate(self.resultats["usernames_probables"][:10], 1):
                table_users.add_row(str(i), username)
            self.console.print(table_users)
        
        # Réseaux sociaux
        if self.resultats.get("reseaux_sociaux"):
            self.console.print("\n[bold cyan]🌐 Profils réseaux sociaux (URLs à vérifier)[/bold cyan]")
            
            for reseau, urls in self.resultats["reseaux_sociaux"].items():
                if isinstance(urls, list):
                    self.console.print(f"\n[bold]{reseau}:[/bold]")
                    for url in urls:
                        self.console.print(f"  🔗 {url}")
                else:
                    self.console.print(f"[bold]{reseau}:[/bold] 🔗 {urls}")
        
        # Google Dorks
        dorks = self.rechercher_google_dorks()
        if dorks:
            self.console.print("\n[bold cyan]🔎 Google Dorks[/bold cyan]")
            for i, dork in enumerate(dorks[:6], 1):
                url = f"https://www.google.com/search?q={urllib.parse.quote(dork)}"
                self.console.print(f"  {i}. [link={url}]{dork}[/link]")
        
        # Annuaires
        annuaires = self.rechercher_annuaires()
        if annuaires:
            self.console.print("\n[bold cyan]📖 Annuaires[/bold cyan]")
            for nom, url in annuaires.items():
                self.console.print(f"  • [link={url}]{nom}[/link]")
        
        # Recommandations
        self.console.print(Panel(
            "[bold yellow]⚠️ Recommandations:[/bold yellow]\n"
            "1. Copiez-collez les URLs dans votre navigateur\n"
            "2. Utilisez les Google Dorks pour affiner\n"
            "3. Vérifiez les photos avec TinEye ou Google Images\n"
            "4. Testez les emails avec des vérificateurs\n"
            "5. Respectez la vie privée et les lois",
            border_style="yellow"
        ))

    def afficher_resultats_texte(self):
        """Affiche les résultats sans Rich"""
        print(f"\n{'='*60}")
        print(f"RÉSULTATS DU PROFILAGE")
        print(f"{'='*60}")
        print(f"Nom: {self.nom}")
        print(f"Prénom: {self.prenom}")
        if self.age:
            print(f"Âge: {self.age}")
            print(f"Année naissance: {datetime.now().year - self.age}")
        
        print(f"\n--- Combinaisons ---")
        for i, combo in enumerate(self.generer_combinaisons()[:10], 1):
            print(f"{i}. {combo}")
        
        print(f"\n--- Emails probables ---")
        for email in self.resultats["emails_probables"][:10]:
            print(f"  {email}")
        
        print(f"\n--- Usernames ---")
        for username in self.resultats["usernames_probables"][:10]:
            print(f"  {username}")
        
        print(f"\n--- Réseaux sociaux ---")
        for reseau, urls in self.resultats["reseaux_sociaux"].items():
            print(f"{reseau}: {urls}")

    def sauvegarder_json(self):
        """Sauvegarde les résultats en JSON"""
        filename = f"profil_{self.prenom}_{self.nom}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        rapport = {
            "date": datetime.now().isoformat(),
            "cible": {
                "nom": self.nom,
                "prenom": self.prenom,
                "age": self.age,
                "annee_naissance_estimee": datetime.now().year - self.age if self.age else None
            },
            "combinaisons": self.generer_combinaisons(),
            "emails_probables": self.resultats["emails_probables"],
            "usernames_probables": self.resultats["usernames_probables"],
            "reseaux_sociaux": self.resultats["reseaux_sociaux"],
            "google_dorks": self.rechercher_google_dorks(),
            "annuaires": self.rechercher_annuaires()
        }
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(rapport, f, indent=2, ensure_ascii=False)
            self._print(f"\n[bold green]💾 Rapport sauvegardé: {filename}[/bold green]")
            return filename
        except Exception as e:
            self._print(f"\n[bold red]❌ Erreur: {e}[/bold red]")
            return None

    def run_scan(self):
        """Méthode principale compatible avec le framework"""
        try:
            from utile.display import console as main_console
            self.set_console(main_console)
        except:
            pass
        
        self._print(Panel.fit(
            "[bold red]🕵️ PROFILEUR OSINT[/bold red]\n"
            "[dim]Recherche de traces en ligne[/dim]",
            border_style="red"
        ))
        
        # Demande les informations
        if not self.nom:
            self.nom = self._input("[bold yellow]➤ NOM : [/bold yellow]").strip().upper()
        if not self.prenom:
            self.prenom = self._input("[bold yellow]➤ PRÉNOM : [/bold yellow]").strip().capitalize()
        if not self.age:
            age_input = self._input("[bold yellow]➤ ÂGE (optionnel) : [/bold yellow]").strip()
            self.age = int(age_input) if age_input.isdigit() else None
        
        if not self.nom or not self.prenom:
            self._print("[bold red]❌ Nom et prénom requis[/bold red]")
            return
        
        self._print(f"\n[bold blue][*] Profilage de: {self.prenom} {self.nom}[/bold blue]")
        
        # Exécution
        self.executer_recherche_complete()
        self.afficher_resultats()
        
        # Sauvegarde optionnelle
        if self._input("\n[bold yellow]➤ Sauvegarder en JSON? (o/n) : [/bold yellow]").lower() == 'o':
            self.sauvegarder_json()


PersonProfiler = Profileur