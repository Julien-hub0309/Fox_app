import os
import json
import sqlite3
from rich.table import Table
from rich.panel import Panel
from utile.display import console

class JustradamusModule:
    def __init__(self, target, proxy=None):
        self.target = target
        self.results_dir = "Justradamus_Reports"
        self.db_path = "justradamus_intelligence.db"
        if not os.path.exists(self.results_dir):
            os.makedirs(self.results_dir)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS findings 
                (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                 target TEXT, category TEXT, data TEXT, 
                 timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)
            """)

    def save_finding(self, category, data):
        path = f"{self.results_dir}/{category}_{self.target}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO findings (target, category, data) VALUES (?, ?, ?)",
                         (self.target, category, json.dumps(data)))
        return path

    def display_results(self, category, data):
        table = Table(title=f"🔍 [bold magenta]{category}[/bold magenta]", box=None)
        table.add_column("Donnée", style="bold yellow")
        table.add_column("Information", style="white")

        for key, value in data.items():
            if isinstance(value, list):
                table.add_row(str(key), ", ".join(map(str, value)))
            else:
                table.add_row(str(key), str(value))

        console.print(Panel(table, border_style="bright_blue"))