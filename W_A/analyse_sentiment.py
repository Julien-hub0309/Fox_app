#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analyseur de sentiments, émotions, sarcasme et sous-entendus (français)

Usage :
    python analyse_sentiment.py "Votre texte ici"
    python analyse_sentiment.py -f message.txt --sentences
    python analyse_sentiment.py -f messages.txt --batch --json > resultats.json
    echo "Super, encore en retard..." | python analyse_sentiment.py --ml

Options :
    -f, --file       lire le texte depuis un fichier
    --batch          une analyse par ligne (avec -f ou stdin)
    --sentences      détail phrase par phrase + trajectoire émotionnelle
    --ml             active les modèles transformers (sentiment, émotions,
                     ironie, sous-entendus) – pip install transformers torch
    --json           sortie JSON (exploitable par d'autres programmes)

Le moteur « règles » fonctionne sans aucune dépendance. Il gère notamment :
négations ("pas mal"), intensificateurs ("très", "un peu"), concessions
("bon mais cher"), MAJUSCULES, émojis, ironie, litotes, reproches, etc.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple


# ════════════════════════════════════════════════════════════════════════════
#  Utilitaires
# ════════════════════════════════════════════════════════════════════════════

def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def norm(s: str) -> str:
    """Minuscule, sans accents, apostrophes normalisées."""
    s = s.lower().replace("’", "'").replace("œ", "oe").replace("æ", "ae")
    return strip_accents(s)


TOKEN_RE = re.compile(r"[a-z]+")
SENT_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|\n+")


def _build(spec: Dict[str, float]) -> Dict[str, float]:
    """'heureux|heureuse': 2.5  ->  {'heureux': 2.5, 'heureuse': 2.5}"""
    out: Dict[str, float] = {}
    for key, val in spec.items():
        for form in key.split("|"):
            out[norm(form)] = val
    return out


def gauge(score: float, width: int = 21) -> str:
    pos = round((score + 1) / 2 * (width - 1))
    mid = width // 2
    return "".join("●" if i == pos else ("┼" if i == mid else "─")
                   for i in range(width))


# ════════════════════════════════════════════════════════════════════════════
#  Lexiques
# ════════════════════════════════════════════════════════════════════════════

LEXICON = _build({
    # ── positifs ──
    "excellent|excellente": 3, "parfait|parfaite": 3, "magnifique": 3,
    "merveilleux|merveilleuse": 3, "fantastique": 3, "extraordinaire": 3,
    "superbe": 3, "genial|geniale": 2.5, "formidable": 2.5, "brillant|brillante": 2.5,
    "super": 2, "top": 2, "incroyable": 2, "impressionnant|impressionnante": 2,
    "cool": 1.5, "bon|bonne": 1.5, "bien": 1.5, "mieux": 1.2,
    "meilleur|meilleure": 2, "beau|belle": 2, "joli|jolie": 1.5,
    "agreable": 1.5, "sympa|sympathique": 1.5, "gentil|gentille": 2,
    "aimable": 1.5, "heureux|heureuse": 2.5, "content|contente": 2,
    "satisfait|satisfaite": 2, "ravi|ravie": 2.5, "enchante|enchantee": 2.5,
    "soulage|soulagee": 2, "fier|fiere": 2, "rassure|rassuree": 1.5,
    "confiant|confiante": 1.5, "reconnaissant|reconnaissante": 2,
    "merci": 1.5, "bravo": 2, "felicitations": 2.5, "adore|adorer|adorable": 3,
    "aime|aimer": 2, "apprecie|apprecier": 2, "plaisir": 2, "joie": 2.5,
    "bonheur": 3, "reussi|reussie|reussite": 2, "succes": 2, "victoire": 2,
    "positif|positive": 1.5, "optimiste": 1.5, "efficace": 1.5, "utile": 1.5,
    "facile": 1, "simple": 0.8, "rapide": 1, "recommande": 2, "espoir": 1.5,
    "chance": 1.5, "sourire": 1.5, "amour": 2.5, "waouh|wow": 1.5,
    # ── négatifs ──
    "mauvais|mauvaise": -2, "mal": -1.5, "horrible": -3, "affreux|affreuse": -3,
    "atroce": -3, "nul|nulle": -2.5, "pourri|pourrie": -2.5,
    "catastrophe|catastrophique": -3, "desastre|desastreux": -3,
    "mediocre": -1.8, "deteste|detester|hais|hait": -3, "haine": -3,
    "triste": -2, "malheureux|malheureuse": -2.5, "decu|decue|deception": -2.5,
    "decevant|decevante": -2.5, "colere": -2.5, "enerve|enervee": -2.5,
    "furieux|furieuse": -3, "agace|agacee": -2, "irrite|irritee": -2,
    "frustre|frustree|frustration": -2.5, "fache|fachee": -2,
    "probleme": -1.5, "difficile": -1, "penible": -2, "complique|compliquee": -1,
    "ennuyeux|ennuyeuse": -2, "ennui": -1.5, "inquiet|inquiete|inquietant": -2,
    "stresse|stressee|stress": -2, "angoisse|angoissant": -2.5,
    "peur": -2, "anxieux|anxieuse": -2, "fatigue|fatiguee": -1.5,
    "epuise|epuisee": -2.5, "deprime|deprimee": -3, "dommage": -1.5,
    "regret|regrette": -2, "honte": -2.5, "desole|desolee": -1,
    "insupportable": -3, "inacceptable": -3, "injuste": -2.5,
    "ridicule": -2, "stupide": -2, "idiot|idiote": -2.5, "lamentable": -3,
    "echec": -2.5, "echouer": -2.5, "perdre|perdu|perdue": -1.5,
    "rate|ratee": -1.5, "panne": -1.5, "bug": -1.5, "erreur": -1.5,
    "retard": -1.5, "lent|lente": -1, "dangereux|dangereuse": -2,
    "douleur": -2.5, "negatif|negative": -1.5, "pessimiste": -1.5,
    "degoute|degoutant|degoutante": -3, "ecoeure": -3, "trahi|trahie": -3,
    "seul|seule": -1.5, "abandonne|abandonnee": -2.5, "blesse|blessee": -2.5,
    "mepris": -3, "arnaque": -3, "marre": -2.5, "galere": -2,
})

INTENSIFIERS = {
    "tres": 1.5, "trop": 1.3, "vraiment": 1.4, "tellement": 1.5,
    "extremement": 1.8, "totalement": 1.6, "completement": 1.6,
    "absolument": 1.7, "franchement": 1.3, "hyper": 1.5, "ultra": 1.5,
    "assez": 0.85, "plutot": 0.9, "peu": 0.5, "legerement": 0.6,
    "relativement": 0.8, "moyennement": 0.6,
}

NEGATORS = {"pas", "jamais", "rien", "aucun", "aucune", "sans", "ni",
            "nullement", "guere"}
CONTRAST = {"mais", "cependant", "pourtant", "toutefois", "neanmoins"}

# Locutions dont le sens n'est pas la somme des mots
PHRASE_SUBS = {
    "merci pour rien": "nul",
    "pas terrible": "mediocre", "pas top": "mediocre",
    "pas fou": "mediocre", "pas ouf": "mediocre",
    "bien sur": "", "bien entendu": "", "bien que": "", "ou bien": "",
    "si bien": "",
}

EMOJI_SENT = {
    "😂": 1, "🤣": 1, "😊": 1.5, "😄": 1.5, "😁": 1.5, "😀": 1.5, "🥳": 2,
    "🎉": 1.5, "❤": 2, "💕": 2, "💖": 2, "😍": 2.5, "🥰": 2.5, "😘": 1.5,
    "👍": 1.5, "👏": 1.5, "🙏": 1,
    "😢": -2, "😭": -2.5, "😡": -3, "😠": -2.5, "🤬": -3, "😞": -2, "😔": -2,
    "💔": -2.5, "😱": -1.5, "😨": -1.5, "😰": -1.5, "👎": -2, "🤢": -2.5,
    "🤮": -2.5, "😤": -2, "🙄": -1, "😒": -1.5,
}

EMOTION_LEX = {
    "joie": ("heureux heureuse content contente joie ravi ravie rire sourire "
             "bonheur fete genial super youpi hourra haha hihi lol mdr ptdr "
             "😂 😊 😄 😁 🥳 🎉 😀 🤣").split(),
    "tristesse": ("triste tristesse pleurer pleure deprime deprimee malheureux "
                  "snif chagrin larmes seul seule manque melancolie decu decue "
                  "deception 😢 😭 😞 😔 💔").split(),
    "colère": ("colere enerve enervee furieux furieuse fache agace agacee rage "
               "marre exaspere insupportable grrr irrite 😠 😡 🤬 😤").split(),
    "peur": ("peur angoisse stress stresse stressee panique inquiet inquiete "
             "anxieux anxieuse effraye terrifie crainte 😨 😱 😰").split(),
    "amour": ("amour aime adore cherie coeur tendresse bisou bisous tendre "
              "passion ❤ 💕 💖 😍 🥰 😘").split(),
    "surprise": ("wow waouh incroyable etonne etonnee surpris surprise choque "
                 "stupefait inattendu 😮 😲 😯 🤯").split(),
    "dégoût": ("degoute degoutant degoutante beurk ecoeure repugnant 🤢 🤮").split(),
}
EMO_LOOKUP: Dict[str, List[str]] = {}
for _emo, _words in EMOTION_LEX.items():
    for _w in _words:
        EMO_LOOKUP.setdefault(norm(_w), []).append(_emo)

SARCASM_PHRASES = {
    "comme par hasard": 0.5, "quelle surprise": 0.5, "merci pour rien": 0.7,
    "bien sur": 0.3, "evidemment": 0.2, "c'est ca": 0.3, "tu m'etonnes": 0.3,
    "sans blague": 0.4, "tu parles": 0.35, "quel talent": 0.4,
    "quelle idee": 0.3, "grand bien te fasse": 0.4,
    "bonne chance avec ca": 0.4, "non mais": 0.2, "ca alors": 0.2,
    "trop fort": 0.25, "on n'est pas sortis": 0.2, "decidement": 0.2,
}

# (regex sur texte normalisé, type, interprétation)
SUBTEXT_RULES: List[Tuple[str, str, str]] = [
    (r"\b(sans (vouloir )?(te |vous )?(vexer|offenser|blesser|froisser)|je ne dis pas que|"
     r"pas pour critiquer|ne m'en veux pas|ne le prends pas mal|ne le prenez pas mal)",
     "Préambule de critique",
     "Annonce une remarque désagréable, adoucie à l'avance"),
    (r"\b(comme tu veux|comme vous voulez|fais comme tu veux|faites comme vous voulez|"
     r"si ca te fait plaisir|si tu y tiens|fais ce que tu veux|a ta guise)",
     "Passif-agressif / résignation",
     "Accord de façade ; contrariété ou désaccord probable"),
    (r"\b(on verra|je vais voir|je te dis ca|on en reparle|je vais y reflechir|"
     r"pas maintenant|peut etre|plus tard)\b",
     "Évitement / ajournement",
     "Refus ou réticence adoucis, sans engagement ferme"),
    (r"\b(interessant|original|particulier|audacieux|special|surprenant)\b",
     "Euphémisme ambigu",
     "Peut masquer une réserve ou une désapprobation"),
    (r"\b(pas mal|pas trop mal|pas terrible|pas top|pas fou|pas ouf|ca peut aller|"
     r"correct|passable|bof|mouais)\b",
     "Litote / enthousiasme limité",
     "Évaluation tiède : peu enthousiaste, voire négative"),
    (r"\b(comme d'habitude|une fois de plus|a chaque fois|comme toujours|"
     r"toujours la meme chose|tu ne [a-z' ]{0,25}jamais|tu fais toujours|"
     r"tu es toujours|encore en retard|encore une fois)\b",
     "Reproche récurrent",
     "Généralisation (toujours / jamais) : frustration accumulée"),
    (r"\b(tu pourrais|vous pourriez|ca serait bien (que|si|de)|il faudrait|tu devrais|"
     r"vous devriez|il serait (bien|temps)|ce serait (bien|mieux)|j'aimerais bien que)",
     "Demande indirecte",
     "Formulée comme une suggestion mais attend une action"),
    (r"\b(ce n'est rien|c'est rien|c'est pas grave|pas grave|"
     r"ne t'inquiete pas pour moi|ne t'en fais pas pour moi|t'en fais pas pour moi)\b",
     "Minimisation émotionnelle",
     "Peut cacher une blessure ou un besoin de réassurance"),
    (r"\b(laisse tomber|peu importe|oublie ca|bref|de toute facon|tant pis|"
     r"c'est pas la peine|a quoi bon|je m'en fiche|ca m'est egal|whatever)\b",
     "Retrait / désengagement",
     "Lassitude ou rupture de dialogue, souvent après une frustration"),
    (r"\b(apres tout ce que|moi qui|personne ne|tu ne penses (qu'|a)|c'est toujours moi)",
     "Culpabilisation",
     "Cherche à faire ressentir une dette ou une injustice"),
    (r"\b(sinon|sans quoi|faute de quoi|dans le cas contraire|ne me pousse pas|"
     r"ne me cherche pas|dernier avertissement|derniere chance|derniere fois)\b",
     "Menace / ultimatum voilé",
     "Annonce une conséquence si la demande n'est pas satisfaite"),
    (r"\b(en fait|honnetement|franchement|a vrai dire|pour etre honnete|"
     r"soyons honnetes|pour etre franc)\b",
     "Marqueur de franchise",
     "Précède souvent une vérité inconfortable ou un désaccord"),
    (r"\b(je suppose|j'imagine|je crois|il me semble|ca depend|si tu veux|si vous voulez)\b",
     "Atténuation / incertitude",
     "Avis exprimé sans s'engager (prudence ou retenue)"),
    (r"\b(oui oui|d'accord d'accord|ok tu as raison|tu as raison hein|c'est ca)\b",
     "Concession sans conviction",
     "Cède pour clore la discussion plutôt que par adhésion"),
    (r"\b(si seulement|j'aurais aime que|j'aurais voulu que|j'avais besoin de)\b",
     "Attente déçue",
     "Exprime un manque sans accuser directement"),
    (r"\b(je dis ca je dis rien|je dis ca comme ca|je dis rien)\b",
     "Insinuation",
     "Insinue quelque chose sans l'assumer"),
    (r"\b(pas de nouvelles|tu ne reponds pas|pas de reponse|silence radio|tu m'ignores)\b",
     "Reproche d'absence",
     "Sentiment d'être ignoré ou négligé"),
]

FORMAL = {"vous", "veuillez", "cordialement", "madame", "monsieur", "messieurs",
          "salutations", "respectueusement", "votre", "vos", "pourriez"}
INFORMAL = {"tu", "toi", "ton", "ta", "tes", "salut", "slt", "coucou", "mdr",
            "lol", "ptdr", "ouais", "pote", "truc", "kiff", "bof", "cc", "wesh",
            "mec", "putain", "bah", "ben"}
POLITE = {"merci", "svp", "stp", "bonjour", "bonsoir", "cordialement",
          "excusez", "pardon", "desole", "desolee", "veuillez"}
URGENT_RE = re.compile(
    r"\b(urgent|urgence|vite|immediatement|asap|rapidement|tout de suite|"
    r"au plus vite|sans attendre|des que possible)\b")


# ════════════════════════════════════════════════════════════════════════════
#  Backend ML optionnel (transformers)
# ════════════════════════════════════════════════════════════════════════════

class MLBackend:
    SENT_MODEL = "nlptown/bert-base-multilingual-uncased-sentiment"
    ZS_MODEL = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"

    EMO_LABELS = {
        "la joie": "joie", "la tristesse": "tristesse", "la colère": "colère",
        "la peur": "peur", "l'amour": "amour", "la surprise": "surprise",
        "le dégoût": "dégoût",
    }
    SUBTEXT_LABELS = [
        "un reproche", "une critique déguisée", "une demande indirecte",
        "de l'évitement", "de la passivité-agressivité", "une menace voilée",
        "un compliment sincère", "aucun sous-entendu",
    ]

    def __init__(self) -> None:
        self.available = False
        self.error: Optional[str] = None
        self._sent = None
        self._zs = None
        try:
            import transformers  # noqa: F401
            self.available = True
        except ImportError:
            self.error = "transformers non installé (pip install transformers torch)"

    @staticmethod
    def _device():
        try:
            import torch
            if torch.cuda.is_available():
                return 0
            mps = getattr(torch.backends, "mps", None)
            if mps is not None and mps.is_available():
                return "mps"
        except Exception:
            pass
        return -1

    def _load(self) -> bool:
        if not self.available:
            return False
        if self._sent is not None and self._zs is not None:
            return True
        try:
            from transformers import pipeline
            dev = self._device()
            print("⏳ Chargement des modèles (première fois : téléchargement)…",
                  file=sys.stderr)
            self._sent = pipeline("text-classification", model=self.SENT_MODEL,
                                  device=dev)
            self._zs = pipeline("zero-shot-classification", model=self.ZS_MODEL,
                                device=dev)
            return True
        except Exception as e:  # réseau, mémoire, version…
            self.error = f"chargement impossible : {e}"
            self.available = False
            return False

    def analyze(self, text: str) -> Optional[Dict[str, Any]]:
        if not self._load():
            return None
        text = text[:1500]
        try:
            # 1) Sentiment (1 à 5 étoiles -> [-1, 1])
            res = self._sent(text, top_k=None, truncation=True, max_length=512)
            if res and isinstance(res[0], list):
                res = res[0]
            expected = sum(int(r["label"].split()[0]) * r["score"] for r in res)
            sentiment = round((expected - 3) / 2, 3)

            # 2) Émotions (zero-shot multi-label)
            z = self._zs(text, candidate_labels=list(self.EMO_LABELS),
                         hypothesis_template="Ce texte exprime {}.",
                         multi_label=True)
            emotions = {self.EMO_LABELS[l]: round(s, 3)
                        for l, s in zip(z["labels"], z["scores"])}

            # 3) Ironie
            z = self._zs(text,
                         candidate_labels=["de l'ironie ou du sarcasme",
                                           "un propos sincère"],
                         hypothesis_template="Ce message est plutôt {}.")
            irony = round(dict(zip(z["labels"], z["scores"]))
                          ["de l'ironie ou du sarcasme"], 3)

            # 4) Sous-entendus
            z = self._zs(text, candidate_labels=self.SUBTEXT_LABELS,
                         hypothesis_template="Ce message contient {}.",
                         multi_label=True)
            subtext = {l: round(s, 3) for l, s in zip(z["labels"], z["scores"])}

            return {"sentiment": sentiment, "emotions": emotions,
                    "irony": irony, "subtext": subtext}
        except Exception as e:
            self.error = f"erreur d'analyse ML : {e}"
            return None


# ════════════════════════════════════════════════════════════════════════════
#  Analyseur
# ════════════════════════════════════════════════════════════════════════════

class SentimentAnalyzer:
    def __init__(self, use_ml: bool = False) -> None:
        self.ml: Optional[MLBackend] = MLBackend() if use_ml else None

    # ── lexique ────────────────────────────────────────────────────────────
    @staticmethod
    def _lex(tok: str) -> Optional[float]:
        if tok in LEXICON:
            return LEXICON[tok]
        if len(tok) > 3:
            for suf in ("s", "x", "es"):
                if tok.endswith(suf) and tok[:-len(suf)] in LEXICON:
                    return LEXICON[tok[:-len(suf)]]
        return None

    @staticmethod
    def _is_negated(seg: List[str], i: int) -> bool:
        window = seg[max(0, i - 3):i]
        for j, t in enumerate(window):
            if t in NEGATORS:
                return True
            if t == "plus" and any(x in ("ne", "n") for x in window[:j]):
                return True
        return False

    # ── sentiment d'une phrase ─────────────────────────────────────────────
    def score_sentence(self, sent: str) -> Dict[str, Any]:
        n = norm(sent)
        for a, b in PHRASE_SUBS.items():
            n = re.sub(r"\b" + re.escape(a) + r"\b", b, n)
        tokens = TOKEN_RE.findall(n)

        # Découpage en propositions autour de « mais »
        segments: List[List[str]] = [[]]
        for t in tokens:
            if t in CONTRAST:
                segments.append([])
            else:
                segments[-1].append(t)
        segments = [s for s in segments if s] or [[]]
        weights = ([0.75] * (len(segments) - 1) + [1.35]
                   if len(segments) > 1 else [1.0])

        caps = {norm(w) for w in re.findall(r"\b[^\W\d_]{3,}\b", sent) if w.isupper()}
        pos: List[Tuple[str, float]] = []
        neg: List[Tuple[str, float]] = []
        raw = 0.0

        for seg, weight in zip(segments, weights):
            mult, ttl = 1.0, 0
            for i, tok in enumerate(seg):
                if tok in INTENSIFIERS:
                    mult, ttl = INTENSIFIERS[tok], 2
                    continue
                val = self._lex(tok)
                if val is None:
                    if ttl:
                        ttl -= 1
                        if not ttl:
                            mult = 1.0
                    continue
                v = val * (mult if ttl else 1.0)
                mult, ttl = 1.0, 0
                if self._is_negated(seg, i):
                    v *= -0.75
                if tok in caps:
                    v *= 1.3
                v *= weight
                raw += v
                (pos if v > 0 else neg).append((tok, round(v, 2)))

        for ch in sent:
            if ch in EMOJI_SENT:
                v = EMOJI_SENT[ch]
                raw += v
                (pos if v > 0 else neg).append((ch, v))

        excl = min(sent.count("!"), 3)
        raw *= 1 + 0.12 * excl
        score = raw / math.sqrt(raw * raw + 15)
        return {
            "text": sent, "raw": raw, "score": round(score, 3),
            "pos": pos, "neg": neg, "hits": len(pos) + len(neg),
            "tokens": len(tokens),
        }

    # ── émotions ───────────────────────────────────────────────────────────
    def detect_emotions(self, text: str) -> Dict[str, float]:
        counts: Counter = Counter()
        for tok in TOKEN_RE.findall(norm(text)):
            cands = EMO_LOOKUP.get(tok)
            if cands is None and len(tok) > 3:
                for suf in ("s", "x", "es"):
                    if tok.endswith(suf):
                        cands = EMO_LOOKUP.get(tok[:-len(suf)])
                        if cands:
                            break
            for e in cands or []:
                counts[e] += 1
        for ch in text:
            for e in EMO_LOOKUP.get(ch, []):
                counts[e] += 1
        total = sum(counts.values())
        return {e: round(c / total, 2) for e, c in counts.most_common()} if total else {}

    # ── sarcasme ───────────────────────────────────────────────────────────
    def detect_sarcasm(self, text: str, sentences: List[Dict[str, Any]]) -> Dict[str, Any]:
        signals: List[str] = []
        score = 0.0

        def add(w: float, why: str) -> None:
            nonlocal score
            if why not in signals:
                signals.append(why)
                score += w

        n_full = norm(text)
        for phrase, w in SARCASM_PHRASES.items():
            if re.search(r"\b" + re.escape(phrase) + r"\b", n_full):
                add(w, f"Expression typique : « {phrase} »")

        has_pos = False
        for res in sentences:
            strong_pos = [w for w, v in res["pos"] if v >= 1.5]
            strong_neg = [w for w, v in res["neg"] if v <= -1.5]
            has_pos = has_pos or bool(strong_pos)
            if strong_pos and strong_neg:
                add(0.3, f"Contradiction dans une même phrase (« {strong_pos[0]} » vs « {strong_neg[0]} »)")
            if strong_pos and re.search(r"\b(encore|toujours|deja|decidement)\b", norm(res["text"])):
                add(0.2, "Mot positif associé à « encore / toujours / déjà »")

        if any(ch in text for ch in "🙄😒🙃😏"):
            add(0.35, "Émoji d'ironie (🙄 😒 🙃 😏)")
        if re.search(r"(^|\s)/s\b", text):
            add(0.8, "Marqueur explicite « /s »")
        for m in re.finditer(r"[«\"“]\s*([^»\"”]{1,25}?)\s*[»\"”]", text):
            if any((self._lex(t) or 0) >= 1.5 for t in TOKEN_RE.findall(norm(m.group(1)))):
                add(0.3, f"Mot positif entre guillemets : « {m.group(1)} »")
        if has_pos and re.search(r"([a-zà-ÿ])\1{2,}", text.lower()):
            add(0.15, "Allongement emphatique d'une lettre (ex. « braaavo »)")

        score = min(1.0, score)
        return {"detected": score >= 0.4, "score": round(score, 2), "signals": signals}

    # ── sous-entendus ──────────────────────────────────────────────────────
    def detect_subtext(self, text: str, raw_sentences: List[str]) -> List[Dict[str, str]]:
        found: List[Dict[str, str]] = []
        seen = set()
        for sent in raw_sentences:
            ns = norm(sent)
            for pattern, label, meaning in SUBTEXT_RULES:
                m = re.search(pattern, ns)
                if m and (label, sent) not in seen:
                    seen.add((label, sent))
                    found.append({
                        "type": label, "meaning": meaning,
                        "trigger": m.group(0).strip(),
                        "sentence": sent if len(sent) <= 90 else sent[:87] + "…",
                    })
        # Réponse sèche ponctuée : « Ok. »
        toks = TOKEN_RE.findall(norm(text))
        if (len(toks) <= 2 and text.strip().endswith(".")
                and re.fullmatch(r"(ok|k|kk|d'accord|oui|bien|parfait|super|cool|merci|ouais|mouais)[.\s]*",
                                 norm(text).strip())):
            found.append({
                "type": "Réponse sèche", "trigger": text.strip(),
                "meaning": "Brièveté + point final : peut traduire froideur, agacement ou désintérêt",
                "sentence": text.strip(),
            })
        return found

    # ── ton ────────────────────────────────────────────────────────────────
    @staticmethod
    def analyze_tone(text: str) -> Dict[str, Any]:
        n = norm(text)
        toks = TOKEN_RE.findall(n)
        formal = sum(t in FORMAL for t in toks)
        informal = sum(t in INFORMAL for t in toks)
        polite = sum(t in POLITE for t in toks) + len(re.findall(r"s'il (vous|te) plait", n))
        urgent = len(URGENT_RE.findall(n))
        letters = [c for c in text if c.isalpha()]
        caps_ratio = (sum(c.isupper() for c in letters) / len(letters)) if letters else 0
        if formal > informal:
            register = "formel"
        elif informal > formal:
            register = "familier"
        else:
            register = "neutre"
        return {
            "register": register,
            "politeness": "marquée" if polite >= 2 else "présente" if polite == 1 else "absente",
            "urgency": "forte" if urgent >= 2 else "présente" if urgent == 1 else "faible",
            "questions": text.count("?"),
            "exclamations": text.count("!"),
            "caps_ratio": round(caps_ratio, 2),
        }

    # ── analyse complète ───────────────────────────────────────────────────
    def analyze(self, text: str) -> Dict[str, Any]:
        if not text or not text.strip():
            return {"error": "Texte vide"}
        text = text.strip()

        raw_sentences = [s.strip() for s in SENT_SPLIT_RE.split(text) if s.strip()] or [text]
        sents = [self.score_sentence(s) for s in raw_sentences]

        # Agrégation pondérée (phrases neutres pèsent moins)
        weights = [0.3 if s["hits"] == 0 else 1 + min(s["hits"], 3) for s in sents]
        lex_score = sum(s["score"] * w for s, w in zip(sents, weights)) / sum(weights)
        pos_mass = sum(abs(v) for s in sents for _, v in s["pos"])
        neg_mass = sum(abs(v) for s in sents for _, v in s["neg"])
        hits = sum(s["hits"] for s in sents)
        n_tokens = max(1, sum(s["tokens"] for s in sents))

        mixed = (pos_mass >= 2 and neg_mass >= 2
                 and min(pos_mass, neg_mass) / max(pos_mass, neg_mass) >= 0.45
                 and abs(lex_score) < 0.5)

        emotions = self.detect_emotions(text)
        sarcasm = self.detect_sarcasm(text, sents)
        subtext = self.detect_subtext(text, raw_sentences)
        tone = self.analyze_tone(text)

        # ── fusion éventuelle avec les modèles ML ──
        ml_result = None
        final_score = lex_score
        if self.ml is not None:
            ml_result = self.ml.analyze(text)
            if ml_result:
                final_score = 0.35 * lex_score + 0.65 * ml_result["sentiment"]
                sarcasm["ml_irony"] = ml_result["irony"]
                sarcasm["score"] = round(0.5 * sarcasm["score"] + 0.5 * ml_result["irony"], 2)
                sarcasm["detected"] = sarcasm["score"] >= 0.4
                if not emotions:
                    emotions = {k: v for k, v in sorted(ml_result["emotions"].items(),
                                                        key=lambda kv: -kv[1]) if v >= 0.3}

        if mixed:
            label = "mitigé"
        elif final_score > 0.15:
            label = "positif"
        elif final_score < -0.15:
            label = "négatif"
        else:
            label = "neutre"

        coverage = hits / n_tokens
        if hits == 0 and not ml_result:
            confidence = 0.2
        else:
            confidence = min(1.0, 0.35 + 0.5 * abs(final_score) + min(0.3, coverage * 1.5))
            if mixed:
                confidence -= 0.15
            if ml_result:
                confidence = min(1.0, confidence + 0.1)
        intensity = min(1.0, (pos_mass + neg_mass) / 10
                        + 0.05 * min(tone["exclamations"], 4) + tone["caps_ratio"] * 0.3)

        top_pos = Counter(w for s in sents for w, _ in s["pos"]).most_common(6)
        top_neg = Counter(w for s in sents for w, _ in s["neg"]).most_common(6)

        result: Dict[str, Any] = {
            "text_analyzed": text if len(text) <= 200 else text[:200] + "…",
            "length": len(text),
            "word_count": len(text.split()),
            "sentence_count": len(raw_sentences),
            "sentiment": {
                "label": label, "score": round(final_score, 3),
                "lexicon_score": round(lex_score, 3),
                "confidence": round(max(0.0, confidence), 2),
                "intensity": round(intensity, 2),
                "positive_words": [w for w, _ in top_pos],
                "negative_words": [w for w, _ in top_neg],
            },
            "emotions": emotions,
            "sarcasm": sarcasm,
            "subtext": subtext,
            "tone": tone,
            "sentences": [{"text": s["text"], "score": s["score"]} for s in sents],
        }
        if self.ml is not None:
            result["ml"] = ml_result if ml_result else {"error": self.ml.error}
        result["summary"] = self._summary(result)
        return result

    # ── résumé interprété ──────────────────────────────────────────────────
    @staticmethod
    def _summary(r: Dict[str, Any]) -> List[str]:
        out: List[str] = []
        s = r["sentiment"]
        icon = {"positif": "✅", "négatif": "⚠️", "mitigé": "⚖️", "neutre": "➖"}[s["label"]]
        out.append(f"{icon} Ton général {s['label']} (confiance {s['confidence']*100:.0f}%)")
        if s["confidence"] < 0.4:
            out.append("🔎 Peu d'indices : interprétation à prendre avec prudence")
        if r["emotions"]:
            top = next(iter(r["emotions"]))
            out.append(f"😊 Émotion dominante : {top}")
        sar = r["sarcasm"]
        if sar["detected"]:
            out.append("🎭 Ironie / sarcasme probable")
            if s["label"] == "positif":
                out.append("🔄 Sentiment apparent positif mais lecture probablement NÉGATIVE (ironie)")
        if r["subtext"]:
            out.append(f"💭 {len(r['subtext'])} sous-entendu(s) possible(s)")
        if r["tone"]["urgency"] != "faible":
            out.append(f"⏰ Urgence {r['tone']['urgency']}")
        return out


# ════════════════════════════════════════════════════════════════════════════
#  Affichage
# ════════════════════════════════════════════════════════════════════════════

def print_results(r: Dict[str, Any], show_sentences: bool = False) -> None:
    print("\n" + "=" * 62)
    print("📊 RÉSULTATS DE L'ANALYSE")
    print("=" * 62)
    if "error" in r:
        print(f"❌ Erreur : {r['error']}")
        return

    print(f"\n📝 Texte : « {r['text_analyzed']} »")
    print(f"📏 {r['length']} caractères · {r['word_count']} mots · {r['sentence_count']} phrase(s)")

    s = r["sentiment"]
    print("\n🎯 SENTIMENT")
    print(f"   Polarité   : {s['label'].upper()}")
    print(f"   Score      : {s['score']:+.2f}   -1 {gauge(s['score'])} +1")
    print(f"   Confiance  : {s['confidence']*100:.0f}%   ·   Intensité : {s['intensity']*100:.0f}%")
    if s["positive_words"]:
        print(f"   Positifs   : {', '.join(s['positive_words'])}")
    if s["negative_words"]:
        print(f"   Négatifs   : {', '.join(s['negative_words'])}")

    print("\n😊 ÉMOTIONS")
    if r["emotions"]:
        for emo, share in r["emotions"].items():
            print(f"   {emo.capitalize():10} {'█' * max(1, round(share * 20)):<20} {share*100:.0f}%")
    else:
        print("   Aucune émotion claire détectée")

    sar = r["sarcasm"]
    print("\n🎭 SARCASME / IRONIE")
    print(f"   Détecté : {'OUI' if sar['detected'] else 'non'}   (score {sar['score']:.2f})")
    for sig in sar["signals"]:
        print(f"   • {sig}")

    print("\n💭 SOUS-ENTENDUS & IMPLICATIONS")
    if r["subtext"]:
        for it in r["subtext"]:
            print(f"   • {it['type']} — {it['meaning']}")
            print(f"       ↳ « {it['sentence']} »")
    else:
        print("   Aucun sous-entendu détecté")

    t = r["tone"]
    print("\n🗣️  TON")
    print(f"   Registre {t['register']} · politesse {t['politeness']} · urgence {t['urgency']}"
          f" · {t['questions']} question(s) · {t['exclamations']} exclamation(s)")

    if "ml" in r:
        print("\n🤖 MODÈLES TRANSFORMERS")
        ml = r["ml"]
        if "error" in ml:
            print(f"   ⚠️  Indisponible : {ml['error']}")
        else:
            print(f"   Sentiment : {ml['sentiment']:+.2f}   ·   Ironie : {ml['irony']*100:.0f}%")
            top_e = sorted(ml["emotions"].items(), key=lambda kv: -kv[1])[:3]
            print("   Émotions  : " + ", ".join(f"{e} {v*100:.0f}%" for e, v in top_e))
            top_s = sorted(ml["subtext"].items(), key=lambda kv: -kv[1])[:3]
            print("   Sous-texte: " + ", ".join(f"{e} {v*100:.0f}%" for e, v in top_s))

    if show_sentences and r["sentence_count"] > 1:
        print("\n📈 TRAJECTOIRE PHRASE PAR PHRASE")
        for i, se in enumerate(r["sentences"], 1):
            txt = se["text"] if len(se["text"]) <= 55 else se["text"][:52] + "…"
            print(f"   {i:>2}. {se['score']:+.2f} {gauge(se['score'], 15)}  {txt}")

    print("\n📋 RÉSUMÉ")
    for line in r["summary"]:
        print(f"   {line}")
    print("\n" + "=" * 62)


def print_batch_stats(results: List[Dict[str, Any]]) -> None:
    ok = [r for r in results if "error" not in r]
    if not ok:
        return
    labels = Counter(r["sentiment"]["label"] for r in ok)
    avg = sum(r["sentiment"]["score"] for r in ok) / len(ok)
    print("\n" + "#" * 62)
    print(f"📦 BILAN DU LOT : {len(ok)} texte(s)")
    for lab, c in labels.most_common():
        print(f"   {lab:8} {'█' * c} {c} ({c/len(ok)*100:.0f}%)")
    print(f"   Score moyen : {avg:+.2f}   -1 {gauge(avg)} +1")
    print(f"   Ironie probable : {sum(r['sarcasm']['detected'] for r in ok)}"
          f" · Avec sous-entendus : {sum(bool(r['subtext']) for r in ok)}")
    print("#" * 62)


# ════════════════════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Analyse de sentiments, émotions, sarcasme et sous-entendus (français)")
    ap.add_argument("text", nargs="*", help="texte à analyser")
    ap.add_argument("-f", "--file", help="fichier texte à analyser")
    ap.add_argument("--batch", action="store_true", help="une analyse par ligne")
    ap.add_argument("--sentences", action="store_true", help="détail par phrase")
    ap.add_argument("--ml", action="store_true", help="active les modèles transformers")
    ap.add_argument("--json", action="store_true", help="sortie JSON")
    args = ap.parse_args()

    if args.file:
        try:
            with open(args.file, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as e:
            sys.exit(f"❌ Impossible de lire {args.file} : {e}")
    elif args.text:
        text = " ".join(args.text)
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        print("Entrez le texte à analyser (Ctrl+D pour terminer) :", file=sys.stderr)
        text = sys.stdin.read()

    if not text.strip():
        sys.exit('❌ Aucun texte fourni\nUsage : python analyse_sentiment.py "Votre texte"')

    analyzer = SentimentAnalyzer(use_ml=args.ml)
    if args.ml and analyzer.ml and not analyzer.ml.available:
        print(f"⚠️  Mode ML indisponible ({analyzer.ml.error}) — mode règles uniquement.",
              file=sys.stderr)

    texts = [l for l in text.splitlines() if l.strip()] if args.batch else [text]
    results = [analyzer.analyze(t) for t in texts]

    if args.json:
        payload: Any = results if args.batch else results[0]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    for r in results:
        print_results(r, show_sentences=args.sentences)
    if args.batch:
        print_batch_stats(results)


if __name__ == "__main__":
    main()