import urllib.request
import socket
import sys
from tkinter import Tk, Label, Button, Entry, END, Frame, Text, Scrollbar

# ──────────────────────────────────────────────────────────────
#  PALETTE "WATCH_FOX" — thème sombre moderne et épuré
# ──────────────────────────────────────────────────────────────
COLOR_BG_DEEP    = "#0B0D10"   # fond principal
COLOR_BG_PANEL   = "#14171C"   # panneaux / cartes
COLOR_BG_CARD    = "#1A1E24"   # cartes légèrement plus claires
COLOR_BG_INPUT   = "#101317"   # champ de saisie
COLOR_CYAN       = "#4FC3F7"   # accent principal
COLOR_CYAN_SOFT  = "#2E3A44"   # accent atténué (bordures)
COLOR_BLUE_DARK  = "#7C9CFF"   # accent secondaire
COLOR_GREEN      = "#4ADE80"   # succès / tag LOCAL
COLOR_RED        = "#F87171"   # erreurs
COLOR_WHITE_DIM  = "#C7D0D9"   # texte console
COLOR_TEXT_MUTED = "#5C6672"   # texte secondaire
COLOR_BORDER     = "#20242B"   # bordures neutres

FONT_MAIN = "Segoe UI" if sys.platform.startswith("win") else "Helvetica"
FONT_MONO = "Consolas" if sys.platform.startswith("win") else "Menlo"

# ──────────────────────────────────────────────────────────────
#  CONSOLE GLOBALE
# ──────────────────────────────────────────────────────────────

class FakeConsole:
    def __init__(self):
        self.text_widget = None

    def get_public_ip(self):
        try:
            return urllib.request.urlopen('https://api4.ipify.org', timeout=3).read().decode('utf8')
        except:
            return "Indisponible"

    def get_hostname(self):
        try:
            return socket.gethostname()
        except:
            return "Inconnu"

    def set_widget(self, widget):
        self.text_widget = widget
        self.text_widget.tag_config("success", foreground=COLOR_GREEN)
        self.text_widget.tag_config("error", foreground=COLOR_RED)
        self.text_widget.tag_config("info", foreground=COLOR_CYAN)
        self.text_widget.tag_config("sep", foreground=COLOR_BLUE_DARK)
        self.text_widget.tag_config("default", foreground=COLOR_WHITE_DIM)

    def print(self, *args, **kwargs):
        if not self.text_widget:
            return
        raw_msg = " ".join(map(str, args))

        if "[+]" in raw_msg or "FOUND" in raw_msg.upper():
            formatted_msg, tag = f"  ✔ {raw_msg}\n", "success"
        elif "[!]" in raw_msg or "ERROR" in raw_msg.upper():
            formatted_msg, tag = f"  ✘ {raw_msg}\n", "error"
        elif "[>]" in raw_msg:
            formatted_msg, tag = f"\n▸ {raw_msg}\n", "sep"
        elif "-" * 10 in raw_msg:
            formatted_msg, tag = "─" * 46 + "\n", "sep"
        elif "[V]" in raw_msg or "[OK]" in raw_msg:
            formatted_msg, tag = f"  ✔ {raw_msg}\n", "success"
        elif "[X]" in raw_msg or "[!!!]" in raw_msg:
            formatted_msg, tag = f"  ✘ {raw_msg}\n", "error"
        elif "[*]" in raw_msg or "[~]" in raw_msg:
            formatted_msg, tag = f"  ⟳ {raw_msg}\n", "info"
        else:
            formatted_msg, tag = f"    • {raw_msg}\n", "default"

        self.text_widget.insert(END, formatted_msg, tag)
        self.text_widget.see(END)
        self.text_widget.update_idletasks()

console = FakeConsole()

# ──────────────────────────────────────────────────────────────
#  REDIRECTEUR stdout → FakeConsole
# ──────────────────────────────────────────────────────────────

class RedirectText:
    def __init__(self):
        self.buffer = ""

    def write(self, string):
        self.buffer += string
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line.strip():
                console.print(line)

    def flush(self):
        if self.buffer.strip():
            console.print(self.buffer)
            self.buffer = ""

# ──────────────────────────────────────────────────────────────
#  GUI
# ──────────────────────────────────────────────────────────────

class WatchFoxGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("WATCH_FOX V2.0 — OSINT")
        self.root.geometry("960x920")
        self.root.minsize(760, 700)
        self.root.configure(bg=COLOR_BG_DEEP)

        # ── Conteneur racine ───────────────────────────────────
        self.main_container = Frame(self.root, bg=COLOR_BG_DEEP)
        self.main_container.pack(fill="both", expand=True, padx=24, pady=20)

        # ── En-tête / carte d'infos ─────────────────────────────
        header = Frame(self.main_container, bg=COLOR_BG_PANEL, highlightbackground=COLOR_BORDER,
                        highlightthickness=1)
        header.pack(fill="x", pady=(0, 16))

        header_inner = Frame(header, bg=COLOR_BG_PANEL)
        header_inner.pack(fill="x", padx=18, pady=14)

        title_row = Frame(header_inner, bg=COLOR_BG_PANEL)
        title_row.pack(fill="x")

        Label(title_row, text="⌁ WATCH_FOX", bg=COLOR_BG_PANEL, fg=COLOR_CYAN,
              font=(FONT_MAIN, 18, "bold")).pack(side="left")
        Label(title_row, text="  V2.0", bg=COLOR_BG_PANEL, fg=COLOR_TEXT_MUTED,
              font=(FONT_MAIN, 12, "bold")).pack(side="left", anchor="s", pady=(0, 3))

        Label(header_inner, text="Intelligence & Investigation Framework", bg=COLOR_BG_PANEL,
              fg=COLOR_TEXT_MUTED, font=(FONT_MAIN, 10)).pack(anchor="w", pady=(2, 10))

        info_row = Frame(header_inner, bg=COLOR_BG_PANEL)
        info_row.pack(fill="x")

        self._info_chip(info_row, "DEVICE", console.get_hostname())
        self._info_chip(info_row, "IPv4", console.get_public_ip())

        # ── Zone de saisie ──────────────────────────────────────
        input_card = Frame(self.main_container, bg=COLOR_BG_PANEL, highlightbackground=COLOR_BORDER,
                            highlightthickness=1)
        input_card.pack(fill="x", pady=(0, 16))

        input_inner = Frame(input_card, bg=COLOR_BG_PANEL)
        input_inner.pack(fill="x", padx=18, pady=14)

        Label(input_inner, text="CIBLE", bg=COLOR_BG_PANEL, fg=COLOR_TEXT_MUTED,
              font=(FONT_MAIN, 9, "bold")).pack(anchor="w", pady=(0, 6))

        self.target_entry = Entry(
            input_inner,
            bg=COLOR_BG_INPUT, fg=COLOR_CYAN, insertbackground=COLOR_CYAN,
            font=(FONT_MONO, 14), justify="left", bd=0, relief="flat",
            highlightbackground=COLOR_CYAN_SOFT, highlightcolor=COLOR_CYAN, highlightthickness=1
        )
        self.target_entry.pack(fill="x", ipady=10)

        # ── Palette de boutons ──────────────────────────────────
        actions_card = Frame(self.main_container, bg=COLOR_BG_DEEP)
        actions_card.pack(fill="x", pady=(0, 16))

        ROWS = [
            {
                "label":  "OSINT",
                "accent": COLOR_CYAN,
                "buttons": [("btn_phone", "PHONE"), ("btn_web", "WEB / IP"), ("btn_mail", "EMAIL"), ("btn_pseudo", "PSEUDO")]
            },
            {
                "label":  "ANALYSE",
                "accent": COLOR_BLUE_DARK,
                "buttons": [("btn_url", "URL SCAN"), ("btn_hash", "DEHASH"), ("btn_pass", "PASSWORD"), ("btn_meta", "METADATA")]
            },
            {
                "label":  "SYSTÈME",
                "accent": COLOR_GREEN,
                "buttons": [("btn_ia", "IA DETECT"), ("btn_profileur", "PROFILEUR"), ("btn_sysinfo", "SYS INFO")]
            },
        ]

        for row_cfg in ROWS:
            accent = row_cfg["accent"]
            section = Frame(actions_card, bg=COLOR_BG_PANEL, highlightbackground=COLOR_BORDER,
                             highlightthickness=1)
            section.pack(fill="x", pady=(0, 10))

            section_inner = Frame(section, bg=COLOR_BG_PANEL)
            section_inner.pack(fill="x", padx=14, pady=12)

            Label(section_inner, text=row_cfg["label"], bg=COLOR_BG_PANEL, fg=accent,
                  font=(FONT_MAIN, 9, "bold")).pack(anchor="w", pady=(0, 8))

            btn_row = Frame(section_inner, bg=COLOR_BG_PANEL)
            btn_row.pack(fill="x")

            for i, (attr, label) in enumerate(row_cfg["buttons"]):
                btn_row.columnconfigure(i, weight=1)

                cell = Frame(btn_row, bg=COLOR_BG_PANEL)
                cell.grid(row=0, column=i, padx=5, sticky="ew")

                btn = Button(
                    cell, text=label,
                    bg=COLOR_BG_CARD, fg=COLOR_WHITE_DIM,
                    activebackground=accent, activeforeground=COLOR_BG_DEEP,
                    relief="flat", font=(FONT_MAIN, 10, "bold"), height=2, bd=0,
                    cursor="hand2"
                )
                btn.pack(fill="x")
                btn.bind("<Enter>", lambda e, b=btn, a=accent: b.config(bg=a, fg=COLOR_BG_DEEP))
                btn.bind("<Leave>", lambda e, b=btn: b.config(bg=COLOR_BG_CARD, fg=COLOR_WHITE_DIM))
                setattr(self, attr, btn)

                if attr == "btn_sysinfo":
                    Label(cell, text="⌁ LOCAL", bg=COLOR_BG_PANEL, fg=COLOR_GREEN,
                          font=(FONT_MAIN, 7, "bold")).pack(pady=(4, 0))

        # ── Terminal ──────────────────────────────────────────
        self.term_frame = Frame(self.main_container, bg=COLOR_BG_PANEL, highlightbackground=COLOR_BORDER,
                                 highlightthickness=1)
        self.term_frame.pack(fill="both", expand=True)

        term_header = Frame(self.term_frame, bg=COLOR_BG_CARD)
        term_header.pack(fill="x")
        Label(term_header, text="TERMINAL", bg=COLOR_BG_CARD, fg=COLOR_TEXT_MUTED,
              font=(FONT_MAIN, 9, "bold"), padx=14, pady=6).pack(anchor="w")

        term_body = Frame(self.term_frame, bg=COLOR_BG_PANEL)
        term_body.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        self.terminal_text = Text(
            term_body, bg="#08090B", fg=COLOR_WHITE_DIM,
            font=(FONT_MONO, 11), relief="flat",
            padx=16, pady=14, insertbackground=COLOR_CYAN, bd=0
        )
        self.scrollbar = Scrollbar(term_body, command=self.terminal_text.yview)
        self.terminal_text.config(yscrollcommand=self.scrollbar.set)
        self.terminal_text.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        console.set_widget(self.terminal_text)
        sys.stdout = RedirectText()

        print("[>] WATCH FOX V2.0 - SYSTEM READY")
        print("[*] En attente d'une cible...")
        print("-" * 20)

    def _info_chip(self, parent, label, value):
        chip = Frame(parent, bg=COLOR_BG_CARD, highlightbackground=COLOR_BORDER, highlightthickness=1)
        chip.pack(side="left", padx=(0, 10), ipadx=10, ipady=6)
        Label(chip, text=label, bg=COLOR_BG_CARD, fg=COLOR_TEXT_MUTED,
              font=(FONT_MAIN, 8, "bold")).pack(anchor="w")
        Label(chip, text=value, bg=COLOR_BG_CARD, fg=COLOR_CYAN,
              font=(FONT_MONO, 11, "bold")).pack(anchor="w")
