import torch
from transformers import GPT2LMHeadModel, GPT2Tokenizer
import os
import threading  # <-- Ajouté pour la gestion asynchrone
from utile.display import console

class IADetector:
    def __init__(self, file_path):
        self.file_path = file_path.replace('"', '').replace("'", "")
        self.model_id = "gpt2"

    def calculate_ai_score(self, text, model, tokenizer):
        encodings = tokenizer(text, return_tensors="pt")
        max_length = model.config.n_positions
        stride = 512
        nlls = []
        for i in range(0, encodings.input_ids.size(1), stride):
            begin_loc = max(i + stride - max_length, 0)
            end_loc = min(i + stride, encodings.input_ids.size(1))
            trg_len = end_loc - i
            input_ids = encodings.input_ids[:, begin_loc:end_loc]
            target_ids = input_ids.clone()
            target_ids[:, :-trg_len] = -100
            with torch.no_grad():
                outputs = model(input_ids, labels=target_ids)
                neg_log_likelihood = outputs.loss * trg_len
            nlls.append(neg_log_likelihood)
        return torch.exp(torch.stack(nlls).sum() / end_loc).item()

    def _async_scan(self):
        """Méthode interne exécutée dans le thread d'arrière-plan."""
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            console.print(f"\n[bold red]❌ [Détecteur IA] Erreur de lecture : {e}[/bold red]\n")
            return

        try:
            # Chargement du modèle (peut prendre du temps)
            model = GPT2LMHeadModel.from_pretrained(self.model_id)
            tokenizer = GPT2Tokenizer.from_pretrained(self.model_id)
            score = self.calculate_ai_score(content, model, tokenizer)

            # Affichage du verdict final en arrière-plan
            console.print(f"\n[bold cyan]🤖 [Analyse IA Terminée] Fichier : {os.path.basename(self.file_path)}[/bold cyan]")
            console.print(f"[bold]Score de Perplexité : {score:.2f}[/bold]")
            if score < 25:
                console.print("[bold red]VERDICT : Très probablement généré par une IA.[/bold red]\n")
            elif score < 50:
                console.print("[bold yellow]VERDICT : Suspicions de contenu assisté par IA.[/bold yellow]\n")
            else:
                console.print("[bold green]VERDICT : Probablement écrit par un humain.[/bold green]\n")
        except Exception as e:
            console.print(f"\n[bold red]❌ [Détecteur IA] Erreur lors de l'analyse : {e}[/bold red]\n")

    def run_scan(self):
        """Lance l'analyse dans un thread séparé pour ne pas bloquer le menu."""
        if not os.path.exists(self.file_path):
            console.print("[bold red]❌ Fichier introuvable.[/bold red]")
            return

        console.print("[bold blue][*] [Détecteur IA] Lancement de l'analyse en arrière-plan... Vous pouvez continuer à utiliser l'application.[/bold blue]")
        
        # Création et démarrage du thread asynchrone
        thread = threading.Thread(target=self._async_scan, daemon=True)
        thread.start()
