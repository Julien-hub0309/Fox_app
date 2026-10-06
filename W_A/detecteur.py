from __future__ import annotations
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict


# ───────────────────────────────────────────────────────────────
#   STRUCTURES DE DONNÉES (Data Models)
# ───────────────────────────────────────────────────────────────

@dataclass
class DimensionResult:
    """Représente le résultat d'une dimension linguistique spécifique."""
    name: str
    score: float          # Score normalisé [0, 1] (probabilité IA)
    weight: float         # Poids dans le score final global
    details: dict = field(default_factory=dict)

    @property
    def weighted(self) -> float:
        """Calcul de la contribution pondérée au score total."""
        return self.score * self.weight


@dataclass
class AnalysisResult:
    """Résultat global de l'analyse du texte."""
    score: float                          # Score final [0, 100]
    verdict: str                          # Label lisible ("Très probablement IA", etc.)
    confidence: str                       # Niveau de confiance ("faible" | "modérée" | "élevée")
    dimensions: list[DimensionResult]
    token_count: int
    warnings: list[str]

    def to_dict(self) -> dict:
        """Convertit les résultats dans un dictionnaire prêt pour l'API/affichage."""
        return {
            "score": round(self.score, 2),
            "verdict": self.verdict,
            "confidence": self.confidence,
            "token_count": self.token_count,
            "warnings": self.warnings,
            "dimensions": [
                {
                    "name": d.name,
                    "score": round(d.score, 4),
                    "weight": d.weight,
                    "weighted_contribution": round(d.weighted, 4),
                    "details": d.details,
                }
                for d in self.dimensions
            ],
        }


# ───────────────────────────────────────────────────────────────
#   RÈGLES LINGUISTIQUES (Regular Expressions)
# ───────────────────────────────────────────────────────────────

AI_MARKERS = [
    r"\b(tout d'abord|premièrement|deuxièmement|troisièmement|en premier lieu|"
    r"en second lieu|en conclusion|pour conclure|en résumé|en somme|"
    r"il convient de|il est important de|il est essentiel de|"
    r"dans ce contexte|à cet égard|à titre d'exemple|"
    r"firstly|secondly|thirdly|furthermore|moreover|additionally|"
    r"in conclusion|to summarize|it is worth noting|it is important to|"
    r"in this context|in this regard)\b",
]

SMOOTH_CONNECTORS = re.compile(
    r"\b(de plus|par ailleurs|en outre|cependant|néanmoins|toutefois|"
    r"en revanche|d'une part|d'autre part|quoi qu'il en soit|"
    r"furthermore|however|nevertheless|nonetheless|on the other hand|"
    r"in addition|that being said|with that said)\b",
    re.IGNORECASE,
)

FILLER_WORDS = re.compile(
    r"\b(très|vraiment|absolument|totalement|complètement|"
    r"entièrement|particulièrement|notamment|spécifiquement|"
    r"very|really|absolutely|totally|completely|entirely|"
    r"particularly|specifically|essentially|basically)\b",
    re.IGNORECASE,
)

HUMAN_PUNCT = re.compile(r"[—–…]|\.{3}|!{2,}|\?{2,}")
AI_MARKER_RE = re.compile("|".join(AI_MARKERS), re.IGNORECASE)


# ───────────────────────────────────────────────────────────────
#   UTILITAIRES MATHEMATIQUES ET DE TRAITEMENT TEXTE
# ───────────────────────────────────────────────────────────────

def tokenize(text: str) -> list[str]:
    """Tokenise le texte en minuscules, ne conservant que les mots alfanumériques."""
    return re.findall(r"\b[a-zA-ZÀ-ÿ''\-]+\b", text.lower())


def sentences(text: str) -> list[str]:
    """Sépare le texte en phrases distinctes (longueur minimale garantie)."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if len(p) > 10]


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Assure qu'une valeur reste dans une plage définie."""
    return max(lo, min(hi, value))


def sigmoid_map(x: float, center: float, steepness: float = 10.0) -> float:
    """Fonction sigmoïde pour mapper une valeur en probabilité (score)."""
    return 1 / (1 + math.exp(-steepness * (x - center)))


# ───────────────────────────────────────────────────────────────
#   DIMENSIONS D'ANALYSE LINGUISTIQUE
# ───────────────────────────────────────────────────────────────

def dim_perplexity_proxy(tokens: list[str]) -> DimensionResult:
    """Évalue la perplexité lexicale (mesure de l'entropie). Plus haut = plus imprévisible/humain."""
    if not tokens:
        return DimensionResult("Perplexité lex.", 0.5, 0.20)

    counts = Counter(tokens)
    total = len(tokens)
    probs = [c / total for c in counts.values()]
    # Calcul de l'entropie en base 2 (bits)
    entropy = -sum(p * math.log2(p) for p in probs if p > 0)

    # Le score doit être inversement corrélé à l'entropie calculée pour correspondre à une échelle [0,1] conventionnelle où le haut est IA/faible perplexité
    score = sigmoid_map(-entropy / 9.0, center=2.5, steepness=-0.6) # Ajustement du centre et de la forme pour mieux mapper l'entropie haute vers un score faible (humain).
    score = clamp(score * 1.2) # Multiplicateur pour ajuster l'échelle

    return DimensionResult(
        "Perplexité lex.",
        clamp(score),
        0.20,
        {"entropy_bits": round(entropy, 3), "unique_tokens": len(counts), "total": total},
    )


def dim_sentence_uniformity(sents: list[str]) -> DimensionResult:
    """Évalue l'uniformité de la longueur des phrases. Les textes humains sont plus variés."""
    if len(sents) < 4:
        return DimensionResult("Uniformité phrases", 0.5, 0.15)

    lengths = [len(s.split()) for s in sents]
    mean = sum(lengths) / len(lengths)
    variance = sum((l - mean) ** 2 for l in lengths) / len(lengths)
    std = math.sqrt(variance)
    # Coefficient de variation (CV): std/mean. Plus élevé, plus hétérogène (humain).
    cv = std / mean if mean > 0 else 0

    score = sigmoid_map(cv, center=0.45, steepness=-8.0)
    score = clamp(score * 1.2) # Ajustement de l'échelle

    return DimensionResult(
        "Uniformité phrases",
        clamp(score),
        0.15,
        {"cv": round(cv, 4), "mean_len": round(mean, 1), "std_len": round(std, 1)},
    )


def dim_ai_markers(text: str, tokens: list[str]) -> DimensionResult:
    """Évalue la densité des marqueurs syntaxiques (connecteurs IA, mots de remplissage)."""
    if not tokens:
        return DimensionResult("Marqueurs IA", 0.5, 0.20)

    # Calcul pondéré : Marqueurs > Connecteurs * 0.5 + Remplissages * 0.3 (Les fillers sont moins pénalisants)
    marker_hits = len(AI_MARKER_RE.findall(text))
    connector_hits = len(SMOOTH_CONNECTORS.findall(text))
    filler_hits = len(FILLER_WORDS.findall(text))

    total_hits = marker_hits + connector_hits * 0.5 + filler_hits * 0.3
    # Densité par 100 tokens (pour normaliser)
    density = total_hits / (len(tokens) / 100.0 if len(tokens) > 0 else 1.0)

    score = sigmoid_map(density, center=2.5, steepness=-0.7) # Inverse la courbure: plus de densité -> score plus bas (plus IA).
    score = clamp(score * 1.1) 

    return DimensionResult(
        "Marqueurs IA",
        clamp(score),
        0.20,
        {
            "ai_phrases": marker_hits,
            "smooth_connectors": connector_hits,
            "filler_words": filler_hits,
            "density_per_100tok": round(density, 2),
        },
    )


def dim_punctuation_richness(text: str, sents: list[str]) -> DimensionResult:
    """Évalue la présence de ponctuation humaine (tirés, ellipses, etc.)."""
    if not sents:
        return DimensionResult("Richesse ponctuation", 0.5, 0.10)

    human_marks = len(HUMAN_PUNCT.findall(text))
    total_chars = len(text)
    # Densité par 1000 caractères (pour normaliser l'impact de la longueur du texte)
    density = human_marks / (total_chars / 1000.0 if total_chars > 0 else 1.0)

    score = sigmoid_map(density, center=2.5, steepness=-1.5) # Plus haut est mieux -> score élevé
    score = clamp(score * 1.1) 

    return DimensionResult(
        "Richesse ponctuation",
        clamp(score),
        0.10,
        {"human_punct_count": human_marks, "density_per_1000ch": round(density, 2)},
    )


def dim_lexical_diversity(tokens: list[str]) -> DimensionResult:
    """Évalue la diversité du vocabulaire (ratio types/tokens)."""
    if len(tokens) < 20:
        return DimensionResult("Diversité lexicale", 0.5, 0.10)

    types = len(set(tokens))
    # Utilisation d'une formule statistique robuste pour la diversité (similaire à TTR mais améliorée)
    cttr = types / math.sqrt(2 * len(tokens))

    score = sigmoid_map(cttr, center=4.0, steepness=-0.5) # Plus haut est mieux -> score élevé
    score = clamp(score * 1.1) 

    return DimensionResult(
        "Diversité lexicale",
        clamp(score),
        0.10,
        {"cttr": round(cttr, 4), "types": types, "tokens": len(tokens)},
    )


def dim_structural_patterns(text: str) -> DimensionResult:
    """Évalue les marqueurs de structuration (listes, titres Markdown)."""
    bullet_lines = len(re.findall(r"^\s*[-•\*]\s+.{20,}", text, re.MULTILINE))
    markdown_headers = len(re.findall(r"^#{1,4}\s+\S", text, re.MULTILINE))
    numbered_lists = len(re.findall(r"^\s*\d+[\.\)]\s+.{20,}", text, re.MULTILINE))
    total_lines = max(len(text.splitlines()), 1)

    # Ponderation: Headers (2x) > Bullet > Numbered list. Normalisé par le nombre de lignes pour la densité.
    structure_density = (bullet_lines + markdown_headers * 2 + numbered_lists) / max(total_lines, 5)

    score = sigmoid_map(structure_density, center=1.8, steepness=-1.0) # Plus haut est IA/structuré -> score plus élevé
    score = clamp(score * 1.1) 

    return DimensionResult(
        "Structures IA",
        clamp(score),
        0.10,
        {
            "bullet_lines": bullet_lines,
            "markdown_headers": markdown_headers,
            "numbered_lists": numbered_lists,
        },
    )


def dim_burstiness(sents: list[str]) -> DimensionResult:
    """Évalue l'hétérogénéité des longueurs de phrases (variabilité). Plus élevé = plus humain."""
    if len(sents) < 6:
        return DimensionResult("Burstiness", 0.5, 0.10)

    lengths = sorted(len(s.split()) for s in sents)
    n = len(lengths)
    # Calcul de l'indice de Gini sur les longueurs
    gini = sum((2 * i - n - 1) * l for i, l in enumerate(lengths, 1)) / (n * sum(lengths) if sum(lengths) != 0 else 1)

    score = sigmoid_map(gini, center=0.45, steepness=-12.0) # Plus haut Gini -> score plus élevé
    score = clamp(score * 1.3) 

    return DimensionResult(
        "Burstiness",
        clamp(score),
        0.10,
        {"gini": round(gini, 4), "n_sentences": n},
    )


def dim_hedging_overconfidence(text: str, tokens: list[str]) -> DimensionResult:
    """Évalue le mélange entre affirmation excessive et prudence (indicateurs de style)."""
    if not tokens:
        return DimensionResult("Ton assertif/prudent", 0.5, 0.05)

    overconfident = re.findall(
        r"\b(toujours|jamais|absolument|sans aucun doute|il est certain|"
        r"always|never|absolutely|without doubt|it is certain|undeniably|"
        r"unquestionably|definitively)\b",
        text,
        re.IGNORECASE,
    )
    hedging = re.findall(
        r"\b(peut-être|il semblerait|on pourrait dire|dans une certaine mesure|"
        r"perhaps|it seems|one could argue|to some extent|arguably|"
        r"it is worth considering|it may be)\b",
        text,
        re.IGNORECASE,
    )

    density = (len(overconfident) + len(hedging)) / (len(tokens) / 100.0 if len(tokens) > 0 else 1.0)
    # Le score est basé sur la variabilité du ton (un bon équilibre est humain). Nous utilisons une sigmoïde simple ici.
    score = sigmoid_map(density, center=2.5, steepness=-0.8)
    score = clamp(score * 1.1)

    return DimensionResult(
        "Ton assertif/prudent",
        clamp(score),
        0.05,
        {
            "overconfident_count": len(overconfident),
            "hedging_count": len(hedging),
            "density_per_100tok": round(density, 2),
        },
    )


# ───────────────────────────────────────────────────────────────
#   ANALYSE PRINCIPALE
# ───────────────────────────────────────────────────────────────

MIN_TOKENS = 50


def analyze_text(text: str) -> AnalysisResult:
    """Exécute l'ensemble des dimensions pour obtenir le score final."""
    warnings: list[str] = []
    tokens = tokenize(text)
    sents = sentences(text)

    if len(tokens) < MIN_TOKENS:
        warnings.append(f"Texte court ({len(tokens)} tokens) — résultat peu fiable")

    dimensions = [
        dim_perplexity_proxy(tokens),
        dim_sentence_uniformity(sents),
        dim_ai_markers(text, tokens),
        dim_punctuation_richness(text, sents),
        dim_lexical_diversity(tokens),
        dim_structural_patterns(text),
        dim_burstiness(sents),
        dim_hedging_overconfidence(text, tokens),
    ]

    total_weight = sum(d.weight for d in dimensions)
    # Le score est la moyenne pondérée des scores de chaque dimension
    raw_score = sum(d.weighted for d in dimensions) / total_weight if total_weight > 0 else 1.0
    score = round(clamp(raw_score) * 100, 1)

    # Logique de verdict (Inversion du score : plus bas = humain)
    if score < 25: # Ex-20
        verdict = "Très probablement humain"
    elif score < 45: # Ex-40
        verdict = "Probablement humain"
    elif score < 60: # Ex-55
        verdict = "Incertain (Mélangé)"
    elif score < 80: # Ex-70
        verdict = "Probablement IA"
    else:
        verdict = "Très probablement IA"

    # Logique de confiance
    if len(tokens) < MIN_TOKENS * 0.5:
        confidence = "faible"
    elif len(tokens) < 300:
        confidence = "modérée"
    else:
        confidence = "élevée"

    return AnalysisResult(
        score=score,
        verdict=verdict,
        confidence=confidence,
        dimensions=dimensions,
        token_count=len(tokens),
        warnings=warnings,
    )


# ───────────────────────────────────────────────────────────────
#   LECTURE DE FICHIERS (I/O Handlers)
# ───────────────────────────────────────────────────────────────

def _read_txt(path: Path) -> str:
    """Lit un fichier texte simple."""
    return path.read_text(encoding="utf-8", errors="replace")


def _read_pdf(path: Path) -> str:
    """Lit et extrait du texte d'un PDF (nécessite pdfminer)."""
    try:
        from pdfminer.high_level import extract_text
        return extract_text(str(path))
    except ImportError:
        print("[ERREUR] pip install pdfminer.six est requis pour lire les PDF.")
        return ""


def _read_docx(path: Path) -> str:
    """Lit et extrait du texte d'un fichier DOCX (nécessite python-docx)."""
    try:
        from docx import Document
        doc = Document(str(path))
        # Récupère le texte de tous les paragraphes
        return "\n".join(p.text for p in doc.paragraphs)
    except ImportError:
        print("[ERREUR] pip install python-docx est requis pour lire les DOCX.")
        return ""


def analyze_file(filepath: str | Path) -> AnalysisResult:
    """Point d'entrée pour l'analyse de n'importe quel type de fichier."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {path}")

    ext = path.suffix.lower()
    readers = {
        ".txt": _read_txt,
        ".md": _read_txt,
        ".pdf": _read_pdf,
        ".docx": _read_docx,
    }

    if ext not in readers:
        raise ValueError(f"Format non supporté : {ext}")

    text = readers[ext](path)
    return analyze_text(text)
