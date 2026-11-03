from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ExifTags
from PIL.ExifTags import TAGS
from scipy import fftpack

# ----------------------------------------------------------------------------
# Constantes
# ----------------------------------------------------------------------------

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}

AI_SOFTWARE_HINTS = [
    "midjourney", "stable diffusion", "stablediffusion", "dall-e", "dalle",
    "dall·e", "firefly", "adobe firefly", "nightcafe", "leonardo.ai",
    "leonardo ai", "runwayml", "runway ml", "ideogram", "flux.1", "flux ",
    "comfyui", "automatic1111", "a1111", "invokeai", "novelai", "playground ai",
    "bing image creator", "craiyon", "dreamstudio", "civitai", "sdxl",
    "diffusers", "generative", "gan", "text-to-image", "ai-generated",
    "google imagen", "imagen", "grok imagine",
]

CAMERA_EXIF_KEYS = {
    "Make", "Model", "LensModel", "FocalLength", "ExposureTime",
    "FNumber", "ISOSpeedRatings", "ShutterSpeedValue", "ApertureValue",
    "DateTimeOriginal", "GPSInfo",
}

# Résolutions "rondes" très fréquemment produites en sortie brute par les
# générateurs d'images courants (SD 1.5 / SDXL / DALL-E / Midjourney...).
RESOLUTIONS_IA_CONNUES = {
    (512, 512), (576, 576), (640, 640), (704, 704), (768, 768), (832, 832),
    (896, 896), (960, 960), (1024, 1024), (1152, 1152), (1216, 1216),
    (1280, 1280), (1536, 1536),
    (512, 768), (768, 512), (576, 1024), (1024, 576), (768, 1344), (1344, 768),
    (832, 1216), (1216, 832), (896, 1152), (1152, 896), (1024, 1792),
    (1792, 1024), (1024, 1536), (1536, 1024), (1080, 1920), (1920, 1080),
}

# Distribution théorique de la loi de Benford pour le premier chiffre (1-9).
BENFORD_THEORIQUE = np.array([np.log10(1 + 1 / d) for d in range(1, 10)])

# Marqueurs standard IPTC/C2PA signalant une origine algorithmique (générative
# ou composite avec de la génération). Référence : vocabulaire IPTC
# "digitalsourcetype" utilisé par Content Credentials (Adobe, OpenAI, Google,
# Microsoft, Leica, Meta...). Présence quasi certaine d'IA si trouvé.
DIGITAL_SOURCE_TYPE_IA = [
    "trainedalgorithmicmedia",
    "compositewithtrainedalgorithmicmedia",
    "algorithmicmedia",
]

# Table de correspondance "mot-clé trouvé dans les métadonnées" -> nom
# canonique de modèle/outil, pour la fonction d'identification.
MODELE_PAR_MOTCLE: dict[str, str] = {
    "midjourney": "Midjourney",
    "dall-e": "DALL-E (OpenAI)",
    "dalle": "DALL-E (OpenAI)",
    "dall·e": "DALL-E (OpenAI)",
    "openai": "DALL-E (OpenAI)",
    "stable diffusion": "Stable Diffusion",
    "stablediffusion": "Stable Diffusion",
    "sdxl": "Stable Diffusion XL",
    "flux.1": "Flux.1 (Black Forest Labs)",
    "flux ": "Flux.1 (Black Forest Labs)",
    "firefly": "Adobe Firefly",
    "adobe firefly": "Adobe Firefly",
    "nightcafe": "NightCafe",
    "leonardo.ai": "Leonardo.Ai",
    "leonardo ai": "Leonardo.Ai",
    "runwayml": "Runway ML",
    "runway ml": "Runway ML",
    "ideogram": "Ideogram",
    "comfyui": "Stable Diffusion (ComfyUI)",
    "automatic1111": "Stable Diffusion (Automatic1111)",
    "a1111": "Stable Diffusion (Automatic1111)",
    "invokeai": "Stable Diffusion (InvokeAI)",
    "novelai": "NovelAI",
    "playground ai": "Playground AI",
    "bing image creator": "Bing Image Creator / DALL-E",
    "microsoft designer": "Microsoft Designer / DALL-E",
    "craiyon": "Craiyon",
    "dreamstudio": "Stable Diffusion (DreamStudio)",
    "civitai": "Stable Diffusion (modèle Civitai)",
    "google imagen": "Google Imagen",
    "imagen": "Google Imagen",
    "grok imagine": "Grok Imagine (xAI)",
}

# Motifs de noms de fichiers associés à des conventions connues de certaines
# plateformes (indice faible : "probable", jamais "confirmé").
MOTIFS_NOM_FICHIER: list[tuple[str, str]] = [
    (r"^dall[·\-]?e[_ ]?\d{4}-\d{2}-\d{2}", "DALL-E (OpenAI, export ChatGPT)"),
    (r"^midjourney", "Midjourney"),
    (r"_mj[_\-]", "Midjourney"),
    (r"^designer[_ ]?[-–]", "Microsoft Designer / DALL-E"),
    (r"firefly", "Adobe Firefly"),
    (r"leonardo", "Leonardo.Ai"),
]


@dataclass
class Indice:
    """Un indice individuel avec son score et son explication."""
    nom: str
    score: float
    poids: float
    details: str
    applicable: bool = True


@dataclass
class IdentificationModele:
    """Résultat de la tentative d'identification du générateur utilisé."""
    modele: str | None          # nom canonique, ou None si inconnu
    confiance: str              # "confirmé" | "probable" | "spéculatif" | "inconnu"
    methode: str                # comment le résultat a été obtenu
    details: str                # explication lisible
    candidats: list[str] = field(default_factory=list)  # autres hypothèses

    def to_dict(self) -> dict[str, Any]:
        return {
            "modele": self.modele,
            "confiance": self.confiance,
            "methode": self.methode,
            "details": self.details,
            "candidats": self.candidats,
        }


@dataclass
class ResultatAnalyse:
    fichier: str
    score_global: float
    verdict: str
    confiance: str
    indices: list[Indice] = field(default_factory=list)
    erreurs: list[str] = field(default_factory=list)
    identification: IdentificationModele | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fichier": self.fichier,
            "score_global": round(self.score_global, 3),
            "verdict": self.verdict,
            "confiance": self.confiance,
            "indices": [
                {
                    "nom": i.nom,
                    "score": round(i.score, 3),
                    "poids": i.poids,
                    "applicable": i.applicable,
                    "details": i.details,
                }
                for i in self.indices
            ],
            "identification_modele": self.identification.to_dict() if self.identification else None,
            "erreurs": self.erreurs,
        }


# ----------------------------------------------------------------------------
# 1. Métadonnées
# ----------------------------------------------------------------------------

def _lire_exif(img: Image.Image) -> dict[str, Any]:
    exif_data: dict[str, Any] = {}
    try:
        raw = img.getexif()
        if raw:
            for tag_id, value in raw.items():
                tag = TAGS.get(tag_id, tag_id)
                exif_data[tag] = value
    except Exception:
        pass
    return exif_data


def _lire_texte_png(img: Image.Image) -> str:
    texte = []
    info = getattr(img, "text", {}) or {}
    for cle, valeur in info.items():
        texte.append(f"{cle}: {valeur}")
    for cle, valeur in (img.info or {}).items():
        if isinstance(valeur, (str, bytes)):
            texte.append(f"{cle}: {valeur}")
    return "\n".join(str(t) for t in texte)


def _lire_octets_bruts(chemin: Path, limite: int = 8_000_000) -> bytes:
    """Lit le fichier en brut (jusqu'à `limite` octets) pour y chercher des
    marqueurs de provenance (XMP, C2PA) que PIL n'expose pas toujours."""
    try:
        with open(chemin, "rb") as f:
            return f.read(limite)
    except Exception:
        return b""


def _extraire_xmp(raw: bytes) -> str:
    """Extrait le paquet XMP embarqué (texte XML) s'il existe, sans dépendre
    d'une bibliothèque XMP dédiée."""
    try:
        debut = raw.find(b"<x:xmpmeta")
        fin = raw.find(b"</x:xmpmeta>")
        if debut != -1 and fin != -1:
            return raw[debut: fin + len(b"</x:xmpmeta>")].decode("utf-8", errors="ignore")
    except Exception:
        pass
    return ""


def _detecter_c2pa(raw: bytes) -> tuple[bool, str]:
    """Recherche best-effort de marqueurs de provenance C2PA/Content
    Credentials dans les octets bruts. Ne décode pas la structure binaire
    JUMBF/CBOR complète (hors-scope ici) : cherche les chaînes ASCII/UTF-8
    lisibles qui y apparaissent presque toujours en clair."""
    blob_lower = raw.lower()
    trouve = False
    extraits: list[str] = []

    for marqueur in DIGITAL_SOURCE_TYPE_IA:
        if marqueur.encode() in blob_lower:
            trouve = True
            extraits.append(marqueur)

    if b"c2pa" in blob_lower or b"contentcredentials" in blob_lower or b"content credentials" in blob_lower:
        trouve = True

    # Tentative d'extraction d'un éventuel champ "claim_generator" ou
    # "softwareAgent" lisible en clair dans le blob binaire.
    import re as _re
    for motif in (rb'"claim_generator"\s*:\s*"([^"]{1,120})"',
                  rb'softwareAgent["\s:=]+["\']?([A-Za-z0-9 ._/\-]{1,80})'):
        m = _re.search(motif, raw)
        if m:
            try:
                extraits.append(m.group(1).decode("utf-8", errors="ignore"))
            except Exception:
                pass

    return trouve, "; ".join(dict.fromkeys(extraits))  # dédoublonne en gardant l'ordre


def analyser_provenance_c2pa(chemin: Path) -> Indice:
    """Indice à part, séparé des métadonnées EXIF classiques : recherche de
    manifestes de provenance standardisés (C2PA / Content Credentials)."""
    try:
        raw = _lire_octets_bruts(chemin)
        if not raw:
            return Indice("provenance_c2pa", 0.5, 0.0, "Fichier illisible pour cette analyse.", applicable=False)

        trouve, extraits = _detecter_c2pa(raw)
        if trouve:
            details = (
                "Marqueur(s) standard de provenance C2PA/Content Credentials "
                "détecté(s) dans le fichier, signalant une origine "
                "algorithmique (génération ou composition assistée par IA)."
            )
            if extraits:
                details += f" Éléments extraits : {extraits}."
            return Indice("provenance_c2pa", 0.95, 3.0, details)

        return Indice(
            "provenance_c2pa", 0.4, 0.0,
            "Aucun manifeste de provenance C2PA/Content Credentials détecté "
            "(absence non concluante : beaucoup de plateformes le retirent).",
            applicable=False,
        )
    except Exception as e:
        return Indice("provenance_c2pa", 0.5, 0.0, f"Analyse de provenance impossible : {e}", applicable=False)


def analyser_metadonnees(img: Image.Image, chemin: Path) -> Indice:
    exif = _lire_exif(img)
    texte_png = _lire_texte_png(img)
    raw = _lire_octets_bruts(chemin, limite=2_000_000)
    texte_xmp = _extraire_xmp(raw)
    blob = (
        texte_png + " " + texte_xmp + " " + " ".join(str(v) for v in exif.values())
    ).lower()

    hints_trouves = [h for h in AI_SOFTWARE_HINTS if h in blob]
    if hints_trouves:
        return Indice(
            nom="metadonnees", score=0.97, poids=3.0,
            details=("Indice(s) explicite(s) d'outil génératif trouvé(s) dans les "
                     f"métadonnées (EXIF/PNG/XMP) : {', '.join(sorted(set(hints_trouves)))}."),
        )

    a_camera_exif = any(k in exif for k in CAMERA_EXIF_KEYS)
    est_jpeg = img.format == "JPEG"

    if est_jpeg and not a_camera_exif and not exif and not texte_xmp:
        return Indice(
            nom="metadonnees", score=0.55, poids=1.0,
            details=("Fichier JPEG sans aucune métadonnée EXIF/XMP (ni appareil, ni "
                     "date de prise de vue). Compatible avec une image générée ou "
                     "avec une image réelle dont l'EXIF a été supprimé par un "
                     "réseau social ou un outil d'édition."),
        )

    if a_camera_exif:
        return Indice(
            nom="metadonnees", score=0.08, poids=1.5,
            details=("Métadonnées d'appareil photo présentes (marque/modèle/"
                     "paramètres de prise de vue), plutôt typiques d'une photo "
                     "réelle non générée."),
        )

    return Indice(nom="metadonnees", score=0.4, poids=0.5,
                  details="Métadonnées présentes mais non concluantes.")


# ----------------------------------------------------------------------------
# 2. Analyse fréquentielle (FFT)
# ----------------------------------------------------------------------------

def analyser_spectre_fft(img_gray: np.ndarray) -> Indice:
    try:
        h, w = img_gray.shape
        taille = 512
        if h > taille or w > taille:
            from PIL import Image as PILImage
            tmp = PILImage.fromarray(img_gray).resize((taille, taille))
            img_gray = np.array(tmp)

        f = fftpack.fft2(img_gray.astype(np.float64))
        fshift = fftpack.fftshift(f)
        magnitude = np.log1p(np.abs(fshift))

        cy, cx = magnitude.shape[0] // 2, magnitude.shape[1] // 2
        rayon_interne = int(min(cy, cx) * 0.35)
        rayon_externe = int(min(cy, cx) * 0.9)

        yy, xx = np.ogrid[: magnitude.shape[0], : magnitude.shape[1]]
        dist = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
        anneau_externe = (dist >= rayon_interne) & (dist <= rayon_externe)

        valeurs_anneau = magnitude[anneau_externe]
        if valeurs_anneau.size == 0:
            return Indice("fft_spectre", 0.5, 0.0, "Image trop petite pour l'analyse FFT.", applicable=False)

        moyenne = float(np.mean(valeurs_anneau))
        ecart_type = float(np.std(valeurs_anneau))

        seuil_pic = moyenne + 3 * ecart_type
        nb_pics = int(np.sum(valeurs_anneau > seuil_pic))
        ratio_pics = nb_pics / valeurs_anneau.size

        if ratio_pics > 0.02:
            score = min(0.5 + ratio_pics * 10, 0.9)
            details = (f"Spectre de Fourier présentant des pics périodiques marqués "
                       f"(ratio {ratio_pics:.4f}), compatible avec des artefacts "
                       f"d'upsampling/génération.")
        elif ratio_pics > 0.005:
            score = 0.5
            details = (f"Spectre de Fourier légèrement irrégulier (ratio {ratio_pics:.4f}), "
                       "non concluant à lui seul.")
        else:
            score = 0.2
            details = ("Spectre de Fourier relativement lisse, sans motif périodique "
                       "marqué (plutôt typique d'une photo naturelle).")

        return Indice("fft_spectre", score, 1.5, details)
    except Exception as e:
        return Indice("fft_spectre", 0.5, 0.0, f"Analyse FFT impossible : {e}", applicable=False)


# ----------------------------------------------------------------------------
# 3. Error Level Analysis (ELA)
# ----------------------------------------------------------------------------

def analyser_ela(chemin: Path, img: Image.Image) -> Indice:
    if img.format != "JPEG":
        return Indice("ela", 0.5, 0.0,
                      "ELA non applicable (l'image n'est pas un JPEG d'origine).",
                      applicable=False)
    try:
        import io
        rgb = img.convert("RGB")
        buffer = io.BytesIO()
        rgb.save(buffer, "JPEG", quality=90)
        buffer.seek(0)
        recompressee = Image.open(buffer)

        diff = np.abs(np.array(rgb).astype(np.int16) - np.array(recompressee).astype(np.int16))
        diff_moyenne_par_zone = diff.mean(axis=2)

        h, w = diff_moyenne_par_zone.shape
        taille_bloc = max(16, min(h, w) // 32)
        if taille_bloc == 0:
            return Indice("ela", 0.5, 0.0, "Image trop petite pour l'ELA.", applicable=False)

        moyennes_blocs = []
        for y in range(0, h - taille_bloc, taille_bloc):
            for x in range(0, w - taille_bloc, taille_bloc):
                bloc = diff_moyenne_par_zone[y:y + taille_bloc, x:x + taille_bloc]
                moyennes_blocs.append(float(bloc.mean()))

        if not moyennes_blocs:
            return Indice("ela", 0.5, 0.0, "Pas assez de blocs pour l'ELA.", applicable=False)

        moyennes_blocs = np.array(moyennes_blocs)
        coefficient_variation = float(np.std(moyennes_blocs) / (np.mean(moyennes_blocs) + 1e-6))

        if coefficient_variation > 1.2:
            score = 0.7
            details = (f"Forte hétérogénéité des niveaux d'erreur de compression entre "
                       f"zones de l'image (coef. variation {coefficient_variation:.2f}), "
                       "pouvant indiquer un montage ou une retouche localisée.")
        elif coefficient_variation > 0.7:
            score = 0.5
            details = f"Hétérogénéité modérée (coef. variation {coefficient_variation:.2f})."
        else:
            score = 0.3
            details = (f"Niveaux d'erreur de compression homogènes sur l'image "
                       f"(coef. variation {coefficient_variation:.2f}).")

        return Indice("ela", score, 1.0, details)
    except Exception as e:
        return Indice("ela", 0.5, 0.0, f"ELA impossible : {e}", applicable=False)


# ----------------------------------------------------------------------------
# 4. Bruit haute fréquence
# ----------------------------------------------------------------------------

def analyser_bruit(img_gray: np.ndarray) -> Indice:
    try:
        from scipy.ndimage import uniform_filter
        img_f = img_gray.astype(np.float64)
        lisse = uniform_filter(img_f, size=3)
        bruit = img_f - lisse
        ecart_type_bruit = float(np.std(bruit))

        if ecart_type_bruit < 1.5:
            score = 0.7
            details = (f"Bruit résiduel très faible (écart-type {ecart_type_bruit:.2f}), "
                       "texture inhabituellement lisse pour un capteur photo réel.")
        elif ecart_type_bruit < 3.0:
            score = 0.5
            details = f"Bruit résiduel modéré (écart-type {ecart_type_bruit:.2f})."
        else:
            score = 0.25
            details = (f"Bruit résiduel marqué (écart-type {ecart_type_bruit:.2f}), "
                       "plutôt cohérent avec un capteur photo réel.")

        return Indice("bruit_capteur", score, 1.0, details)
    except Exception as e:
        return Indice("bruit_capteur", 0.5, 0.0, f"Analyse du bruit impossible : {e}", applicable=False)


# ----------------------------------------------------------------------------
# 5. Statistiques colorimétriques
# ----------------------------------------------------------------------------

def analyser_couleurs(img_rgb: np.ndarray) -> Indice:
    try:
        r = img_rgb[:, :, 0].astype(np.float64)
        g = img_rgb[:, :, 1].astype(np.float64)
        b = img_rgb[:, :, 2].astype(np.float64)

        maxc = np.maximum(np.maximum(r, g), b)
        minc = np.minimum(np.minimum(r, g), b)
        saturation = np.where(maxc > 0, (maxc - minc) / (maxc + 1e-6), 0)

        sat_moyenne = float(np.mean(saturation))
        sat_ecart_type = float(np.std(saturation))

        if sat_moyenne > 0.45 and sat_ecart_type < 0.18:
            score = 0.6
            details = (f"Saturation globale élevée et homogène (moyenne {sat_moyenne:.2f}, "
                       f"écart-type {sat_ecart_type:.2f}) : esthétique parfois associée "
                       "aux images générées, mais aussi à des photos retouchées.")
        else:
            score = 0.4
            details = (f"Distribution de saturation sans signal particulier "
                       f"(moyenne {sat_moyenne:.2f}, écart-type {sat_ecart_type:.2f}).")

        return Indice("couleurs", score, 0.5, details)
    except Exception as e:
        return Indice("couleurs", 0.5, 0.0, f"Analyse colorimétrique impossible : {e}", applicable=False)


# ----------------------------------------------------------------------------
# 6. Résolution typique des générateurs
# ----------------------------------------------------------------------------

def analyser_resolution(img: Image.Image) -> Indice:
    w, h = img.size

    if (w, h) in RESOLUTIONS_IA_CONNUES:
        return Indice(
            "resolution", 0.65, 0.7,
            f"Dimensions {w}×{h} correspondant exactement à une résolution de "
            "sortie typique des générateurs d'images (SD/SDXL/DALL-E/"
            "Midjourney). Indice faible pris isolément (une photo peut avoir "
            "été recadrée/redimensionnée à cette taille).",
        )

    multiple_64 = (w % 64 == 0) and (h % 64 == 0)
    if multiple_64 and max(w, h) <= 2048:
        return Indice(
            "resolution", 0.5, 0.3,
            f"Dimensions {w}×{h} toutes deux multiples de 64, compatible avec "
            "une sortie de générateur par diffusion (mais aussi avec un "
            "redimensionnement standard).",
        )

    return Indice(
        "resolution", 0.3, 0.3,
        f"Dimensions {w}×{h} ne correspondant pas à une résolution de "
        "générateur typique.",
    )


# ----------------------------------------------------------------------------
# Utilitaire commun : extraction de blocs DCT 8×8
# ----------------------------------------------------------------------------

def _extraire_coefficients_dct(img_gray: np.ndarray, taille_max: int = 1024) -> np.ndarray | None:
    """Découpe l'image en blocs 8x8 et renvoie leurs coefficients DCT-II
    (orthonormés), empilés selon forme (n_blocs, 8, 8)."""
    h, w = img_gray.shape
    if max(h, w) > taille_max:
        ratio = taille_max / max(h, w)
        nouvelle_taille = (max(8, int(w * ratio)), max(8, int(h * ratio)))
        img_gray = np.array(Image.fromarray(img_gray).resize(nouvelle_taille))
        h, w = img_gray.shape

    h8, w8 = (h // 8) * 8, (w // 8) * 8
    if h8 < 8 or w8 < 8:
        return None
    img_gray = img_gray[:h8, :w8].astype(np.float64)

    blocs = (
        img_gray.reshape(h8 // 8, 8, w8 // 8, 8)
        .swapaxes(1, 2)
        .reshape(-1, 8, 8)
    )
    return fftpack.dctn(blocs, type=2, norm="ortho", axes=(1, 2))


# ----------------------------------------------------------------------------
# 7. Loi de Benford sur les coefficients DCT
# ----------------------------------------------------------------------------

def analyser_benford_dct(img_gray: np.ndarray) -> Indice:
    try:
        dct_blocs = _extraire_coefficients_dct(img_gray)
        if dct_blocs is None or dct_blocs.shape[0] < 50:
            return Indice("benford_dct", 0.5, 0.0, "Image trop petite pour l'analyse DCT.", applicable=False)

        ac = dct_blocs.copy()
        ac[:, 0, 0] = 0
        valeurs = np.abs(ac.flatten())
        valeurs = valeurs[valeurs >= 1.0]

        if valeurs.size < 500:
            return Indice("benford_dct", 0.5, 0.0, "Pas assez de coefficients AC significatifs.", applicable=False)

        premiers_chiffres = np.floor(valeurs / 10 ** np.floor(np.log10(valeurs))).astype(int)
        premiers_chiffres = np.clip(premiers_chiffres, 1, 9)

        distribution = np.array([
            np.sum(premiers_chiffres == d) for d in range(1, 10)
        ], dtype=np.float64)
        distribution /= distribution.sum()

        ecart_moyen = float(np.mean(np.abs(distribution - BENFORD_THEORIQUE)))

        if ecart_moyen > 0.045:
            score = 0.65
            details = (
                f"Distribution du premier chiffre des coefficients DCT "
                f"nettement éloignée de la loi de Benford (écart moyen "
                f"{ecart_moyen:.3f}), signal de contenu haute-fréquence non "
                "naturel."
            )
        elif ecart_moyen > 0.025:
            score = 0.5
            details = f"Écart modéré à la loi de Benford (écart moyen {ecart_moyen:.3f})."
        else:
            score = 0.3
            details = (
                f"Distribution proche de la loi de Benford (écart moyen "
                f"{ecart_moyen:.3f}), plutôt typique d'un contenu naturel."
            )

        return Indice("benford_dct", score, 1.2, details)
    except Exception as e:
        return Indice("benford_dct", 0.5, 0.0, f"Analyse de Benford impossible : {e}", applicable=False)


# ----------------------------------------------------------------------------
# 8. Périodicité de double compression JPEG
# ----------------------------------------------------------------------------

def analyser_double_compression(img_gray: np.ndarray, est_jpeg: bool) -> Indice:
    if not est_jpeg:
        return Indice("double_compression", 0.5, 0.0, "Non applicable (l'image n'est pas un JPEG).", applicable=False)
    try:
        dct_blocs = _extraire_coefficients_dct(img_gray)
        if dct_blocs is None or dct_blocs.shape[0] < 200:
            return Indice("double_compression", 0.5, 0.0, "Image trop petite pour cette analyse.", applicable=False)

        coeff = np.round(dct_blocs[:, 1, 1]).astype(int)
        valeurs, _ = np.histogram(coeff, bins=np.arange(coeff.min(), coeff.max() + 2))
        if valeurs.size < 16:
            return Indice("double_compression", 0.5, 0.0, "Histogramme trop court pour cette analyse.", applicable=False)

        spectre = np.abs(fftpack.fft(valeurs.astype(np.float64) - valeurs.mean()))
        moitie = spectre[1: len(spectre) // 2]
        if moitie.size == 0:
            return Indice("double_compression", 0.5, 0.0, "Spectre trop court.", applicable=False)

        pic = float(np.max(moitie))
        fond = float(np.median(moitie)) + 1e-6
        ratio_pic = pic / fond

        if ratio_pic > 8:
            score = 0.6
            details = (
                f"Forte périodicité détectée dans l'histogramme des "
                f"coefficients DCT (ratio pic/fond {ratio_pic:.1f}), signe "
                "probable d'une double compression JPEG (recompression lors "
                "d'un export web, d'un pipeline de génération ou d'un montage)."
            )
        elif ratio_pic > 4:
            score = 0.5
            details = f"Périodicité modérée (ratio {ratio_pic:.1f}), non concluante seule."
        else:
            score = 0.35
            details = f"Pas de périodicité marquée (ratio {ratio_pic:.1f}), compatible avec une compression unique."

        return Indice("double_compression", score, 0.8, details)
    except Exception as e:
        return Indice("double_compression", 0.5, 0.0, f"Analyse de double compression impossible : {e}", applicable=False)


# ----------------------------------------------------------------------------
# 9. Autocorrélation / motifs en grille (artefacts d'upsampling)
# ----------------------------------------------------------------------------

def analyser_autocorrelation(img_gray: np.ndarray) -> Indice:
    try:
        taille = 512
        h, w = img_gray.shape
        if max(h, w) > taille:
            ratio = taille / max(h, w)
            img_gray = np.array(
                Image.fromarray(img_gray).resize((max(8, int(w * ratio)), max(8, int(h * ratio))))
            )

        img_f = img_gray.astype(np.float64)
        img_f -= img_f.mean()

        spectre = fftpack.fft2(img_f)
        autocorr = np.real(fftpack.ifft2(spectre * np.conj(spectre)))
        autocorr = fftpack.fftshift(autocorr)
        autocorr /= (np.max(np.abs(autocorr)) + 1e-9)

        cy, cx = autocorr.shape[0] // 2, autocorr.shape[1] // 2

        rayon_min, rayon_max = 3, 40
        yy, xx = np.ogrid[: autocorr.shape[0], : autocorr.shape[1]]
        dist = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
        zone = (dist >= rayon_min) & (dist <= rayon_max)

        valeurs_zone = autocorr[zone]
        if valeurs_zone.size == 0:
            return Indice("autocorrelation", 0.5, 0.0, "Image trop petite pour cette analyse.", applicable=False)

        pic_secondaire = float(np.max(valeurs_zone))

        if pic_secondaire > 0.35:
            score = 0.7
            details = (
                f"Pic d'autocorrélation secondaire marqué près du centre "
                f"(intensité {pic_secondaire:.2f}), compatible avec un motif "
                "périodique fin (grille d'upsampling), peu présent sur une "
                "photo naturelle."
            )
        elif pic_secondaire > 0.2:
            score = 0.5
            details = f"Autocorrélation secondaire modérée (intensité {pic_secondaire:.2f})."
        else:
            score = 0.25
            details = f"Pas de motif périodique marqué en autocorrélation (intensité {pic_secondaire:.2f})."

        return Indice("autocorrelation", score, 1.0, details)
    except Exception as e:
        return Indice("autocorrelation", 0.5, 0.0, f"Analyse d'autocorrélation impossible : {e}", applicable=False)


# ----------------------------------------------------------------------------
# 10. Entropie de micro-texture
# ----------------------------------------------------------------------------

def analyser_entropie_texture(img_gray: np.ndarray) -> Indice:
    try:
        from scipy.ndimage import laplace

        img_f = img_gray.astype(np.float64)
        reponse = laplace(img_f)

        taille_patch = 16
        h, w = reponse.shape
        variances = []
        for y in range(0, h - taille_patch, taille_patch):
            for x in range(0, w - taille_patch, taille_patch):
                patch = reponse[y:y + taille_patch, x:x + taille_patch]
                variances.append(float(np.var(patch)))

        if len(variances) < 20:
            return Indice("entropie_texture", 0.5, 0.0, "Image trop petite pour cette analyse.", applicable=False)

        variances = np.array(variances)
        hist, _ = np.histogram(variances, bins=32, density=False)
        proba = hist.astype(np.float64) / (hist.sum() + 1e-9)
        proba = proba[proba > 0]
        entropie = float(-np.sum(proba * np.log2(proba)))
        entropie_normalisee = entropie / float(np.log2(32))

        if entropie_normalisee < 0.45:
            score = 0.6
            details = (
                f"Micro-texture peu variée sur l'image (entropie normalisée "
                f"{entropie_normalisee:.2f}), compatible avec un lissage "
                "typique des décodeurs génératifs."
            )
        elif entropie_normalisee < 0.65:
            score = 0.45
            details = f"Variété de micro-texture modérée (entropie normalisée {entropie_normalisee:.2f})."
        else:
            score = 0.3
            details = (
                f"Micro-texture riche et variée (entropie normalisée "
                f"{entropie_normalisee:.2f}), plutôt typique d'une photo "
                "naturelle (grain, détails fins)."
            )

        return Indice("entropie_texture", score, 0.8, details)
    except Exception as e:
        return Indice("entropie_texture", 0.5, 0.0, f"Analyse d'entropie impossible : {e}", applicable=False)


# ----------------------------------------------------------------------------
# Identification du modèle / générateur
# ----------------------------------------------------------------------------

def _parser_params_automatic1111(texte: str) -> dict[str, str]:
    """Extrait les champs structurés d'une chaîne de paramètres au format
    Automatic1111/ComfyUI (ex: 'Steps: 20, Sampler: Euler a, ... Model: xyz')."""
    import re as _re
    champs: dict[str, str] = {}
    for cle in ("Model", "Model hash", "Sampler", "Version", "Steps", "CFG scale"):
        m = _re.search(rf"{cle}\s*:\s*([^,\n]+)", texte)
        if m:
            champs[cle] = m.group(1).strip()
    return champs


def identifier_modele_ia(img: Image.Image, chemin: Path) -> IdentificationModele:
    """Tente d'identifier le générateur probablement utilisé, avec un niveau
    de confiance explicite. Voir le docstring du module pour la méthodologie
    et ses limites (en particulier : pas d'attribution fiable "au pixel" sans
    métadonnées)."""
    exif = _lire_exif(img)
    texte_png = _lire_texte_png(img)
    raw = _lire_octets_bruts(chemin, limite=4_000_000)
    texte_xmp = _extraire_xmp(raw)
    blob = (texte_png + " " + texte_xmp + " " + " ".join(str(v) for v in exif.values()))
    blob_lower = blob.lower()

    # --- Palier 1 : paramètres structurés Automatic1111/ComfyUI (PNG) -------
    if "steps:" in blob_lower and "sampler" in blob_lower:
        champs = _parser_params_automatic1111(blob)
        if champs:
            nom_modele = champs.get("Model") or champs.get("Model hash")
            details = "Paramètres de génération embarqués détectés (" + ", ".join(
                f"{k}: {v}" for k, v in champs.items()
            ) + ")."
            return IdentificationModele(
                modele=f"Stable Diffusion — checkpoint « {nom_modele} »" if nom_modele else "Stable Diffusion (checkpoint non précisé)",
                confiance="confirmé",
                methode="paramètres de génération embarqués (PNG tEXt, format Automatic1111/ComfyUI)",
                details=details,
            )

    # --- Palier 2 : mot-clé explicite dans métadonnées fiables (EXIF/XMP/PNG)
    hints = [h for h in MODELE_PAR_MOTCLE if h in blob_lower]
    if hints:
        candidats = sorted({MODELE_PAR_MOTCLE[h] for h in hints})
        return IdentificationModele(
            modele=candidats[0],
            confiance="confirmé",
            methode="mot-clé explicite dans les métadonnées (EXIF/PNG/XMP)",
            details=f"Correspondance trouvée pour : {', '.join(hints)}.",
            candidats=candidats[1:],
        )

    # --- Palier 3 : provenance C2PA présente mais sans nom de modèle clair --
    trouve_c2pa, extraits_c2pa = _detecter_c2pa(raw)
    if trouve_c2pa:
        hints_extraits = [h for h in MODELE_PAR_MOTCLE if h in extraits_c2pa.lower()]
        if hints_extraits:
            return IdentificationModele(
                modele=MODELE_PAR_MOTCLE[hints_extraits[0]],
                confiance="confirmé",
                methode="manifeste de provenance C2PA / Content Credentials",
                details=f"Producteur extrait du manifeste : {extraits_c2pa}.",
            )
        return IdentificationModele(
            modele=None,
            confiance="probable",
            methode="manifeste de provenance C2PA / Content Credentials",
            details=(
                "Origine algorithmique confirmée par un manifeste C2PA/Content "
                "Credentials, mais le nom précis de l'outil n'a pas pu être "
                "extrait automatiquement du manifeste binaire."
                + (f" Éléments bruts : {extraits_c2pa}." if extraits_c2pa else "")
            ),
        )

    # --- Palier 4 : convention de nommage de fichier connue -----------------
    import re as _re
    nom_fichier = Path(chemin).name.lower()
    for motif, modele in MOTIFS_NOM_FICHIER:
        if _re.search(motif, nom_fichier):
            return IdentificationModele(
                modele=modele,
                confiance="probable",
                methode="convention de nommage du fichier",
                details=f"Le nom de fichier « {Path(chemin).name} » correspond au motif habituel de {modele}.",
            )

    # --- Palier 5 : aucune métadonnée exploitable, pas d'attribution fiable -
    return IdentificationModele(
        modele=None,
        confiance="inconnu",
        methode="aucune",
        details=(
            "Aucune métadonnée, manifeste de provenance ou convention de "
            "nommage exploitable. Une estimation de FAMILLE (diffusion/GAN) "
            "basée sur les seuls indices pixel peut être déduite du score "
            "global, mais n'identifie aucun produit précis de façon fiable."
        ),
    )


# ----------------------------------------------------------------------------
# Agrégation
# ----------------------------------------------------------------------------

def agreger(indices: list[Indice]) -> tuple[float, str, str]:
    applicables = [i for i in indices if i.applicable and i.poids > 0]
    if not applicables:
        return 0.5, "INDÉTERMINÉ", "très faible"

    poids_total = sum(i.poids for i in applicables)
    score = sum(i.score * i.poids for i in applicables) / poids_total

    if score >= 0.75:
        verdict = "PROBABLEMENT GÉNÉRÉE PAR IA"
    elif score >= 0.58:
        verdict = "SUSPECT — INDICES D'IA PRÉSENTS"
    elif score <= 0.3:
        verdict = "PROBABLEMENT AUTHENTIQUE"
    else:
        verdict = "NON CONCLUANT"

    scores_bruts = [i.score for i in applicables]
    desaccord = float(np.std(scores_bruts))
    nb_indices_forts = sum(1 for i in applicables if i.poids >= 1.2)

    if nb_indices_forts >= 2 and desaccord < 0.25 and poids_total >= 4:
        confiance = "haute"
    elif poids_total >= 2 and desaccord < 0.3:
        confiance = "moyenne"
    else:
        confiance = "faible"

    return score, verdict, confiance


def analyser_image(chemin: Path, rapide: bool = False) -> ResultatAnalyse:
    """Analyse une image. `rapide=True` saute les analyses les plus coûteuses
    (DCT/Benford, double compression, autocorrélation, entropie de texture) :
    utile pour traiter de gros lots, au prix d'une puissance de détection
    réduite."""
    chemin = Path(chemin)
    indices: list[Indice] = []
    erreurs: list[str] = []

    try:
        img = Image.open(chemin)
        img.load()
    except Exception as e:
        return ResultatAnalyse(
            fichier=str(chemin), score_global=0.0, verdict="ERREUR",
            confiance="aucune", erreurs=[f"Impossible d'ouvrir l'image : {e}"],
        )

    est_jpeg = img.format == "JPEG"
    img_gray = None

    try:
        indices.append(analyser_metadonnees(img, chemin))
    except Exception as e:
        erreurs.append(f"Erreur analyse métadonnées : {e}")

    try:
        indices.append(analyser_provenance_c2pa(chemin))
    except Exception as e:
        erreurs.append(f"Erreur analyse provenance C2PA : {e}")

    try:
        indices.append(analyser_resolution(img))
    except Exception as e:
        erreurs.append(f"Erreur analyse résolution : {e}")

    try:
        img_gray = np.array(img.convert("L"))
        indices.append(analyser_spectre_fft(img_gray))
        indices.append(analyser_bruit(img_gray))
    except Exception as e:
        erreurs.append(f"Erreur analyses niveaux de gris : {e}")

    try:
        indices.append(analyser_ela(chemin, img))
    except Exception as e:
        erreurs.append(f"Erreur ELA : {e}")

    try:
        img_rgb = np.array(img.convert("RGB"))
        indices.append(analyser_couleurs(img_rgb))
    except Exception as e:
        erreurs.append(f"Erreur analyse couleurs : {e}")

    if not rapide and img_gray is not None:
        try:
            indices.append(analyser_benford_dct(img_gray))
        except Exception as e:
            erreurs.append(f"Erreur Benford/DCT : {e}")

        try:
            indices.append(analyser_double_compression(img_gray, est_jpeg))
        except Exception as e:
            erreurs.append(f"Erreur double compression : {e}")

        try:
            indices.append(analyser_autocorrelation(img_gray))
        except Exception as e:
            erreurs.append(f"Erreur autocorrélation : {e}")

        try:
            indices.append(analyser_entropie_texture(img_gray))
        except Exception as e:
            erreurs.append(f"Erreur entropie de texture : {e}")

    try:
        identification = identifier_modele_ia(img, chemin)
    except Exception as e:
        identification = IdentificationModele(
            modele=None, confiance="inconnu", methode="erreur",
            details=f"Identification impossible : {e}",
        )

    score, verdict, confiance = agreger(indices)
    return ResultatAnalyse(fichier=str(chemin), score_global=score, verdict=verdict,
                           confiance=confiance, indices=indices, erreurs=erreurs,
                           identification=identification)


# ----------------------------------------------------------------------------
# API applicative (intégration dans l'application)
# ----------------------------------------------------------------------------

def analyser_images(cible: Path, recursive: bool = False, rapide: bool = False) -> list[ResultatAnalyse]:
    """Analyse un fichier unique ou un dossier. Renvoie la liste des résultats."""
    cible = Path(cible)
    if cible.is_file():
        return [analyser_image(cible, rapide=rapide)]
    motif = "**/*" if recursive else "*"
    fichiers = sorted(
        p for p in cible.glob(motif)
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    return [analyser_image(f, rapide=rapide) for f in fichiers]


def analyser(chemin) -> ResultatAnalyse:
    """Alias simple pour un usage applicatif direct."""
    return analyser_image(Path(chemin))


# ----------------------------------------------------------------------------
# Sélecteur de fichier (boîte de dialogue native)
# ----------------------------------------------------------------------------

def choisir_fichiers(multiple: bool = True) -> list[Path]:
    """Ouvre une boîte de dialogue native pour choisir une ou plusieurs images.
    Renvoie une liste vide si l'utilisateur annule ou si tkinter est absent."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        print("tkinter n'est pas disponible : impossible d'ouvrir le sélecteur de fichier. "
              "Passez le chemin en argument.", file=sys.stderr)
        return []

    racine = tk.Tk()
    racine.withdraw()
    racine.attributes("-topmost", True)  # place la boîte de dialogue au premier plan
    try:
        extensions = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTENSIONS))
        options = {
            "title": "Choisir une image à analyser",
            "filetypes": [("Images", extensions), ("Tous les fichiers", "*.*")],
        }
        if multiple:
            choix = filedialog.askopenfilenames(**options)
            return [Path(c) for c in choix]
        choix = filedialog.askopenfilename(**options)
        return [Path(choix)] if choix else []
    finally:
        racine.destroy()


def choisir_dossier() -> Path | None:
    """Ouvre une boîte de dialogue native pour choisir un dossier d'images."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        print("tkinter n'est pas disponible : impossible d'ouvrir le sélecteur de dossier. "
              "Passez le chemin en argument.", file=sys.stderr)
        return None

    racine = tk.Tk()
    racine.withdraw()
    racine.attributes("-topmost", True)
    try:
        choix = filedialog.askdirectory(title="Choisir un dossier d'images à analyser")
        return Path(choix) if choix else None
    finally:
        racine.destroy()


def run_scan(target: str | None = None, recursive: bool = False, as_json: bool = False,
             rapide: bool = False) -> list[ResultatAnalyse]:
    """Point d'entrée générique (page ModulePage / _auto) : analyse et affiche.
    Si `target` est vide ou None, ouvre le sélecteur de fichier."""
    if target:
        cibles = [Path(str(target)).expanduser()]
    else:
        cibles = choisir_fichiers()
        if not cibles:
            print("Aucun fichier sélectionné.")
            return []

    resultats: list[ResultatAnalyse] = []
    for cible in cibles:
        if not cible.exists():
            print(f"Chemin introuvable : {cible}")
            continue
        resultats.extend(analyser_images(cible, recursive, rapide=rapide))

    if not resultats:
        print("Aucune image supportée trouvée.")
        return []
    if as_json:
        print(json.dumps([r.to_dict() for r in resultats], ensure_ascii=False, indent=2))
    else:
        for r in resultats:
            afficher_resultat(r)
            print()
    return resultats


# ----------------------------------------------------------------------------
# Affichage
# ----------------------------------------------------------------------------

def afficher_resultat(resultat: ResultatAnalyse) -> None:
    print("=" * 70)
    print(f"Fichier   : {resultat.fichier}")
    print(f"Score IA  : {resultat.score_global:.2f} / 1.00")
    print(f"Verdict   : {resultat.verdict}")
    print(f"Confiance : {resultat.confiance}")
    print("-" * 70)
    for indice in resultat.indices:
        marqueur = "•" if indice.applicable else "◦ (non applicable)"
        print(f"  {marqueur} {indice.nom} — score={indice.score:.2f} (poids {indice.poids})")
        print(f"      {indice.details}")
    if resultat.identification:
        ident = resultat.identification
        print("-" * 70)
        print(f"Modèle probable : {ident.modele or 'non identifié'}")
        print(f"  Confiance   : {ident.confiance}")
        print(f"  Méthode     : {ident.methode}")
        print(f"  Détails     : {ident.details}")
        if ident.candidats:
            print(f"  Autres candidats possibles : {', '.join(ident.candidats)}")
    if resultat.erreurs:
        print("-" * 70)
        for err in resultat.erreurs:
            print(f"  ! {err}")
    print("=" * 70)
    print("Rappel : ceci est une analyse heuristique, pas une preuve formelle. "
          "Pour une vérification à enjeu (presse, modération, juridique), "
          "croisez avec la recherche de la source originale et, si possible, "
          "les métadonnées de provenance (C2PA / Content Credentials).")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Détecteur heuristique d'images potentiellement générées par IA.",
    )
    parser.add_argument("chemin", nargs="?", default=None,
                        help="Fichier image ou dossier à analyser. "
                             "Si omis, un sélecteur de fichier s'ouvre.")
    parser.add_argument("--dossier", action="store_true",
                        help="Ouvre le sélecteur pour choisir un dossier plutôt qu'un fichier.")
    parser.add_argument("--recursive", action="store_true",
                        help="Si la cible est un dossier, parcourt aussi les sous-dossiers.")
    parser.add_argument("--json", action="store_true",
                        help="Sort le résultat au format JSON plutôt qu'en texte lisible.")
    parser.add_argument("--fast", "--rapide", dest="rapide", action="store_true",
                        help=("Mode rapide : saute les analyses coûteuses (Benford/DCT, "
                              "double compression, autocorrélation, entropie de texture)."))
    args = parser.parse_args(argv)

    # Détermination des cibles : argument explicite, sinon sélecteur graphique.
    if args.chemin:
        cibles = [Path(args.chemin).expanduser()]
    elif args.dossier:
        dossier = choisir_dossier()
        cibles = [dossier] if dossier else []
    else:
        cibles = choisir_fichiers()

    if not cibles:
        print("Aucune sélection effectuée.", file=sys.stderr)
        return 1

    resultats: list[ResultatAnalyse] = []
    for cible in cibles:
        if not cible.exists():
            print(f"Erreur : chemin introuvable : {cible}", file=sys.stderr)
            continue
        resultats.extend(analyser_images(cible, args.recursive, rapide=args.rapide))

    if not resultats:
        print("Aucune image supportée trouvée.", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps([r.to_dict() for r in resultats], ensure_ascii=False, indent=2))
    else:
        for r in resultats:
            afficher_resultat(r)
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())