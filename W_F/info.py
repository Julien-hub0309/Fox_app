import platform
import psutil
import subprocess
import os
from datetime import datetime
from utile.display import console

class SystemDevis:
    def __init__(self, target=None):
        self.os_type = platform.system().lower()
        self.is_android = 'ANDROID_STORAGE' in os.environ

    def get_info(self, cmd):
        try:
            return subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode().strip()
        except:
            return "N/A"

    def run_scan(self):
        console.print(f"\n[bold cyan]📋 GÉNÉRATION DU DEVIS SYSTÈME[/bold cyan]")
        
        report = []
        def add_line(text):
            console.print(text)
            report.append(text)

        # --- Système d'exploitation ---
        os_name = "Android" if self.is_android else platform.system()
        add_line(f"\n[bold orange1]💻 Machine & OS[/bold orange1]")
        add_line(f"Type : {os_name} {platform.release()}")
        add_line(f"Architecture : {platform.machine()}")

        # --- CPU ---
        add_line(f"\n[bold orange1]⚙️ Processeur[/bold orange1]")
        cpu_model = "Inconnu"
        if self.os_type == "windows":
            cpu_model = self.get_info("wmic cpu get name").split('\n')[-1]
        elif self.os_type == "linux" or self.is_android:
            cpu_model = self.get_info("grep -m 1 'model name' /proc/cpuinfo | cut -d: -f2")
        elif self.os_type == "darwin":
            cpu_model = self.get_info("sysctl -n machdep.cpu.brand_string")
        
        add_line(f"Modèle : {cpu_model.strip()}")
        add_line(f"Cœurs : {psutil.cpu_count(logical=False)} physiques / {psutil.cpu_count()} logiques")

        # --- Mémoire ---
        mem = psutil.virtual_memory()
        add_line(f"\n[bold orange1]🧠 Mémoire (RAM)[/bold orange1]")
        add_line(f"Total : {round(mem.total / (1024**3), 2)} Go")
        add_line(f"Utilisé : {mem.percent}%")

        # --- GPU (Windows/Linux) ---
        if self.os_type == "windows" or self.os_type == "linux":
            add_line(f"\n[bold orange1]🎮 Graphismes (GPU)[/bold orange1]")
            if self.os_type == "windows":
                gpu = self.get_info("wmic path win32_VideoController get name").split('\n')[-1]
            else:
                gpu = self.get_info("lspci | grep VGA | cut -d ':' -f3")
            add_line(f"GPU : {gpu.strip()}")

        # --- Batterie ---
        batt = psutil.sensors_battery()
        if batt:
            add_line(f"\n[bold orange1]🔋 Énergie[/bold orange1]")
            add_line(f"Batterie : {batt.percent}% | Branchement : {'Secteur' if batt.power_plugged else 'Batterie'}")

        # --- Option Sauvegarde ---
        save = console.input("\n[bold yellow]➤ Sauvegarder le devis en .txt ? (o/n) : [/bold yellow]").lower()
        if save == 'o':
            filename = f"devis_{datetime.now().strftime('%d%m%Y_%H%M')}.txt"
            with open(filename, "w", encoding="utf-8") as f:
                f.write("\n".join([line for line in report])) # Nettoyage sommaire des balises rich possible ici
            console.print(f"[bold green]✅ Devis sauvegardé sous : {filename}[/bold green]")