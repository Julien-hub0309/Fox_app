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
    identification: "IdentificationModeleTexte | None" = None

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
            "identification_modele": self.identification.to_dict() if self.identification else None,
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

# Phrases d'auto-référence explicite : le texte se décrit lui-même comme
# produit par une IA. C'est, de très loin, le signal le plus fiable qui
# existe pour ce type d'outil (équivalent du tag logiciel EXIF pour les
# images) — d'où un poids dynamique très élevé dès qu'il est détecté.
AI_SELF_REFERENCE = re.compile(
    r"\b("
    r"as an ai(?: language model| assistant)?|as a language model|"
    r"i(?:'m| am) an ai\b|i(?:'m| am) a large language model|"
    r"i don't have (?:personal )?(?:opinions|feelings|the ability|access)|"
    r"i do not have (?:access to|personal|the ability)|"
    r"my training data|as of my (?:last )?(?:training|knowledge) (?:cutoff|update)|"
    r"i cannot browse the internet|i('m| am) unable to access real-time|"
    r"i don't have real-time (?:access|information)|i'm just an ai|"
    r"en tant qu'ia|en tant qu'assistant ia|en tant que mod[eè]le de langage|"
    r"je suis une ia\b|je suis un mod[eè]le de langage|"
    r"je n'ai pas d'opinions? personnelles?|je n'ai pas accès à internet|"
    r"mes données d'entraînement|je n'ai pas la capacité de"
    r")\b",
    re.IGNORECASE,
)

# Noms de fournisseurs/produits connus, pour la fonction d'identification.
# La seule présence du nom NE SUFFIT PAS (un texte peut simplement parler
# de ChatGPT) : il faut une auto-référence proche pour la confiance "confirmé".
VENDOR_PATTERNS: dict = {
    r"chatgpt": "ChatGPT (OpenAI)",
    r"gpt-?4o?": "GPT-4/4o (OpenAI)",
    r"gpt-?3\.5": "GPT-3.5 (OpenAI)",
    r"\bopenai\b": "OpenAI (modèle non précisé)",
    r"\bclaude\b": "Claude (Anthropic)",
    r"\banthropic\b": "Anthropic (modèle non précisé)",
    r"\bgemini\b": "Gemini (Google)",
    r"\bbard\b": "Bard/Gemini (Google)",
    r"google ai\b": "Google AI (modèle non précisé)",
    r"\bllama\b": "Llama (Meta)",
    r"meta ai\b": "Meta AI (modèle non précisé)",
    r"\bmistral\b": "Mistral AI",
    r"\bcopilot\b": "Copilot (Microsoft/OpenAI)",
    r"perplexity(?:\.ai)?\b": "Perplexity AI",
    r"\bgrok\b": "Grok (xAI)",
    r"\bdeepseek\b": "DeepSeek",
    r"\bqwen\b": "Qwen (Alibaba)",
}
VENDOR_RE = re.compile("|".join(VENDOR_PATTERNS.keys()), re.IGNORECASE)

# "GPTismes" : vocabulaire et tournures statistiquement surreprésentées dans
# les sorties de grands modèles de langage généralistes (largement documenté
# publiquement, notamment par les efforts de nettoyage anti-IA de Wikipédia).
# Signal utile mais générique : il ne permet pas de distinguer un modèle
# précis d'un autre, seulement "style LLM généraliste" vs "style humain".
GPT_CLICHES = re.compile(
    r"\b("
    r"in today's fast-paced world|in the ever-evolving landscape of|"
    r"it is crucial to understand that|let's delve into|delve into|"
    r"unlock the (?:full )?potential|whether you're a .{1,30} or a|"
    r"stands as a testament to|a testament to|plays a pivotal role|"
    r"navigating the complexities of|in the realm of|underscores the importance|"
    r"myriad of|tapestry of|multifaceted|holistic approach|"
    r"boasts a range of|showcasing|meticulous|intricate(?:ly)?|"
    r"garner(?:ed|ing)?|foster(?:ing)?|bolster(?:ing)?|leverage(?:s|d|ing)?|"
    r"seamless(?:ly)?|robust|paramount|pivotal|"
    r"dans le paysage en constante évolution|il est essentiel de comprendre|"
    r"plonger dans|un témoignage de|joue un rôle central|"
    r"dans le domaine de|une approche holistique|une pléthore de|"
    r"il convient de souligner que"
    r")\b",
    re.IGNORECASE,
)

EM_DASH_RE = re.compile(r"[—–]")


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


def dim_self_reference(text: str) -> DimensionResult:
    """Détecte les auto-références explicites ('en tant qu'IA...'). Signal
    le plus fiable du script : poids très élevé dès qu'il est trouvé, quasi
    nul sinon (pour ne pas polluer la moyenne en son absence)."""
    hits = AI_SELF_REFERENCE.findall(text)
    if hits:
        return DimensionResult(
            "Auto-référence IA",
            0.95,
            0.9,
            {"occurrences": len(hits), "exemples": list(dict.fromkeys(hits))[:3]},
        )
    return DimensionResult("Auto-référence IA", 0.5, 0.02, {"occurrences": 0})


def dim_gptismes(text: str, tokens: list[str]) -> DimensionResult:
    """Densité de tournures/vocabulaire typiques des LLM généralistes
    ('delve into', 'tapestry', 'leverage'...). Signal générique : indique un
    style LLM, pas un modèle précis."""
    if not tokens:
        return DimensionResult("GPTismes / clichés LLM", 0.5, 0.25)

    hits = GPT_CLICHES.findall(text)
    density = len(hits) / (len(tokens) / 100.0 if tokens else 1.0)
    score = clamp(density / 5.0)

    return DimensionResult(
        "GPTismes / clichés LLM",
        score,
        0.25,
        {"occurrences": len(hits), "density_per_100tok": round(density, 2)},
    )


def dim_em_dash(text: str) -> DimensionResult:
    """Densité de tirets cadratins/demi-cadratins. Surreprésentés dans de
    nombreuses sorties de LLM (signal faible et non spécifique à lui seul :
    certains styles d'écriture humains en abusent aussi)."""
    total_chars = len(text)
    if total_chars < 200:
        return DimensionResult("Densité tirets longs", 0.5, 0.03)

    hits = len(EM_DASH_RE.findall(text))
    density = hits / (total_chars / 1000.0)
    score = clamp(density / 8.0)

    return DimensionResult(
        "Densité tirets longs",
        score,
        0.08,
        {"occurrences": hits, "density_per_1000ch": round(density, 2)},
    )


def dim_paragraph_uniformity(text: str) -> DimensionResult:
    """Évalue l'homogénéité de longueur des paragraphes. Les LLM produisent
    souvent des paragraphes très réguliers ; l'écriture humaine varie
    davantage leur taille au fil du texte."""
    paragraphes = [p for p in re.split(r"\n\s*\n", text.strip()) if len(p.split()) >= 5]
    if len(paragraphes) < 3:
        return DimensionResult("Uniformité paragraphes", 0.5, 0.03)

    longueurs = [len(p.split()) for p in paragraphes]
    moyenne = sum(longueurs) / len(longueurs)
    variance = sum((l - moyenne) ** 2 for l in longueurs) / len(longueurs)
    cv = math.sqrt(variance) / moyenne if moyenne > 0 else 0

    score = clamp(1.0 - cv / 0.6)

    return DimensionResult(
        "Uniformité paragraphes",
        score,
        0.12,
        {"cv": round(cv, 4), "n_paragraphes": len(paragraphes), "longueur_moyenne": round(moyenne, 1)},
    )


def dim_repetition_ngrammes(tokens: list[str]) -> DimensionResult:
    """Mesure la part de 4-grammes qui se répètent dans le texte. Un style
    humain spontané varie davantage sa formulation ; un texte généré peut
    réutiliser les mêmes tournures/structures à plusieurs reprises."""
    if len(tokens) < 40:
        return DimensionResult("Répétition de structures", 0.5, 0.05)

    ngrammes = [tuple(tokens[i:i + 4]) for i in range(len(tokens) - 3)]
    compte = Counter(ngrammes)
    repetes = sum(1 for c in compte.values() if c > 1)
    ratio = repetes / len(compte) if compte else 0

    score = clamp(ratio * 3.0)

    return DimensionResult(
        "Répétition de structures",
        score,
        0.10,
        {"ratio_4grammes_repetes": round(ratio, 4), "total_4grammes_uniques": len(compte)},
    )


# ───────────────────────────────────────────────────────────────
#   IDENTIFICATION DU MODÈLE / FOURNISSEUR
# ───────────────────────────────────────────────────────────────

@dataclass
class IdentificationModeleTexte:
    """Résultat de la tentative d'identification du générateur de texte."""
    modele: Optional[str]       # nom canonique, ou None si inconnu
    confiance: str               # "confirmé" | "probable" | "spéculatif" | "inconnu"
    methode: str
    details: str
    candidats: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "modele": self.modele,
            "confiance": self.confiance,
            "methode": self.methode,
            "details": self.details,
            "candidats": self.candidats,
        }


def identifier_modele_texte(text: str, score_global: float) -> IdentificationModeleTexte:
    """Tente d'identifier QUEL fournisseur/modèle a probablement produit le
    texte. Important : à la différence des métadonnées d'une image, un texte
    ne porte normalement AUCUNE preuve technique de son origine. Toute
    identification au-delà d'une auto-référence explicite est donc une
    hypothèse stylistique faible, jamais une preuve."""
    vendor_matches = list(VENDOR_RE.finditer(text))

    if vendor_matches:
        # Un nom de fournisseur est-il trouvé À PROXIMITÉ IMMÉDIATE d'une
        # auto-référence ("en tant que Claude, je...") ? C'est le seul cas
        # où l'on peut parler de confiance "confirmée".
        self_ref_spans = [m.span() for m in AI_SELF_REFERENCE.finditer(text)]
        for vm in vendor_matches:
            v_start, v_end = vm.span()
            for s_start, s_end in self_ref_spans:
                if abs(v_start - s_end) < 80 or abs(s_start - v_end) < 80:
                    nom = next(
                        (v for k, v in VENDOR_PATTERNS.items() if re.search(k, vm.group(), re.IGNORECASE)),
                        vm.group(),
                    )
                    return IdentificationModeleTexte(
                        modele=nom,
                        confiance="confirmé",
                        methode="auto-référence explicite à proximité d'un nom de fournisseur",
                        details=(
                            f"Le texte se présente lui-même comme une sortie de « {nom} » "
                            f"(passage trouvé : « {vm.group()} » proche d'une formule "
                            "d'auto-référence IA)."
                        ),
                    )

        # Nom de fournisseur présent mais sans auto-référence proche : peut
        # être une signature/footer ("— Généré par ChatGPT"), ou simplement
        # un texte qui PARLE de cet outil sans en être issu.
        noms = sorted({
            v for k, v in VENDOR_PATTERNS.items()
            for m in vendor_matches if re.search(k, m.group(), re.IGNORECASE)
        })
        return IdentificationModeleTexte(
            modele=noms[0] if len(noms) == 1 else None,
            confiance="probable",
            methode="nom de fournisseur mentionné, sans auto-référence proche",
            details=(
                f"Fournisseur(s)/produit(s) mentionné(s) dans le texte : {', '.join(noms)}. "
                "Attention : ceci peut aussi être un texte humain qui parle de cet outil, "
                "pas nécessairement un texte qu'il a généré."
            ),
            candidats=noms[1:] if len(noms) > 1 else [],
        )

    # Auto-référence seule, sans nom de fournisseur.
    if AI_SELF_REFERENCE.search(text):
        return IdentificationModeleTexte(
            modele=None,
            confiance="probable",
            methode="auto-référence générique sans nom de fournisseur",
            details=(
                "Le texte se décrit comme généré par une IA, mais ne nomme aucun "
                "fournisseur ou modèle précis."
            ),
        )

    # Aucun indice direct : au mieux une tendance stylistique générale.
    if score_global >= 70:
        return IdentificationModeleTexte(
            modele=None,
            confiance="spéculatif",
            methode="score stylistique global élevé, sans preuve directe",
            details=(
                "Style globalement compatible avec un grand modèle de langage "
                "généraliste, mais SANS preuve technique. Il n'existe pas de "
                "méthode fiable, publiquement validée, permettant de distinguer "
                "un fournisseur précis (OpenAI/Anthropic/Google/...) à partir du "
                "seul style d'écriture : ce niveau ne doit pas être traité comme "
                "une identification, seulement comme une piste à vérifier "
                "autrement (métadonnées de la plateforme source, historique de "
                "conversation, déclaration de l'auteur...)."
            ),
        )

    return IdentificationModeleTexte(
        modele=None,
        confiance="inconnu",
        methode="aucun indice exploitable",
        details="Aucune auto-référence, aucun nom de fournisseur, aucun signal stylistique fort.",
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
        dim_self_reference(text),
        dim_gptismes(text, tokens),
        dim_em_dash(text),
        dim_paragraph_uniformity(text),
        dim_repetition_ngrammes(tokens),
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

    identification = identifier_modele_texte(text, score)

    return AnalysisResult(
        score=score,
        verdict=verdict,
        confidence=confidence,
        dimensions=dimensions,
        token_count=len(tokens),
        warnings=warnings,
        identification=identification,
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


# ───────────────────────────────────────────────────────────────
#   AFFICHAGE ET CLI
# ───────────────────────────────────────────────────────────────

def afficher_resultat(resultat: AnalysisResult, source: str = "") -> None:
    print("=" * 70)
    if source:
        print(f"Source     : {source}")
    print(f"Score IA   : {resultat.score:.1f} / 100")
    print(f"Verdict    : {resultat.verdict}")
    print(f"Confiance  : {resultat.confidence}")
    print(f"Tokens     : {resultat.token_count}")
    print("-" * 70)
    for d in resultat.dimensions:
        print(f"  • {d.name} — score={d.score:.2f} (poids {d.weight})")
        if d.details:
            print(f"      {d.details}")
    if resultat.identification:
        ident = resultat.identification
        print("-" * 70)
        print(f"Modèle probable : {ident.modele or 'non identifié'}")
        print(f"  Confiance   : {ident.confiance}")
        print(f"  Méthode     : {ident.methode}")
        print(f"  Détails     : {ident.details}")
        if ident.candidats:
            print(f"  Autres candidats possibles : {', '.join(ident.candidats)}")
    if resultat.warnings:
        print("-" * 70)
        for w in resultat.warnings:
            print(f"  ! {w}")
    print("=" * 70)
    print(
        "Rappel : ceci est une analyse heuristique de style, pas une preuve "
        "formelle. Sans auto-référence explicite ou preuve de plateforme "
        "(historique de compte, logs...), aucun outil ne peut garantir qu'un "
        "texte a été écrit par une IA, ni identifier avec certitude quel "
        "modèle précis l'a produit."
    )


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(
        description="Détecteur heuristique de texte potentiellement généré par IA.",
    )
    groupe = parser.add_mutually_exclusive_group(required=True)
    groupe.add_argument("chemin", nargs="?", help="Fichier texte/.md/.pdf/.docx à analyser")
    groupe.add_argument("--texte", help="Texte à analyser directement (entre guillemets)")
    parser.add_argument("--json", action="store_true", help="Sort le résultat au format JSON.")
    args = parser.parse_args(argv)

    if args.texte:
        resultat = analyze_text(args.texte)
        source = "(texte fourni en ligne de commande)"
    else:
        try:
            resultat = analyze_file(args.chemin)
            source = args.chemin
        except (FileNotFoundError, ValueError) as e:
            print(f"Erreur : {e}", file=sys.stderr)
            return 1

    if args.json:
        print(_json.dumps(resultat.to_dict(), ensure_ascii=False, indent=2))
    else:
        afficher_resultat(resultat, source)
    return 0


if __name__ == "__main__":
    sys.exit(main())