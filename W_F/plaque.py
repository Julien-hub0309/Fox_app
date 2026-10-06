#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module de recherche d'informations véhicule
API gratuites uniquement - VIN optionnel
"""

import requests
import json
import re
import random
from datetime import datetime
from rich.table import Table
from rich.panel import Panel


class PlaqueOSINT:
    """Module de recherche véhicule par plaque/VIN/marque"""
    
    def __init__(self, target=None):
        self.target = target
        self.nhtsa_url = "https://vpic.nhtsa.dot.gov/api/vehicles"
        self.console = None
        
        # Base de données locale des véhicules français
        self.vehicules_fr = {
            "renault": {
                "clio": {"carburant": ["Essence", "Diesel"], "puissances": [75, 90, 110, 130], "types": ["Citadine"]},
                "megane": {"carburant": ["Essence", "Diesel", "Hybride"], "puissances": [115, 140, 160, 200], "types": ["Compacte"]},
                "captur": {"carburant": ["Essence", "Diesel", "Hybride"], "puissances": [90, 130, 160], "types": ["SUV"]},
                "talisman": {"carburant": ["Essence", "Diesel"], "puissances": [150, 200], "types": ["Berline"]},
                "scenic": {"carburant": ["Essence", "Diesel", "Hybride"], "puissances": [115, 140, 160], "types": ["Monospace"]},
                "zoe": {"carburant": ["Electrique"], "puissances": [110, 135], "types": ["Citadine"]},
                "arkana": {"carburant": ["Hybride", "Essence"], "puissances": [140, 160], "types": ["SUV Coupé"]},
            },
            "peugeot": {
                "208": {"carburant": ["Essence", "Diesel", "Electrique"], "puissances": [75, 100, 136, 156], "types": ["Citadine"]},
                "308": {"carburant": ["Essence", "Diesel", "Hybride"], "puissances": [130, 180, 225], "types": ["Compacte"]},
                "3008": {"carburant": ["Essence", "Diesel", "Hybride"], "puissances": [130, 180, 300], "types": ["SUV"]},
                "5008": {"carburant": ["Essence", "Diesel", "Hybride"], "puissances": [130, 180, 300], "types": ["SUV 7 places"]},
                "2008": {"carburant": ["Essence", "Diesel", "Electrique"], "puissances": [100, 130, 156], "types": ["SUV"]},
                "508": {"carburant": ["Essence", "Diesel", "Hybride"], "puissances": [130, 180, 360], "types": ["Berline"]},
            },
            "citroen": {
                "c3": {"carburant": ["Essence", "Diesel"], "puissances": [83, 110], "types": ["Citadine"]},
                "c4": {"carburant": ["Essence", "Diesel", "Electrique"], "puissances": [100, 130, 156], "types": ["Compacte"]},
                "c5 aircross": {"carburant": ["Essence", "Diesel", "Hybride"], "puissances": [130, 180, 225], "types": ["SUV"]},
                "berlingo": {"carburant": ["Essence", "Diesel", "Electrique"], "puissances": [110, 130], "types": ["Ludospace"]},
            },
            "volkswagen": {
                "golf": {"carburant": ["Essence", "Diesel", "Hybride"], "puissances": [115, 150, 245], "types": ["Compacte"]},
                "polo": {"carburant": ["Essence", "Diesel"], "puissances": [80, 95, 115], "types": ["Citadine"]},
                "tiguan": {"carburant": ["Essence", "Diesel", "Hybride"], "puissances": [130, 150, 245], "types": ["SUV"]},
                "passat": {"carburant": ["Essence", "Diesel", "Hybride"], "puissances": [150, 200, 280], "types": ["Berline"]},
                "t-roc": {"carburant": ["Essence", "Diesel"], "puissances": [115, 150, 190], "types": ["SUV"]},
                "id.3": {"carburant": ["Electrique"], "puissances": [150, 204], "types": ["Compacte"]},
                "id.4": {"carburant": ["Electrique"], "puissances": [170, 204, 299], "types": ["SUV"]},
            },
            "bmw": {
                "serie 1": {"carburant": ["Essence", "Diesel"], "puissances": [116, 150, 306], "types": ["Compacte"]},
                "serie 3": {"carburant": ["Essence", "Diesel", "Hybride"], "puissances": [150, 190, 374], "types": ["Berline"]},
                "serie 5": {"carburant": ["Essence", "Diesel", "Hybride"], "puissances": [190, 286, 394], "types": ["Berline"]},
                "x1": {"carburant": ["Essence", "Diesel", "Hybride"], "puissances": [150, 204], "types": ["SUV"]},
                "x3": {"carburant": ["Essence", "Diesel", "Hybride"], "puissances": [190, 286], "types": ["SUV"]},
                "x5": {"carburant": ["Essence", "Diesel", "Hybride"], "puissances": [286, 394, 625], "types": ["SUV"]},
            },
            "mercedes": {
                "classe a": {"carburant": ["Essence", "Diesel", "Hybride"], "puissances": [116, 150, 190], "types": ["Compacte"]},
                "classe c": {"carburant": ["Essence", "Diesel", "Hybride"], "puissances": [170, 200, 390], "types": ["Berline"]},
                "classe e": {"carburant": ["Essence", "Diesel", "Hybride"], "puissances": [197, 265, 442], "types": ["Berline"]},
                "glc": {"carburant": ["Essence", "Diesel", "Hybride"], "puissances": [197, 265], "types": ["SUV"]},
            },
            "toyota": {
                "yaris": {"carburant": ["Essence", "Hybride"], "puissances": [72, 116, 125], "types": ["Citadine"]},
                "corolla": {"carburant": ["Hybride"], "puissances": [122, 180], "types": ["Compacte"]},
                "rav4": {"carburant": ["Hybride", "Hybride rechargeable"], "puissances": [218, 306], "types": ["SUV"]},
                "chr": {"carburant": ["Hybride"], "puissances": [122, 184], "types": ["SUV"]},
            },
            "dacia": {
                "sandero": {"carburant": ["Essence", "GPL"], "puissances": [65, 90, 100], "types": ["Citadine"]},
                "duster": {"carburant": ["Essence", "Diesel", "GPL"], "puissances": [90, 115, 150], "types": ["SUV"]},
                "logan": {"carburant": ["Essence", "GPL", "Diesel"], "puissances": [75, 95], "types": ["Berline"]},
                "spring": {"carburant": ["Electrique"], "puissances": [45], "types": ["Citadine"]},
            },
            "ford": {
                "fiesta": {"carburant": ["Essence", "Diesel"], "puissances": [95, 125, 200], "types": ["Citadine"]},
                "focus": {"carburant": ["Essence", "Diesel"], "puissances": [100, 150, 280], "types": ["Compacte"]},
                "puma": {"carburant": ["Essence", "Hybride"], "puissances": [125, 155], "types": ["SUV"]},
                "kuga": {"carburant": ["Essence", "Diesel", "Hybride"], "puissances": [150, 190, 243], "types": ["SUV"]},
            },
            "audi": {
                "a1": {"carburant": ["Essence"], "puissances": [95, 150, 200], "types": ["Citadine"]},
                "a3": {"carburant": ["Essence", "Diesel", "Hybride"], "puissances": [116, 150, 245], "types": ["Compacte"]},
                "a4": {"carburant": ["Essence", "Diesel", "Hybride"], "puissances": [150, 204, 349], "types": ["Berline"]},
                "q3": {"carburant": ["Essence", "Diesel"], "puissances": [150, 200], "types": ["SUV"]},
                "q5": {"carburant": ["Essence", "Diesel", "Hybride"], "puissances": [190, 286, 367], "types": ["SUV"]},
            },
            "fiat": {
                "500": {"carburant": ["Essence", "Electrique", "Hybride"], "puissances": [70, 95, 118], "types": ["Citadine"]},
                "panda": {"carburant": ["Essence", "GPL", "Hybride"], "puissances": [70, 85], "types": ["Citadine"]},
            },
            "hyundai": {
                "i10": {"carburant": ["Essence"], "puissances": [67, 84], "types": ["Citadine"]},
                "i20": {"carburant": ["Essence", "Hybride"], "puissances": [84, 100], "types": ["Citadine"]},
                "i30": {"carburant": ["Essence", "Diesel", "Hybride"], "puissances": [120, 159], "types": ["Compacte"]},
                "tucson": {"carburant": ["Essence", "Diesel", "Hybride"], "puissances": [150, 265], "types": ["SUV"]},
            },
            "nissan": {
                "micra": {"carburant": ["Essence"], "puissances": [92, 117], "types": ["Citadine"]},
                "juke": {"carburant": ["Essence", "Hybride"], "puissances": [117, 143], "types": ["SUV"]},
                "qashqai": {"carburant": ["Essence", "Hybride"], "puissances": [140, 158], "types": ["SUV"]},
                "leaf": {"carburant": ["Electrique"], "puissances": [150], "types": ["Compacte"]},
            },
        }

    def set_console(self, console):
        """Définit la console pour l'affichage"""
        self.console = console

    def _print(self, message, style=""):
        """Affiche un message via la console"""
        if self.console:
            if style:
                self.console.print(f"[{style}]{message}[/{style}]")
            else:
                self.console.print(message)
        else:
            print(message)

    def _input(self, prompt):
        """Demande une entrée utilisateur"""
        if self.console:
            return self.console.input(prompt)
        return input(prompt)

    def verifier_vin(self, vin):
        """Vérifie la validité d'un VIN"""
        if not vin or len(vin) != 17:
            return False
        pattern = r'^[A-HJ-NPR-Z0-9]{17}$'
        return re.match(pattern, vin.upper()) is not None

    def decode_vin_nhtsa(self, vin, year=None):
        """Décode un VIN via l'API NHTSA gratuite"""
        endpoint = f"{self.nhtsa_url}/DecodeVinValuesExtended/{vin}?format=json"
        if year:
            endpoint += f"&modelyear={year}"
        
        try:
            response = requests.get(endpoint, timeout=15)
            response.raise_for_status()
            data = response.json()
            return data["Results"][0] if data.get("Results") else None
        except Exception as e:
            self._print(f"Erreur API NHTSA: {e}", "red")
            return None

    def get_models_for_make(self, make, year=None):
        """Récupère les modèles d'un constructeur via NHTSA"""
        if year:
            endpoint = f"{self.nhtsa_url}/GetModelsForMakeYear/make/{make}/modelyear/{year}?format=json"
        else:
            endpoint = f"{self.nhtsa_url}/GetModelsForMake/{make}?format=json"
        
        try:
            response = requests.get(endpoint, timeout=10)
            response.raise_for_status()
            return response.json().get("Results", [])
        except:
            return []

    def rechercher_vehicule_local(self, marque, modele=None):
        """Recherche dans la base locale française"""
        marque_key = marque.lower().replace(" ", "").replace("-", "")
        modele_key = modele.lower().replace(" ", "").replace("-", "") if modele else None
        
        if marque_key not in self.vehicules_fr:
            return None
        
        marque_data = self.vehicules_fr[marque_key]
        
        if not modele_key:
            return {
                "marque": marque.capitalize(),
                "modeles": list(marque_data.keys()),
                "data": marque_data
            }
        
        for modele_nom, modele_data in marque_data.items():
            if modele_key in modele_nom.replace(" ", "").replace("-", ""):
                return {
                    "marque": marque.capitalize(),
                    "modele": modele_nom.capitalize(),
                    "data": modele_data
                }
        
        return None

    def generer_fiche_estimee(self, marque, modele, annee=None):
        """Génère une fiche technique estimée"""
        vehicule = self.rechercher_vehicule_local(marque, modele)
        
        if not vehicule or "data" not in vehicule:
            return None
        
        data = vehicule["data"]
        carburant = random.choice(data["carburant"])
        puissance = random.choice(data["puissances"])
        type_v = data["types"][0]
        
        # Estimations selon le type
        estimations = {
            "Citadine": {"places": 5, "portes": 5, "coffre": "300-350 L", "conso": "4.5-6.5 L/100km" if carburant != "Electrique" else "15-20 kWh/100km"},
            "Compacte": {"places": 5, "portes": 5, "coffre": "380-450 L", "conso": "5.0-7.0 L/100km" if carburant != "Electrique" else "16-22 kWh/100km"},
            "SUV": {"places": 5, "portes": 5, "coffre": "450-550 L", "conso": "5.5-8.0 L/100km" if carburant != "Electrique" else "18-25 kWh/100km"},
            "SUV Coupé": {"places": 5, "portes": 5, "coffre": "400-500 L", "conso": "5.5-8.0 L/100km" if carburant != "Electrique" else "18-25 kWh/100km"},
            "Berline": {"places": 5, "portes": 4, "coffre": "480-550 L", "conso": "5.5-8.0 L/100km" if carburant != "Electrique" else "18-24 kWh/100km"},
            "Monospace": {"places": 7, "portes": 5, "coffre": "200-700 L", "conso": "6.0-9.0 L/100km" if carburant != "Electrique" else "20-28 kWh/100km"},
            "SUV 7 places": {"places": 7, "portes": 5, "coffre": "200-700 L", "conso": "6.0-9.0 L/100km" if carburant != "Electrique" else "20-28 kWh/100km"},
        }
        
        est = estimations.get(type_v, {"places": 5, "portes": 5, "coffre": "400 L", "conso": "6.0+ L/100km"})
        
        # Prix estimé selon année
        prix = "Non disponible"
        if annee:
            age = datetime.now().year - int(annee)
            if age <= 1:
                prix = "20 000 - 45 000 €"
            elif age <= 3:
                prix = "15 000 - 35 000 €"
            elif age <= 5:
                prix = "10 000 - 25 000 €"
            elif age <= 10:
                prix = "5 000 - 15 000 €"
            else:
                prix = "Moins de 8 000 €"
        
        return {
            "Marque": vehicule["marque"],
            "Modèle": vehicule.get("modele", modele.capitalize()),
            "Type": type_v,
            "Année": annee if annee else "Non spécifiée",
            "Carburant": carburant,
            "Puissance": f"{puissance} ch",
            "Places": est["places"],
            "Portes": est["portes"],
            "Coffre": est["coffre"],
            "Consommation": est["conso"],
            "Prix estimé": prix,
            "Source": "Base locale (estimation)"
        }

    def afficher_fiche_rich(self, data, title="Fiche Technique"):
        """Affiche une fiche technique avec Rich"""
        if not self.console:
            for key, value in data.items():
                print(f"{key}: {value}")
            return
        
        table = Table(title=title, show_header=True, header_style="bold magenta")
        table.add_column("Caractéristique", style="cyan")
        table.add_column("Valeur", style="green")
        
        for key, value in data.items():
            table.add_row(str(key), str(value))
        
        self.console.print(table)

    def afficher_resultats_nhtsa(self, data):
        """Affiche les résultats détaillés NHTSA"""
        if not self.console:
            return
        
        table = Table(title="Informations VIN (NHTSA)", show_header=True, header_style="bold blue")
        table.add_column("Attribut", style="cyan")
        table.add_column("Valeur", style="green")
        
        champs = {
            'Make': 'Marque',
            'Model': 'Modèle',
            'ModelYear': 'Année',
            'VehicleType': 'Type',
            'BodyClass': 'Carrosserie',
            'EngineCylinders': 'Cylindres',
            'EngineSize': 'Cylindrée (L)',
            'FuelTypePrimary': 'Carburant',
            'TransmissionStyle': 'Transmission',
            'DriveType': 'Traction',
            'HorsePower': 'Puissance (ch)',
            'CurbWeight': 'Poids (kg)',
            'PlantCountry': 'Pays fabrication',
        }
        
        for champ, label in champs.items():
            valeur = data.get(champ)
            if valeur and str(valeur).strip() and str(valeur).lower() not in ['not applicable', 'n/a', 'null', 'none', '']:
                table.add_row(label, str(valeur))
        
        self.console.print(table)

    def menu_recherche(self):
        """Affiche le menu de recherche"""
        self._print("\n[bold cyan]MÉTHODES DE RECHERCHE (API gratuites)[/bold cyan]")
        self._print("[bold cyan]1.[/bold cyan] 🔍 Recherche par MARQUE + MODÈLE (Base France)")
        self._print("[bold cyan]2.[/bold cyan] 🔍 Recherche par MARQUE + MODÈLE + ANNÉE (API NHTSA)")
        self._print("[bold cyan]3.[/bold cyan] 🔍 Recherche par VIN (Précision maximale)")
        self._print("[bold cyan]4.[/bold cyan] 📋 Liste des marques disponibles")
        self._print("[bold red]0.[/bold red] 🔙 Retour")
        
        return self._input("[bold yellow]➤ Choix : [/bold yellow]").strip()

    def run_scan(self):
        """Lance le module de recherche véhicule"""
        try:
            from utile.display import console as main_console
            self.set_console(main_console)
        except:
            pass
        
        self._print(Panel.fit(
            "[bold blue]Recherche Véhicule[/bold blue]\n"
            "[dim]API gratuites - VIN optionnel[/dim]",
            border_style="blue"
        ))
        
        while True:
            choix = self.menu_recherche()
            
            if choix == "0":
                break
            
            # Option 1: Recherche base locale
            if choix == "1":
                marque = self._input("[bold yellow]➤ Marque (ex: Renault, Peugeot): [/bold yellow]").strip()
                modele = self._input("[bold yellow]➤ Modèle (ex: Clio, 308 - laisser vide pour voir tous): [/bold yellow]").strip() or None
                
                if not marque:
                    self._print("❌ Marque requise", "red")
                    continue
                
                resultat = self.rechercher_vehicule_local(marque, modele)
                
                if resultat:
                    if "modeles" in resultat and not modele:
                        self._print(f"\n✅ {len(resultat['modeles'])} modèles trouvés pour {resultat['marque']}:", "green")
                        for i, mod in enumerate(resultat['modeles'], 1):
                            self._print(f"  {i}. {mod.capitalize()}")
                        
                        choix_mod = self._input("\n[bold yellow]➤ Numéro du modèle à détailler (ou Entrée): [/bold yellow]").strip()
                        if choix_mod.isdigit():
                            idx = int(choix_mod) - 1
                            if 0 <= idx < len(resultat['modeles']):
                                modele = resultat['modeles'][idx]
                                fiche = self.generer_fiche_estimee(marque, modele)
                                if fiche:
                                    self.afficher_fiche_rich(fiche)
                    else:
                        fiche = self.generer_fiche_estimee(marque, modele)
                        if fiche:
                            self.afficher_fiche_rich(fiche)
                            
                            annee = self._input("[bold yellow]➤ Année pour affiner (optionnel): [/bold yellow]").strip()
                            if annee.isdigit():
                                fiche = self.generer_fiche_estimee(marque, modele, annee)
                                self.afficher_fiche_rich(fiche)
                else:
                    self._print(f"❌ Marque '{marque}' non trouvée", "red")
            
            # Option 2: Recherche API NHTSA par marque
            elif choix == "2":
                marque = self._input("[bold yellow]➤ Marque (en anglais, ex: Honda, Toyota): [/bold yellow]").strip()
                annee = self._input("[bold yellow]➤ Année (optionnel): [/bold yellow]").strip()
                
                if not marque:
                    self._print("❌ Marque requise", "red")
                    continue
                
                self._print(f"\n⏳ Recherche des modèles {marque}...", "blue")
                modeles = self.get_models_for_make(marque, int(annee) if annee.isdigit() else None)
                
                if modeles:
                    self._print(f"\n✅ {len(modeles)} modèles trouvés:", "green")
                    for i, modele in enumerate(modeles[:30], 1):
                        nom = modele.get('Model_Name', 'N/A')
                        make_name = modele.get('Make_Name', marque)
                        self._print(f"  {i:2}. {make_name} {nom}")
                else:
                    self._print(f"❌ Aucun modèle trouvé", "red")
            
            # Option 3: Recherche par VIN
            elif choix == "3":
                vin = self._input("[bold yellow]➤ VIN (17 caractères): [/bold yellow]").strip().upper()
                
                if not self.verifier_vin(vin):
                    self._print("❌ VIN invalide (17 caractères, sans I, O, Q)", "red")
                    continue
                
                annee = self._input("[bold yellow]➤ Année modèle (optionnel): [/bold yellow]").strip()
                annee = int(annee) if annee.isdigit() else None
                
                self._print("\n⏳ Décodage VIN via NHTSA...", "blue")
                data = self.decode_vin_nhtsa(vin, annee)
                
                if data and data.get('Make'):
                    self.afficher_resultats_nhtsa(data)
                    
                    if self._input("[bold yellow]➤ Sauvegarder en JSON? (o/n): [/bold yellow]").lower() == 'o':
                        filename = f"vehicle_{vin}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                        with open(filename, 'w', encoding='utf-8') as f:
                            json.dump(data, f, indent=2, ensure_ascii=False)
                        self._print(f"💾 Sauvegardé: {filename}", "green")
                else:
                    self._print("❌ Aucune donnée trouvée pour ce VIN", "red")
                    self._print("Note: L'API NHTSA couvre les véhicules vendus aux USA", "dim")
            
            # Option 4: Liste des marques
            elif choix == "4":
                self._print("\n[bold cyan]MARQUES DISPONIBLES (Base locale):[/bold cyan]")
                marques = sorted(self.vehicules_fr.keys())
                
                for i, marque in enumerate(marques, 1):
                    nb_modeles = len(self.vehicules_fr[marque])
                    self._print(f"  {i:2}. {marque.capitalize():15} ({nb_modeles} modèles)")
                
                self._print(f"\nTotal: {len(marques)} marques", "dim")
            
            else:
                self._print("❌ Choix invalide", "red")
            
            self._input("\n[bold white]Appuyez sur Entrée pour continuer...[/bold white]")

PlaqueAnalyzer = PlaqueOSINT