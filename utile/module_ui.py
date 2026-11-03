from __future__ import annotations

import importlib
import math
import os
from pathlib import Path

from utile.panel import Action, Field, ModuleResult, ModuleSpec, Row


# ───────────────────────── utilitaires ─────────────────────────
def _load(name: str):
    """Importe un module en essayant plusieurs dossiers (adapte si besoin)."""
    last = None
    for pkg in ("modules", "core", "utile", ""):
        full = f"{pkg}.{name}" if pkg else name
        try:
            return importlib.import_module(full)
        except ModuleNotFoundError as e:
            if e.name not in (full, pkg, name):      # vraie dépendance manquante
                raise
            last = e
    raise ImportError(f"Module « {name} » introuvable") from last


def _proxy(value: str):
    value = (value or "").strip()
    return {"http": value, "https": value} if value else None


def run_module(mod, method: str = "run_scan") -> dict:
    """Lance mod.<method>() et récupère le dict passé à save_finding()."""
    captured: dict = {}
    orig = mod.save_finding

    def save(category, data):
        captured["category"], captured["data"] = category, data
        try:
            return orig(category, data)
        except Exception:                            # écriture disque impossible
            return ""
    mod.save_finding = save
    getattr(mod, method)()
    return captured.get("data", {})


def _level_pct(p: float, low=45, high=60) -> str:
    return "good" if p < low else "warn" if p < high else "bad"


def dict_rows(d: dict, level: str = "info") -> list[Row]:
    rows = []
    for k, v in d.items():
        if isinstance(v, (list, tuple)):
            v = ", ".join(map(str, v))
        elif isinstance(v, dict):
            v = ", ".join(f"{a}={b}" for a, b in v.items())
        rows.append(Row(str(k), None, str(v), level))
    return rows


def human_duration(log10_seconds: float) -> str:
    if log10_seconds < 0:
        return "instantané"
    units = [("s", 1), ("min", 60), ("h", 3600), ("jours", 86400),
             ("ans", 31_557_600), ("milliers d'ans", 3.15576e10),
             ("millions d'ans", 3.15576e13), ("milliards d'ans", 3.15576e16)]
    for name, size in reversed(units):
        if log10_seconds >= math.log10(size):
            v = 10 ** (log10_seconds - math.log10(size))
            return f"{v:,.0f} {name}" if v < 1e6 else f"10^{log10_seconds - math.log10(size):.0f} {name}"
    return "instantané"


# ───────────────────────── résultat OSINT générique ─────────────────────────
def osint_result(data: dict, noun: str = "trouvés") -> ModuleResult:
    found = data.get("found", [])
    nf, er = data.get("not_found", []), data.get("errors", [])
    total = len(found) + len(nf) + len(er)
    pct = 100 * len(found) / total if total else 0
    rows = []
    for item in found:
        if isinstance(item, dict):
            rows.append(Row(item.get("site", "?"), 100, item.get("url", ""), "good"))
        else:
            site, _, info = str(item).partition(": ")
            rows.append(Row(site, 100, info, "good"))
    return ModuleResult(
        main=str(len(found)), suffix=f"/ {total}", percent=pct,
        caption=f"{len(found)} résultat(s) positif(s) sur {total} sources testées",
        level="good" if found else "muted",
        cards=[("Trouvés", str(len(found))), ("Non trouvés", str(len(nf))),
               ("Erreurs", str(len(er)))],
        detail_title="Détail par source", rows=rows, data=data)


# ═════════════════════════ DÉTECTEUR / HUMANISER / REFORMATER ═════════════════════════
HUMAN_MODES = ["subtil", "fort", "extreme", "furtif", "etudiant", "pro", "academique",
               "journaliste", "technique", "scientifique", "juridique", "medical",
               "marketing", "historique", "philo", "educatif"]


def _read_any(path: Path) -> str:
    det = _load("detecteur")
    ext = path.suffix.lower()
    if ext == ".pdf":
        return det._read_pdf(path)
    if ext == ".docx":
        return det._read_docx(path)
    return det._read_txt(path)


def _detect(inp, log):
    r = _load("detecteur").analyze_text(inp["text"])
    d = r.to_dict()
    rows = [Row(x.name, x.score * 100, "", _level_pct(x.score * 100)) for x in r.dimensions]
    for w in r.warnings:
        log(f"[!] {w}")
    return ModuleResult(
        main=f"{r.score:.1f}", suffix="/100", percent=r.score, caption=r.verdict,
        level=_level_pct(r.score),
        cards=[("Verdict", r.verdict), ("Tokens", str(r.token_count)),
               ("Confiance", r.confidence)],
        detail_title="Détail par dimension", rows=rows, data=d)


def _humanize(inp, log):
    ad = _load("anti_detecteur").MetadataCleaner()
    out = ad._human_targeted(inp["text"], inp["human_mode"])
    return ModuleResult(silent=True, set_fields={"text": out},
                        log=[f"[Humanisé · {inp['human_mode']}] {len(out)} caractères"])


def _reformat(inp, log):
    out = _load("refile").reformat_text(inp["text"], inp["style"])
    return ModuleResult(silent=True, set_fields={"text": out},
                        log=[f"[Reformaté · {inp['style']}]"])


def spec_detecteur() -> ModuleSpec:
    try:
        styles = [(lbl, key) for key, lbl in _load("refile").available_styles().items()]
    except Exception:
        styles = [("Pavé (bloc unique)", "pave")]
    return ModuleSpec(
        key="detecteur", title="Détecteur / Humaniser / Reformater", icon="🧠",
        fields=[Field("text", "Texte à analyser", "text")],
        actions=[
            Action("analyse", "Analyser", _detect),
            Action("humanize", "Humaniser", _humanize, section="Humanisation",
                   fields=[Field("human_mode", "", "select",
                                 options=[(m, m) for m in HUMAN_MODES], value="subtil")]),
            Action("reformat", "Reformater", _reformat, section="Reformatage",
                   fields=[Field("style", "", "select", options=styles,
                                 value=styles[0][1])]),
        ],
        export_name="analyse_ai.json", idle_main="—", idle_suffix="/100",
        detail_title="Détail par dimension", open_mode="text",
        open_exts=(".txt", ".md", ".pdf", ".docx"), file_reader=_read_any,
        card_titles=("Verdict", "Tokens", "Confiance"))


# ═════════════════════════ ANALYSE DE SENTIMENT ═════════════════════════
def _pct(v) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, v * 100 if v <= 1 else v))


def _sentiment(inp, log):
    r = _load("analyse_sentiment").SentimentAnalyzer(use_ml=False).analyze(inp["text"])
    if "error" in r:
        return ModuleResult(error=r["error"])
    s = r["sentiment"]
    lvl = {"positif": "good", "négatif": "bad", "mitigé": "warn"}.get(s["label"], "info")
    rows = [Row("Score lexical", (s["score"] + 1) * 50, f"{s['score']:+.2f}", lvl),
            Row("Confiance", s["confidence"] * 100, "", "info"),
            Row("Intensité", s["intensity"] * 100, "", "info"),
            Row("Sarcasme / ironie", _pct(r["sarcasm"].get("score", 0)), "",
                "warn" if r["sarcasm"].get("detected") else "good")]
    for name, v in (r.get("emotions") or {}).items():
        rows.append(Row(f"Émotion · {name}", _pct(v), "", "info"))
    for line in r.get("summary", []):
        log(line)
    return ModuleResult(
        main=f"{s['score']:+.2f}", suffix="(−1 → +1)", percent=(s["score"] + 1) * 50,
        caption=f"Ton {s['label']}", level=lvl,
        cards=[("Ton", s["label"]), ("Mots", str(r["word_count"])),
               ("Confiance", f"{s['confidence']*100:.0f}%")],
        detail_title="Détail par indicateur", rows=rows, data=r)


def spec_sentiment() -> ModuleSpec:
    return ModuleSpec(
        key="sentiment", title="Analyse de sentiment", icon="🎭",
        fields=[Field("text", "Texte à analyser", "text")],
        actions=[Action("analyse", "Analyser", _sentiment)],
        export_name="analyse_sentiment.json", idle_suffix="(−1 → +1)",
        detail_title="Détail par indicateur", open_mode="text",
        open_exts=(".txt", ".md"), card_titles=("Ton", "Mots", "Confiance"))


# ═════════════════════════ OSINT : pseudo / email / web / téléphone ═════════════════════════
def _pseudo(inp, log):
    mod = _load("pseudo").UsernameOSINT(inp["target"], _proxy(inp.get("proxy")))
    return osint_result(run_module(mod))


def _mail(inp, log):
    mod = _load("mail").EmailOSINT(inp["target"], _proxy(inp.get("proxy")))
    return osint_result(run_module(mod))


def _web(inp, log):
    mod = _load("web").WebScanner(inp["target"])
    data = run_module(mod, "scan_infra")
    if not data:
        return ModuleResult(error="Aucun résultat (domaine non résolu ?)")
    ports = data.get("Ports_Ouverts", "—")
    return ModuleResult(
        main=str(data.get("IP", "—")), caption=f"Infrastructure de {inp['target']}",
        level="info",
        cards=[("IP", str(data.get("IP", "—"))),
               ("Localisation", str(data.get("Localisation", "—"))),
               ("Ports ouverts", str(ports))],
        detail_title="Détail infrastructure", rows=dict_rows(data), data=data)


def _phone(inp, log):
    mod = _load("phone").PhonyNode(inp["target"])
    data = run_module(mod)
    if not data:
        return ModuleResult(error="Numéro illisible (format +33612345678)")
    ok = bool(data.get("Validite"))
    return ModuleResult(
        main="Valide" if ok else "Invalide", percent=100 if ok else 0,
        caption=inp["target"], level="good" if ok else "bad",
        cards=[("Pays", str(data.get("Pays") or "—")),
               ("Opérateur", str(data.get("Operateur") or "—")),
               ("Validité", "oui" if ok else "non")],
        detail_title="Détail téléphone", rows=dict_rows(data), data=data)


def _target_spec(key, title, icon, label, placeholder, fn, export, proxy=False,
                 cards=("Résultat", "Info", "Statut"), detail="Détail", suffix=""):
    fields = [Field("target", label, placeholder=placeholder)]
    if proxy:
        fields.append(Field("proxy", "Proxy (optionnel)", placeholder="http://127.0.0.1:8080"))
    return ModuleSpec(key=key, title=title, icon=icon, fields=fields,
                      actions=[Action("analyse", "Analyser", fn)],
                      export_name=export, idle_suffix=suffix,
                      detail_title=detail, card_titles=cards)


def spec_pseudo():
    return _target_spec("pseudo", "Pseudo / Username", "👤", "Pseudo cible", "ex: jean_dupont",
                        _pseudo, "pseudo_intel.json", proxy=True,
                        cards=("Trouvés", "Non trouvés", "Erreurs"),
                        detail="Détail par source", suffix="/ 0")


def spec_mail():
    return _target_spec("mail", "Email", "📧", "Adresse email", "ex: nom@domaine.fr",
                        _mail, "email_intel.json", proxy=True,
                        cards=("Trouvés", "Non trouvés", "Erreurs"),
                        detail="Détail par source", suffix="/ 0")


def spec_web():
    return _target_spec("web", "Web / IP", "🌐", "Domaine ou hôte", "ex: exemple.fr",
                        _web, "web_infra.json", cards=("IP", "Localisation", "Ports ouverts"),
                        detail="Détail infrastructure")


def spec_phone():
    return _target_spec("phone", "Téléphone", "📱", "Numéro (format international)",
                        "ex: +33612345678", _phone, "phone_intel.json",
                        cards=("Pays", "Opérateur", "Validité"), detail="Détail téléphone")


# ═════════════════════════ MOT DE PASSE ═════════════════════════
def _password(inp, log):
    pw = _load("password").PasswordAnalyzer()
    mdp = inp["password"]
    if not mdp:
        return ModuleResult(error="Saisis un mot de passe à tester")
    e = pw.evaluer(mdp)["entropie"]
    pool = {"Minuscules": any(c.islower() for c in mdp),
            "Majuscules": any(c.isupper() for c in mdp),
            "Chiffres": any(c.isdigit() for c in mdp),
            "Caractères spéciaux": any(not c.isalnum() for c in mdp)}
    size = (26 if pool["Minuscules"] else 0) + (26 if pool["Majuscules"] else 0) \
        + (10 if pool["Chiffres"] else 0) + (32 if pool["Caractères spéciaux"] else 0)
    log10_s = len(mdp) * math.log10(size) - 10 if size else -1     # 10^10 essais/s
    verdict, lvl = (("Insuffisant", "bad") if e < 60 else
                    ("Correct", "warn") if e < 80 else ("Robuste", "good"))
    rows = [Row(k, 100 if v else 0, "présent" if v else "absent",
                "good" if v else "bad") for k, v in pool.items()]
    rows.append(Row("Longueur", min(100, len(mdp) / 16 * 100), f"{len(mdp)} car.",
                    "good" if len(mdp) >= 12 else "warn"))
    if e < 60:
        log("Suggestion : utilise « Générer » pour obtenir un mot de passe robuste.")
    return ModuleResult(
        main=f"{e:.0f}", suffix="bits d'entropie", percent=min(100, e / 100 * 100),
        caption=verdict, level=lvl,
        cards=[("Verdict", verdict), ("Longueur", str(len(mdp))),
               ("Temps de craquage", human_duration(log10_s))],
        detail_title="Composition", rows=rows,
        data={"entropie_bits": round(e, 2), "longueur": len(mdp), "verdict": verdict,
              "classes": pool})        # le mot de passe n'est jamais exporté


def _gen(inp, log):
    mdp = _load("password").PasswordAnalyzer().generer_robuste(int(inp["pw_len"]))
    return ModuleResult(silent=True, set_fields={"password": mdp},
                        log=[f"[Généré] {mdp}"])


def spec_password():
    return ModuleSpec(
        key="password", title="Testeur de mot de passe", icon="🔑",
        fields=[Field("password", "Mot de passe à tester", password=True)],
        actions=[Action("analyse", "Analyser", _password),
                 Action("gen", "Générer", _gen, section="Générateur",
                        fields=[Field("pw_len", "", "select",
                                      options=[(f"{n} caractères", str(n)) for n in (12, 16, 20, 32)],
                                      value="16")])],
        export_name="password_analyse.json", idle_suffix="bits d'entropie",
        detail_title="Composition", card_titles=("Verdict", "Longueur", "Temps de craquage"))


# ═════════════════════════ VÉRIFIER UNE URL (VirusTotal) ═════════════════════════
def _url(inp, log):
    stats = _load("danger").URLAnalyzer(inp["url"].strip()).scan()
    total = sum(stats.values()) or 1
    mal, sus = stats.get("malicious", 0), stats.get("suspicious", 0)
    verdict, lvl = (("DANGEREUX", "bad") if mal else
                    ("SUSPECT", "warn") if sus else ("LÉGITIME", "good"))
    rows = [Row("Sain", stats.get("harmless", 0) / total * 100, str(stats.get("harmless", 0)), "good"),
            Row("Suspect", sus / total * 100, str(sus), "warn"),
            Row("Malveillant", mal / total * 100, str(mal), "bad"),
            Row("Non détecté", stats.get("undetected", 0) / total * 100,
                str(stats.get("undetected", 0)), "info")]
    return ModuleResult(
        main=str(mal), suffix=f"/ {total} moteurs", percent=mal / total * 100,
        caption=f"Verdict : {verdict}", level=lvl,
        cards=[("Sain", str(stats.get("harmless", 0))), ("Suspect", str(sus)),
               ("Malveillant", str(mal))],
        detail_title="Détail par catégorie", rows=rows,
        data={"url": inp["url"], "stats": stats, "verdict": verdict})


def spec_url():
    return _target_spec("url", "Vérifier une URL", "🛡️", "URL à analyser",
                        "https://exemple.com", _url, "url_virustotal.json",
                        cards=("Sain", "Suspect", "Malveillant"),
                        detail="Détail par catégorie", suffix="/ moteurs")


# ═════════════════════════ MÉTADONNÉES ═════════════════════════
def _meta(inp, log):
    p = Path(inp["path"].strip())
    if not p.exists():
        return ModuleResult(error=f"Fichier introuvable : {p}")
    ok = _load("anti_detecteur").MetadataCleaner().clean_file_metadata(p)
    return ModuleResult(
        main="OK" if ok else "Échec", level="good" if ok else "bad",
        caption=str(p), percent=100 if ok else 0,
        cards=[("Fichier", p.name), ("Type", p.suffix or "—"),
               ("Statut", "nettoyé" if ok else "échec")],
        rows=[Row("Métadonnées nettoyées", 100 if ok else 0, "", "good" if ok else "bad")],
        data={"fichier": str(p), "nettoye": ok})


def spec_meta():
    s = _target_spec("meta", "Métadonnées", "📂", "Fichier à nettoyer", "chemin du fichier",
                     _meta, "metadonnees.json", cards=("Fichier", "Type", "Statut"),
                     detail="Détail nettoyage")
    s.actions[0].label = "Nettoyer"
    s.open_mode = "path"
    return s


# ═════════════════════════ VÉHICULE ═════════════════════════
VIN_FIELDS = {"Make": "Marque", "Model": "Modèle", "ModelYear": "Année",
              "VehicleType": "Type", "BodyClass": "Carrosserie",
              "EngineCylinders": "Cylindres", "EngineSize": "Cylindrée (L)",
              "FuelTypePrimary": "Carburant", "TransmissionStyle": "Transmission",
              "DriveType": "Traction", "HorsePower": "Puissance (ch)",
              "CurbWeight": "Poids (kg)", "PlantCountry": "Pays fabrication"}


def _vehicle(inp, log):
    p = _load("plaque").PlaqueOSINT()
    q = inp["target"].strip()
    if p.verifier_vin(q.upper()):
        raw = p.decode_vin_nhtsa(q.upper())
        if not raw:
            return ModuleResult(error="VIN non décodé (API NHTSA indisponible ?)")
        data = {lbl: raw[k] for k, lbl in VIN_FIELDS.items()
                if raw.get(k) and str(raw[k]).strip().lower() not in ("not applicable", "n/a", "null")}
        head = f"{data.get('Marque', '?')} {data.get('Modèle', '')}".strip()
        return ModuleResult(
            main=head, caption=f"VIN {q.upper()}", level="info",
            cards=[("Année", str(data.get("Année", "—"))),
                   ("Carburant", str(data.get("Carburant", "—"))),
                   ("Puissance", str(data.get("Puissance (ch)", "—")))],
            detail_title="Fiche VIN (NHTSA)", rows=dict_rows(data), data=data)
    parts = q.split(None, 1)
    r = p.rechercher_vehicule_local(parts[0], parts[1] if len(parts) > 1 else None) if parts else None
    if not r:
        return ModuleResult(error="Entre un VIN (17 car.) ou « marque modèle » connu")
    d = r.get("data", {})
    flat = {"Marque": r.get("marque"), "Modèle": r.get("modele") or "(tous)",
            **({"Modèles": r["modeles"]} if "modeles" in r else {})}
    if "carburant" in d:
        flat.update({"Carburants": d["carburant"], "Puissances (ch)": d["puissances"],
                     "Types": d["types"]})
    return ModuleResult(
        main=f"{flat['Marque']} {flat['Modèle']}".strip(), caption="Base locale",
        cards=[("Carburants", ", ".join(d.get("carburant", [])) or "—"),
               ("Types", ", ".join(d.get("types", [])) or "—"),
               ("Source", "locale")],
        detail_title="Fiche véhicule", rows=dict_rows(flat), data=flat)


def spec_vehicle():
    return _target_spec("vehicle", "Véhicule (plaque / VIN)", "🚗", "VIN ou marque + modèle",
                        "ex: VF1… ou renault clio", _vehicle, "vehicule.json",
                        cards=("Année", "Carburant", "Puissance"), detail="Fiche véhicule")


# ═════════════════════════ PROFILAGE ═════════════════════════
def _profile(inp, log):
    P = _load("profileur").Profileur(inp["nom"], inp["prenom"], inp["age"])
    P.console = None
    if not P.nom or not P.prenom:
        return ModuleResult(error="Nom et prénom requis")
    P.executer_recherche_complete()
    res = P.resultats
    rows = ([Row("Email probable", None, e, "info") for e in res["emails_probables"][:40]]
            + [Row("Username probable", None, u, "info") for u in res["usernames_probables"][:40]])
    nets = res["reseaux_sociaux"]
    rows += [Row(f"Réseau · {k}", None, v if isinstance(v, str) else f"{len(v)} URL", "info")
             for k, v in nets.items()]
    return ModuleResult(
        main=f"{P.prenom} {P.nom}", caption="Pistes générées (à vérifier manuellement)",
        cards=[("Emails", str(len(res["emails_probables"]))),
               ("Usernames", str(len(res["usernames_probables"]))),
               ("Réseaux", str(len(nets)))],
        detail_title="Pistes", rows=rows, data={**res, "google_dorks": P.rechercher_google_dorks(),
                                              "annuaires": P.rechercher_annuaires()})


def spec_profile():
    return ModuleSpec(
        key="profile", title="Profilage (Nom/Prénom)", icon="🕵️",
        fields=[Field("nom", "Nom"), Field("prenom", "Prénom"),
                Field("age", "Âge (optionnel)")],
        actions=[Action("analyse", "Analyser", _profile)],
        export_name="profil.json", detail_title="Pistes",
        card_titles=("Emails", "Usernames", "Réseaux"))


# ═════════════════════════ VÉRIFICATEUR D'INFORMATIONS ═════════════════════════
def _verify(inp, log):
    idee = _load("idee")
    eng = idee.TorSearchEngine()
    urls = eng.search_on_surface_web(inp["query"], 10)
    if not urls:
        return ModuleResult(error="Aucune page trouvée")
    exact, partial = eng.search_content_in_pages(inp["query"], urls, 5)
    summ = eng.summarize_credibility(exact)
    lvl = {"crédible": "good", "suspect": "bad"}.get(summ["verdict"], "warn")
    score = {"crédible": 100, "mitigé": 50, "suspect": 10}
    rows = [Row(m.get("url", "?")[:40], score.get(m.get("credibility"), 50),
                f"{m.get('credibility', '?')} · {m.get('source_reliability', '')}",
                {"crédible": "good", "suspect": "bad"}.get(m.get("credibility"), "warn"))
            for m in exact + partial]
    return ModuleResult(
        main=summ["verdict"].upper(), caption=f"{len(exact)} correspondance(s) exacte(s)",
        level=lvl,
        cards=[("Exactes", str(len(exact))), ("Partielles", str(len(partial))),
               ("Crédibles / suspectes", f"{summ['credible']} / {summ['suspect']}")],
        detail_title="Sources analysées", rows=rows,
        data={"query": inp["query"], "summary": summ, "exact": exact, "partial": partial})


def spec_verify():
    return _target_spec("verify", "Vérificateur d'informations", "📰", "Affirmation à vérifier",
                        "ex: phrase ou fait à recouper", _verify, "verification.json",
                        cards=("Exactes", "Partielles", "Crédibles / suspectes"),
                        detail="Sources analysées")


# ═════════════════════════ REGISTRE ═════════════════════════
def _flipper():
    from utile.studio_panels import FlipperPanel
    return FlipperPanel


def _esp32():
    from utile.studio_panels import ESP32Panel
    return ESP32Panel


# (clé, titre menu, icône, fabrique) ; fabrique renvoie ModuleSpec OU une classe Widget
SECTIONS: list[tuple[str, list[tuple[str, str, str, callable]]]] = [
    ("W_I · Texte IA", [
        ("detecteur", "Détecteur / Humaniser / Reformater", "🧠", spec_detecteur),
        ("sentiment", "Analyse de sentiment", "🎭", spec_sentiment)]),
    ("W_J · Vérification", [
        ("verify", "Vérificateur d'informations", "📰", spec_verify)]),
    ("W_F · Flipper & ESP32", [
        ("flipper", "Flipper Studio (JS / CLI)", "🐬", _flipper),
        ("esp32", "ESP32 Studio (C/C++ / Flash)", "📶", _esp32)]),
    ("W_O / W_S · OSINT & Réseau", [
        ("phone", "Téléphone", "📱", spec_phone),
        ("web", "Web / IP", "🌐", spec_web),
        ("mail", "Email", "📧", spec_mail),
        ("pseudo", "Pseudo / Username", "👤", spec_pseudo),
        ("password", "Testeur de mot de passe", "🔑", spec_password),
        ("profile", "Profilage (Nom/Prénom)", "🕵️", spec_profile),
        ("url", "Vérifier une URL", "🛡️", spec_url),
        ("meta", "Métadonnées", "📂", spec_meta),
        ("vehicle", "Véhicule (plaque / VIN)", "🚗", spec_vehicle)]),
]


def build_widget(key: str):
    """Renvoie le widget (ModulePanel ou Studio) pour une clé de module."""
    from utile.panel import ModulePanel
    for _, items in SECTIONS:
        for k, _t, _i, factory in items:
            if k == key:
                out = factory()
                return ModulePanel(out) if isinstance(out, ModuleSpec) else out()
    raise KeyError(key)