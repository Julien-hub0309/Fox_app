import glob
import io
import json
import os
import sys
from contextlib import redirect_stdout
from datetime import datetime

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Confirm, IntPrompt, Prompt
    from rich.table import Table
    from rich.text import Text
    from rich.markup import escape
    from rich import box
except ImportError:
    print("Le module 'rich' est requis :  pip install rich")
    sys.exit(1)

try:
    from idee import TorSearchEngine, STEM_AVAILABLE
except ImportError as exc:
    print(f"Impossible de charger idee.py ({exc}).")
    print("Installez les dépendances :  pip install -r requirements.txt")
    sys.exit(1)

# Console liée au vrai stdout : les prints de idee.py sont capturés sans casser l'affichage
console = Console(file=sys.stdout)

RELIABILITY_STYLE = {
    "fiable": "bold green",
    "satire": "bold red",
    "inconnu": "yellow",
    "inconnu (Tor)": "yellow",
}
CREDIBILITY_STYLE = {
    "crédible": "bold green",
    "suspect": "bold red",
    "moyen": "yellow",
    "non pertinent": "dim",
}
VERDICT_STYLE = {"crédible": "green", "suspect": "red", "mitigé": "yellow"}

BANNER = r"""
 __     __        _  __ _           _
 \ \   / /__ _ __(_)/ _(_) ___ __ _| |_ ___ _   _ _ __
  \ \ / / _ \ '__| | |_| |/ __/ _` | __/ _ \ | | | '__|
   \ V /  __/ |  | |  _| | (_| (_| | ||  __/ |_| | |
    \_/ \___|_|  |_|_| |_|\___\__,_|\__\___|\__,_|_|
"""


# --------------------------------------------------------------------------- #
#  Utilitaires d'affichage
# --------------------------------------------------------------------------- #
def clear():
    console.clear()


def header():
    console.print(Text(BANNER, style="bold cyan"))
    console.print(
        Panel.fit(
            "[bold]Vérificateur d'informations[/bold]  ·  recherche, sources, crédibilité",
            border_style="cyan",
        )
    )


def styled(value, mapping):
    style = mapping.get(value, "white")
    return f"[{style}]{escape(str(value))}[/{style}]"


def pause():
    Prompt.ask("\n[dim]Appuyez sur Entrée pour continuer[/dim]", default="", show_default=False)


def short(text, size=70):
    text = (text or "").strip()
    return text if len(text) <= size else text[: size - 1] + "…"


# --------------------------------------------------------------------------- #
#  Affichage des résultats
# --------------------------------------------------------------------------- #
def show_results(query, search_results, exact_matches, partial_matches, timestamp=None):
    console.rule(f"[bold cyan]Résultats pour « {escape(query)} »")
    if timestamp:
        console.print(f"[dim]Recherche du {timestamp}[/dim]")

    if not search_results:
        console.print(Panel("Aucun résultat trouvé.", border_style="red"))
        return

    # --- Tableau des résultats bruts -------------------------------------- #
    table = Table(box=box.ROUNDED, show_lines=True, header_style="bold", expand=True)
    table.add_column("#", justify="right", width=3)
    table.add_column("Titre / URL", ratio=3)
    table.add_column("Source", justify="center", ratio=1)
    table.add_column("Extrait", ratio=3)
    for i, r in enumerate(search_results, 1):
        table.add_row(
            str(i),
            f"[bold]{escape(short(r['title'], 80))}[/bold]\n[blue]{escape(short(r['url'], 80))}[/blue]",
            styled(r.get("source_reliability", "inconnu"), RELIABILITY_STYLE),
            escape(short(r.get("snippet", ""), 160)) or "[dim]—[/dim]",
        )
    console.print(table)

    # --- Répartition des sources ------------------------------------------ #
    counts = {}
    for r in search_results:
        key = r.get("source_reliability", "inconnu")
        counts[key] = counts.get(key, 0) + 1
    console.print(
        "Sources : "
        + "  ".join(f"{styled(k, RELIABILITY_STYLE)} × {v}" for k, v in counts.items())
    )

    # --- Analyse détaillée ------------------------------------------------- #
    if exact_matches or partial_matches:
        console.rule("[bold cyan]Analyse détaillée du contenu")

        if exact_matches:
            console.print(f"\n[bold]Correspondances exactes ({len(exact_matches)})[/bold]")
            for i, m in enumerate(exact_matches, 1):
                body = (
                    f"[bold]{escape(m['title'])}[/bold]\n"
                    f"[blue]{escape(m['url'])}[/blue]\n\n"
                    f"Auteur       : {escape(str(m['author']))}\n"
                    f"Source       : {styled(m['source_reliability'], RELIABILITY_STYLE)}\n"
                    f"Crédibilité  : {styled(m['credibility'], CREDIBILITY_STYLE)}\n\n"
                    f"[italic]« …{escape(m['context'])}… »[/italic]"
                )
                console.print(Panel(body, title=f"#{i}", border_style="green", expand=True))
        else:
            console.print("\n[yellow]Aucune correspondance exacte trouvée.[/yellow]")

        if partial_matches:
            console.print(f"\n[bold]Correspondances partielles ({len(partial_matches)})[/bold]")
            ptable = Table(box=box.SIMPLE_HEAVY, header_style="bold", expand=True)
            ptable.add_column("#", justify="right", width=3)
            ptable.add_column("Titre / URL", ratio=3)
            ptable.add_column("Auteur", ratio=1)
            ptable.add_column("Source", justify="center")
            ptable.add_column("Crédibilité", justify="center")
            for i, m in enumerate(partial_matches, 1):
                ptable.add_row(
                    str(i),
                    f"{escape(short(m['title'], 60))}\n[blue]{escape(short(m['url'], 60))}[/blue]",
                    escape(str(m["author"])),
                    styled(m["source_reliability"], RELIABILITY_STYLE),
                    styled(m["credibility"], CREDIBILITY_STYLE),
                )
            console.print(ptable)

        show_verdict(exact_matches)
    else:
        console.print(
            "\n[dim]L'analyse du contenu n'a pas été effectuée : "
            "relancez avec « analyser les pages » pour obtenir un verdict.[/dim]"
        )


def show_verdict(exact_matches):
    summary = TorSearchEngine.summarize_credibility(exact_matches)
    messages = {
        "crédible": "L'information semble globalement crédible.",
        "suspect": "L'information semble suspecte, vérifiez avec d'autres sources.",
        "mitigé": "Les sources sont mitigées, approfondissez votre recherche.",
    }
    color = VERDICT_STYLE[summary["verdict"]]
    body = (
        f"Sources crédibles : [green]{summary['credible']}[/green]\n"
        f"Sources suspectes : [red]{summary['suspect']}[/red]\n\n"
        f"[bold {color}]CONCLUSION : {messages[summary['verdict']]}[/bold {color}]\n\n"
        "[dim]Indicateur automatique basé sur des mots-clés et la liste de sources : "
        "il ne remplace pas votre jugement.[/dim]"
    )
    console.print(Panel(body, title="Résumé de la crédibilité", border_style=color))


# --------------------------------------------------------------------------- #
#  Tor
# --------------------------------------------------------------------------- #
def tor_status(engine):
    clear()
    header()
    console.rule("[bold cyan]Statut Tor")

    console.print(f"Module stem installé : {'[green]oui[/green]' if STEM_AVAILABLE else '[red]non[/red]'}")
    running = engine.is_tor_running()
    console.print(
        f"Tor actif sur le port {engine.socks_port} : "
        f"{'[green]oui[/green]' if running else '[red]non[/red]'}"
    )

    if running:
        with console.status("Test de la connexion via Tor…"):
            ip = engine.check_tor_connection()
        if ip:
            console.print(f"Connexion Tor fonctionnelle · IP de sortie : [bold]{escape(ip)}[/bold]")
        else:
            console.print("[yellow]Le port répond mais le trafic ne passe pas par Tor.[/yellow]")
    elif STEM_AVAILABLE and Confirm.ask("\nDémarrer une instance Tor maintenant ?", default=False):
        start_tor_with_feedback(engine)
    pause()


def start_tor_with_feedback(engine):
    buffer = io.StringIO()
    with console.status("Démarrage de Tor (peut prendre une minute)…") as status:
        def handler(line):
            line = str(line).strip()
            if "Bootstrapped" in line:
                status.update(f"Démarrage de Tor… {escape(line.split('Bootstrapped')[-1].strip()[:60])}")

        with redirect_stdout(buffer):
            ok = engine.start_tor(msg_handler=handler)
    if ok:
        console.print("[green]Tor a démarré avec succès.[/green]")
    else:
        err = [l for l in buffer.getvalue().splitlines() if "Erreur" in l]
        console.print("[red]Impossible de démarrer Tor.[/red]")
        for l in err:
            console.print(f"[dim]{escape(l)}[/dim]")
        console.print("[dim]Astuce : installez Tor (« sudo apt install tor » / « brew install tor »).[/dim]")
    return ok


# --------------------------------------------------------------------------- #
#  Nouvelle recherche
# --------------------------------------------------------------------------- #
def ask_parameters(engine):
    console.print("\n[bold]1/4 · Que voulez-vous vérifier ?[/bold]")
    query = Prompt.ask("  Phrase ou idée à rechercher").strip()
    if not query:
        console.print("[red]Vous devez entrer une phrase valide.[/red]")
        return None

    console.print("\n[bold]2/4 · Confidentialité[/bold]")
    use_tor = Confirm.ask("  Passer par le réseau Tor ?", default=False)
    start_tor = False
    if use_tor:
        if engine.is_tor_running():
            console.print("  [green]Un Tor est déjà actif, il sera utilisé.[/green]")
        elif STEM_AVAILABLE:
            start_tor = Confirm.ask("  Aucun Tor détecté. En démarrer un ?", default=True)
        else:
            console.print("  [yellow]stem n'est pas installé et aucun Tor ne tourne : Tor sera ignoré.[/yellow]")
            use_tor = False

    console.print("\n[bold]3/4 · Profondeur[/bold]")
    num_results = IntPrompt.ask("  Nombre de résultats (1-50)", default=10)
    num_results = max(1, min(num_results, 50))
    analyze = Confirm.ask("  Analyser le contenu des pages (verdict de crédibilité) ?", default=True)
    max_pages = 5
    if analyze:
        max_pages = max(1, min(IntPrompt.ask("  Nombre de pages à analyser (1-10)", default=5), 10))

    params = {
        "query": query,
        "tor": use_tor,
        "start_tor": start_tor,
        "results": num_results,
        "analyze": analyze,
        "max_pages": max_pages,
    }

    console.print("\n[bold]4/4 · Récapitulatif[/bold]")
    recap = Table.grid(padding=(0, 2))
    recap.add_row("Requête", f"[bold]{escape(query)}[/bold]")
    recap.add_row("Réseau", "Tor" if use_tor else "Web normal")
    recap.add_row("Résultats", str(num_results))
    recap.add_row("Analyse des pages", f"oui ({max_pages} pages)" if analyze else "non")
    console.print(Panel(recap, border_style="cyan"))
    return params if Confirm.ask("Lancer la recherche ?", default=True) else None


def run_search(engine, params):
    """Exécute la recherche en capturant les prints de idee.py"""
    buffer = io.StringIO()

    if params["start_tor"]:
        if not start_tor_with_feedback(engine):
            console.print("[yellow]Retour au web normal.[/yellow]")
            params["tor"] = False

    if params["tor"]:
        engine.configure_tor_proxies()

    search_results, exact_matches, partial_matches = [], [], []

    with console.status("Recherche en cours…") as status:
        with redirect_stdout(buffer):
            if params["tor"]:
                status.update("Recherche via le réseau Tor… (peut être long)")
                search_results = engine.search_on_tor(params["query"], params["results"])
            else:
                status.update("Recherche sur le web…")
                search_results = engine.search_on_surface_web(params["query"], params["results"])

            if params["analyze"] and search_results:
                def progress(i, total, url):
                    status.update(f"Analyse de la page {i + 1}/{total} · {escape(short(url, 60))}")

                exact_matches, partial_matches = engine.search_content_in_pages(
                    params["query"], search_results, max_pages=params["max_pages"], progress=progress
                )

    errors = [l for l in buffer.getvalue().splitlines() if "Erreur" in l]
    if errors:
        console.print(f"[yellow]{len(errors)} avertissement(s) pendant la recherche :[/yellow]")
        for l in errors[:5]:
            console.print(f"  [dim]{escape(short(l, 110))}[/dim]")

    return search_results, exact_matches, partial_matches


def save_results(params, search_results, exact_matches, partial_matches):
    filename = f"recherche_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(
            {
                "query": params["query"],
                "timestamp": datetime.now().isoformat(),
                "search_results": search_results,
                "exact_matches": exact_matches,
                "partial_matches": partial_matches,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    console.print(f"[green]Résultats sauvegardés dans {filename}[/green]")


def new_search(engine):
    clear()
    header()
    console.rule("[bold cyan]Nouvelle vérification")
    params = ask_parameters(engine)
    if not params:
        pause()
        return

    search_results, exact_matches, partial_matches = run_search(engine, params)
    clear()
    header()
    show_results(params["query"], search_results, exact_matches, partial_matches)

    if search_results and Confirm.ask("\nSauvegarder les résultats dans un fichier JSON ?", default=False):
        save_results(params, search_results, exact_matches, partial_matches)
    pause()


# --------------------------------------------------------------------------- #
#  Historique
# --------------------------------------------------------------------------- #
def history():
    while True:
        clear()
        header()
        console.rule("[bold cyan]Historique des recherches")
        files = sorted(glob.glob("recherche_*.json"), reverse=True)
        if not files:
            console.print("[dim]Aucune recherche sauvegardée dans ce dossier.[/dim]")
            pause()
            return

        table = Table(box=box.ROUNDED, header_style="bold")
        table.add_column("#", justify="right")
        table.add_column("Date")
        table.add_column("Requête")
        table.add_column("Résultats", justify="right")
        entries = []
        for i, path in enumerate(files, 1):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            entries.append((path, data))
            date = data.get("timestamp", "")[:19].replace("T", " ")
            table.add_row(
                str(len(entries)), date, escape(short(data.get("query", "?"), 60)),
                str(len(data.get("search_results", []))),
            )
        console.print(table)

        choice = Prompt.ask("\nNuméro à afficher (Entrée pour revenir)", default="", show_default=False)
        if not choice:
            return
        if not choice.isdigit() or not (1 <= int(choice) <= len(entries)):
            console.print("[red]Numéro invalide.[/red]")
            pause()
            continue

        path, data = entries[int(choice) - 1]
        clear()
        header()
        show_results(
            data.get("query", "?"),
            data.get("search_results", []),
            data.get("exact_matches", []),
            data.get("partial_matches", []),
            timestamp=data.get("timestamp", "")[:19].replace("T", " "),
        )
        pause()


# --------------------------------------------------------------------------- #
#  Aide
# --------------------------------------------------------------------------- #
def show_help():
    clear()
    header()
    console.rule("[bold cyan]Aide")
    console.print(
        Panel(
            "[bold]Comment ça marche ?[/bold]\n"
            "1. Vous saisissez une phrase ou une idée à vérifier.\n"
            "2. L'outil la recherche (web normal ou Tor) et note la fiabilité de chaque source.\n"
            "3. Si vous activez l'analyse, il ouvre les pages, cherche votre phrase, repère l'auteur\n"
            "   et évalue la crédibilité du texte.\n\n"
            "[bold]Fiabilité des sources[/bold]\n"
            "  [green]fiable[/green]   média reconnu (Reuters, BBC, Le Monde…)\n"
            "  [red]satire[/red]   site humoristique connu (The Onion…)\n"
            "  [yellow]inconnu[/yellow]  source non évaluée\n\n"
            "[bold]Crédibilité du contenu[/bold]\n"
            "  [green]crédible[/green] · [yellow]moyen[/yellow] · [red]suspect[/red] · [dim]non pertinent[/dim]\n\n"
            "[bold]Important[/bold]\n"
            "Le verdict est une aide heuristique (mots-clés + liste de sources), pas une vérité absolue.\n"
            "Recoupez toujours avec plusieurs sources.\n\n"
            "[dim]Raccourci : Ctrl+C pour quitter à tout moment.[/dim]",
            border_style="cyan",
        )
    )
    pause()


# --------------------------------------------------------------------------- #
#  Boucle principale
# --------------------------------------------------------------------------- #
def main():
    engine = TorSearchEngine()
    try:
        while True:
            clear()
            header()
            menu = Table.grid(padding=(0, 2))
            menu.add_row("[bold cyan]1[/bold cyan]", "Nouvelle vérification")
            menu.add_row("[bold cyan]2[/bold cyan]", "Historique des recherches")
            menu.add_row("[bold cyan]3[/bold cyan]", "Statut / démarrage de Tor")
            menu.add_row("[bold cyan]4[/bold cyan]", "Aide")
            menu.add_row("[bold cyan]5[/bold cyan]", "Quitter")
            console.print(Panel(menu, title="Menu", border_style="cyan", expand=False))

            choice = Prompt.ask("Votre choix", choices=["1", "2", "3", "4", "5"], default="1")
            if choice == "1":
                new_search(engine)
            elif choice == "2":
                history()
            elif choice == "3":
                tor_status(engine)
            elif choice == "4":
                show_help()
            else:
                break
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        engine.stop_tor()
        console.print("\n[cyan]À bientôt ![/cyan]")


if __name__ == "__main__":
    main()