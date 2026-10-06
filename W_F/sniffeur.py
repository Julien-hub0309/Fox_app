import threading
from scapy.all import sniff, IP, TCP, UDP, ICMP
from utile.display import console

class NetworkSniffer:
    def __init__(self, target=None):
        self.target = target
        self.thread = None
        self.is_running = False

    def analyser_paquet(self, paquet):
        if paquet.haslayer(IP):
            ip_src = paquet[IP].src
            ip_dst = paquet[IP].dst
            proto = "Autre"
            if paquet.haslayer(TCP): proto = "TCP"
            elif paquet.haslayer(UDP): proto = "UDP"
            elif paquet.haslayer(ICMP): proto = "ICMP"
            
            console.print(f"[bold green][+][/bold green] {proto} : {ip_src} --> {ip_dst}")

    def _execute_sniff(self):
        """Méthode interne exécutée dans le thread secondaire."""
        try:
            filtre = f"host {self.target}" if self.target else "ip"
            # On utilise le paramètre stop_filter pour pouvoir arrêter le thread proprement si besoin
            sniff(filter=filtre, prn=self.analyser_paquet, store=False, stop_filter=lambda p: not self.is_running)
        except Exception as e:
            console.print(f"\n[bold red][!] Erreur Sniffer (Termux sans root ?) : {e}[/bold red]")
            self.is_running = False

    def run_scan(self):
        """Lance le sniffeur en arrière-plan sans bloquer le reste de l'application."""
        console.print(f"[bold orange1]📡 Tentative de démarrage du sniffing sur {self.target if self.target else 'tout le réseau'}...[/bold orange1]")
        
        self.is_running = True
        # Création et démarrage du thread en mode 'daemon' 
        # (il s'arrêtera automatiquement si le programme principal se ferme)
        self.thread = threading.Thread(target=self._execute_sniff, daemon=True)
        self.thread.start()
        
        console.print("[bold blue][i]Le sniffeur tourne en arrière-plan. Continuation du programme principal...[/bold blue]\n")

    def stop_scan(self):
        """Permet d'arrêter proprement le scan depuis le programme principal."""
        self.is_running = False
        console.print("[bold yellow]🛑 Arrêt demandé pour le sniffeur...[/bold yellow]")
