import importlib
import os
import platform
import subprocess
import sys
from pathlib import Path

# ──────────────────────────────────────────────────────────────
# CONFIGURATION — à adapter si besoin
# ──────────────────────────────────────────────────────────────

PROJECT_DIR = Path(__file__).resolve().parent
MAIN_SCRIPT = PROJECT_DIR / "main.py"      # <-- change ici si ton entrée s'appelle autrement
SHORTCUT_NAME = "Fox_app"                  # nom affiché du raccourci

# mapping : nom du module importé -> nom du paquet pip (souvent différent)
DEPENDENCIES = {
    "requests": "requests",
    "rich": "rich",
    "psutil": "psutil",
    "PIL": "Pillow",
    "hachoir": "hachoir",
    "pytsk3": "pytsk3",
    "scapy": "scapy",
    "dns": "dnspython",
    "phonenumbers": "phonenumbers",
    "bs4": "beautifulsoup4",
}


# ──────────────────────────────────────────────────────────────
# 1) INSTALLATION DES DÉPENDANCES
# ──────────────────────────────────────────────────────────────

def installer_dependances():
    print("🔍 Vérification des dépendances...")
    manquants = []

    for module_name, pip_name in DEPENDENCIES.items():
        try:
            importlib.import_module(module_name)
        except ImportError:
            manquants.append(pip_name)

    if not manquants:
        print("✅ Toutes les dépendances sont déjà installées.")
        return

    print(f"📦 Paquets manquants : {', '.join(manquants)}")
    for pip_name in manquants:
        print(f"   → Installation de {pip_name}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", pip_name])
        except subprocess.CalledProcessError as e:
            print(f"   ⚠️ Échec de l'installation de {pip_name} : {e}")
            print("      Installe-le manuellement si l'outil ne fonctionne pas.")

    print("✅ Installation terminée.")


# ──────────────────────────────────────────────────────────────
# 2) DROITS D'EXÉCUTION (Linux / macOS)
# ──────────────────────────────────────────────────────────────

def donner_droits_execution():
    """Rend le launcher et le script principal exécutables (chmod +x).
    Sans effet sous Windows, qui ne gère pas ces permissions."""
    if platform.system() == "Windows":
        return

    fichiers = [Path(__file__).resolve()]
    if MAIN_SCRIPT.exists():
        fichiers.append(MAIN_SCRIPT)

    for f in fichiers:
        try:
            f.chmod(f.stat().st_mode | 0o111)  # ajoute +x pour user/group/other
            print(f"🔓 Droits d'exécution accordés : {f.name}")
        except Exception as e:
            print(f"⚠️ Impossible de rendre {f.name} exécutable : {e}")


# ──────────────────────────────────────────────────────────────
# 3) CRÉATION DU RACCOURCI BUREAU
# ──────────────────────────────────────────────────────────────

def get_desktop_path() -> Path:
    home = Path.home()
    candidats = [home / "Desktop", home / "Bureau"]
    for c in candidats:
        if c.exists():
            return c
    # si aucun dossier bureau détecté, on le crée (cas Desktop par défaut)
    candidats[0].mkdir(parents=True, exist_ok=True)
    return candidats[0]


def creer_raccourci_windows(desktop: Path):
    try:
        import win32com.client  # fourni par pywin32
    except ImportError:
        print("📦 Installation de pywin32 (requis pour le raccourci Windows)...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "pywin32"])
        import win32com.client

    shortcut_path = desktop / f"{SHORTCUT_NAME}.lnk"
    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortCut(str(shortcut_path))
    shortcut.Targetpath = sys.executable
    shortcut.Arguments = f'"{MAIN_SCRIPT}"'
    shortcut.WorkingDirectory = str(PROJECT_DIR)
    shortcut.IconLocation = sys.executable
    shortcut.save()
    print(f"✅ Raccourci créé : {shortcut_path}")


def creer_raccourci_linux(desktop: Path):
    shortcut_path = desktop / f"{SHORTCUT_NAME}.desktop"
    contenu = f"""[Desktop Entry]
Type=Application
Name={SHORTCUT_NAME}
Exec={sys.executable} "{MAIN_SCRIPT}"
Path={PROJECT_DIR}
Terminal=true
"""
    shortcut_path.write_text(contenu, encoding="utf-8")
    shortcut_path.chmod(0o755)
    print(f"✅ Raccourci créé : {shortcut_path}")


def creer_raccourci_macos(desktop: Path):
    shortcut_path = desktop / f"{SHORTCUT_NAME}.command"
    contenu = f'#!/bin/bash\ncd "{PROJECT_DIR}"\n"{sys.executable}" "{MAIN_SCRIPT}"\n'
    shortcut_path.write_text(contenu, encoding="utf-8")
    shortcut_path.chmod(0o755)
    print(f"✅ Raccourci créé : {shortcut_path}")


def creer_raccourci():
    if not MAIN_SCRIPT.exists():
        print(f"⚠️ Script principal introuvable : {MAIN_SCRIPT}")
        print("   Modifie la variable MAIN_SCRIPT dans launcher.py puis relance.")
        return

    desktop = get_desktop_path()
    systeme = platform.system()

    print(f"🖥️ Création du raccourci bureau ({systeme})...")
    if systeme == "Windows":
        creer_raccourci_windows(desktop)
    elif systeme == "Darwin":
        creer_raccourci_macos(desktop)
    elif systeme == "Linux":
        creer_raccourci_linux(desktop)
    else:
        print(f"⚠️ Système non reconnu ({systeme}), raccourci non créé.")


# ──────────────────────────────────────────────────────────────
# 4) LANCEMENT DE L'OUTIL
# ──────────────────────────────────────────────────────────────

def lancer_outil():
    if not MAIN_SCRIPT.exists():
        print(f"⚠️ Impossible de lancer : {MAIN_SCRIPT} n'existe pas.")
        return
    print(f"🚀 Lancement de {MAIN_SCRIPT.name}...\n")
    subprocess.call([sys.executable, str(MAIN_SCRIPT)])


# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== LANCEUR ===\n")
    installer_dependances()
    print()
    donner_droits_execution()
    print()
    creer_raccourci()
    print()
    lancer_outil()