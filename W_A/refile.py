from __future__ import annotations

import re
import textwrap


# Styles exposés à l'interface graphique (clé interne -> libellé affiché)
STYLE_LABELS: dict[str, str] = {
    "pave":        "Pavé (bloc unique)",
    "paragraphes": "Paragraphes aérés",
    "liste":       "Liste à puces",
    "numerotee":   "Liste numérotée",
    "titres":      "Titres + sections",
    "dialogue":    "Dialogue / script",
    "cartes":      "Cartes séparées",
    "compact":     "Compact (une ligne)",
}

DEFAULT_STYLE = "pave"

_SENTENCE_END_RE = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÀ-Ý0-9«\"'(])")
_WHITESPACE_RE   = re.compile(r"[ \t]+")
_MULTI_NL_RE     = re.compile(r"\n{2,}")

_BULLET_SYMBOLS = ("•", "-", "*", "–", "—")



def _normalize(text: str) -> str:
    """Nettoie les espaces multiples et les retours à la ligne superflus
    tout en conservant les paragraphes existants si présents."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WHITESPACE_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _MULTI_NL_RE.sub("\n\n", text)
    return text.strip()


def _strip_existing_markup(text: str) -> str:
    """Retire la mise en forme déjà présente (puces, numéros, titres
    markdown) afin de pouvoir réappliquer un nouveau style proprement."""
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        # Supprime puces "- ", "* ", "• "
        stripped = re.sub(r"^[•\-\*–—]\s+", "", stripped)
        # Supprime numérotation "1. ", "1) ", "1 - "
        stripped = re.sub(r"^\d+[\.\)\-]\s+", "", stripped)
        # Supprime titres markdown "### "
        stripped = re.sub(r"^#{1,6}\s+", "", stripped)
        lines.append(stripped)
    return " ".join(lines)


def _split_sentences(text: str) -> list[str]:
    """Découpe un texte en phrases (heuristique simple, sans dépendance)."""
    flat = _strip_existing_markup(_normalize(text))
    flat = _WHITESPACE_RE.sub(" ", flat).strip()
    if not flat:
        return []
    parts = _SENTENCE_END_RE.split(flat)
    sentences = [p.strip() for p in parts if p.strip()]
    return sentences


def _chunk(seq: list, size: int) -> list[list]:
    """Découpe une liste en sous-listes de taille `size` (dernier groupe
    pouvant être plus petit)."""
    if size <= 0:
        size = 1
    return [seq[i:i + size] for i in range(0, len(seq), size)]


def _guess_title(sentence: str, max_words: int = 6) -> str:
    """Génère un titre court à partir d'une phrase (premiers mots
    significatifs, capitalisés)."""
    words = re.findall(r"[\wÀ-ÿ\-']+", sentence)
    words = [w for w in words if w.lower() not in
             {"le", "la", "les", "un", "une", "des", "de", "du", "et",
              "ou", "que", "qui", "à", "au", "aux", "en", "dans", "sur"}]
    if not words:
        words = re.findall(r"[\wÀ-ÿ\-']+", sentence)
    title = " ".join(words[:max_words])
    return title.strip(" ,;:.").capitalize() or "Point clé"


class TextReformatter:
    """Reformate un texte selon un style de présentation choisi.

    Le contenu (les mots) n'est pas réécrit : seule la mise en forme
    visuelle (paragraphes, puces, titres, etc.) est modifiée.
    """

    def __init__(self) -> None:
        self._dispatch = {
            "pave":        self.to_pave,
            "paragraphes": self.to_paragraphes,
            "liste":       self.to_liste,
            "numerotee":   self.to_numerotee,
            "titres":      self.to_titres,
            "dialogue":    self.to_dialogue,
            "cartes":      self.to_cartes,
            "compact":     self.to_compact,
        }

    # ── API publique ──────────────────────────────────────────

    def styles(self) -> dict[str, str]:
        """Retourne le dictionnaire {clé: libellé} des styles disponibles."""
        return dict(STYLE_LABELS)

    def reformat(self, text: str, style: str = DEFAULT_STYLE) -> str:
        """Reformate `text` selon `style`.

        Lève ValueError si `style` est inconnu, et retourne une chaîne
        vide si `text` est vide.
        """
        if not text or not text.strip():
            return ""

        key = self._normalize_style_key(style)
        func = self._dispatch.get(key)
        if func is None:
            raise ValueError(
                f"Style inconnu : {style!r}. "
                f"Styles valides : {', '.join(self._dispatch)}"
            )
        return func(text)

    @staticmethod
    def _normalize_style_key(style: str) -> str:
        """Normalise la clé de style (accents, casse, alias FR)."""
        key = style.strip().lower()
        aliases = {
            "pavé":        "pave",
            "paragraphe":  "paragraphes",
            "paragraphes": "paragraphes",
            "puces":       "liste",
            "bullet":      "liste",
            "numéroté":    "numerotee",
            "numérotée":   "numerotee",
            "numerote":    "numerotee",
            "numerotee":   "numerotee",
            "titre":       "titres",
            "sections":    "titres",
            "script":      "dialogue",
            "carte":       "cartes",
            "card":        "cartes",
            "ligne":       "compact",
            "une_ligne":   "compact",
        }
        return aliases.get(key, key)

    # ── STYLES ────────────────────────────────────────────────

    def to_pave(self, text: str) -> str:
        """Un seul bloc compact : toutes les phrases bout à bout,
        un seul paragraphe."""
        sentences = _split_sentences(text)
        if not sentences:
            return _normalize(text)
        return " ".join(sentences)

    def to_paragraphes(self, text: str, sentences_per_paragraph: int = 3) -> str:
        """Découpe le texte en paragraphes de N phrases (par défaut 3),
        séparés par une ligne vide."""
        sentences = _split_sentences(text)
        if not sentences:
            return _normalize(text)
        groups = _chunk(sentences, sentences_per_paragraph)
        return "\n\n".join(" ".join(g) for g in groups)

    def to_liste(self, text: str) -> str:
        """Transforme chaque phrase en élément de liste à puces."""
        sentences = _split_sentences(text)
        if not sentences:
            return _normalize(text)
        return "\n".join(f"• {s}" for s in sentences)

    def to_numerotee(self, text: str) -> str:
        """Transforme chaque phrase en élément de liste numérotée."""
        sentences = _split_sentences(text)
        if not sentences:
            return _normalize(text)
        return "\n".join(f"{i}. {s}" for i, s in enumerate(sentences, start=1))

    def to_titres(self, text: str, sentences_per_section: int = 2) -> str:
        """Découpe le texte en sections, chacune précédée d'un titre
        généré automatiquement à partir de sa première phrase."""
        sentences = _split_sentences(text)
        if not sentences:
            return _normalize(text)

        groups = _chunk(sentences, sentences_per_section)
        blocks = []
        for group in groups:
            title = _guess_title(group[0])
            body = " ".join(group)
            blocks.append(f"## {title}\n{body}")
        return "\n\n".join(blocks)

    def to_dialogue(self, text: str) -> str:
        """Présente le texte comme un échange alterné entre deux
        intervenants ('A' et 'B'), une phrase par tour de parole."""
        sentences = _split_sentences(text)
        if not sentences:
            return _normalize(text)

        lines = []
        for i, s in enumerate(sentences):
            speaker = "A" if i % 2 == 0 else "B"
            lines.append(f"{speaker} : {s}")
        return "\n".join(lines)

    def to_cartes(self, text: str, sentences_per_card: int = 2) -> str:
        """Découpe le texte en blocs visuellement séparés ('cartes'),
        utiles pour un export façon slides ou fiches."""
        sentences = _split_sentences(text)
        if not sentences:
            return _normalize(text)

        groups = _chunk(sentences, sentences_per_card)
        sep = "─" * 32
        blocks = []
        for idx, group in enumerate(groups, start=1):
            title = _guess_title(group[0])
            body = " ".join(group)
            wrapped = textwrap.fill(body, width=60)
            blocks.append(f"{sep}\n[{idx}] {title}\n{sep}\n{wrapped}")
        return "\n\n".join(blocks)

    def to_compact(self, text: str) -> str:
        """Met tout le texte sur une seule ligne, espaces normalisés."""
        sentences = _split_sentences(text)
        if not sentences:
            return _WHITESPACE_RE.sub(" ", text.replace("\n", " ")).strip()
        return _WHITESPACE_RE.sub(" ", " ".join(sentences)).strip()

_default_reformatter = TextReformatter()


def reformat_text(text: str, style: str = DEFAULT_STYLE) -> str:
    """Fonction de commodité : reformate `text` selon `style`
    en utilisant une instance partagée de TextReformatter."""
    return _default_reformatter.reformat(text, style)


def available_styles() -> dict[str, str]:
    """Retourne le dictionnaire {clé: libellé} des styles disponibles."""
    return _default_reformatter.styles()


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Reformate un texte selon un style de présentation."
    )
    parser.add_argument(
        "texte", nargs="?", default=None,
        help="Texte à reformater (sinon lu depuis stdin).",
    )
    parser.add_argument(
        "--style", "-s", default=DEFAULT_STYLE,
        choices=sorted(STYLE_LABELS.keys()),
        help=f"Style cible (par défaut : {DEFAULT_STYLE}).",
    )
    parser.add_argument(
        "--list-styles", action="store_true",
        help="Affiche la liste des styles disponibles et quitte.",
    )
    args = parser.parse_args()

    if args.list_styles:
        for key, label in STYLE_LABELS.items():
            print(f"{key:12s} : {label}")
        sys.exit(0)

    source = args.texte if args.texte is not None else sys.stdin.read()
    print(reformat_text(source, args.style))