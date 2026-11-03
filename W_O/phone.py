import os
import re
import json
import html
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from zoneinfo import ZoneInfo

import phonenumbers
from phonenumbers import (
    geocoder,
    carrier,
    timezone as pn_timezone,
    number_type,
    PhoneNumberType,
    PhoneNumberFormat,
    region_code_for_number,
)

from core.base import JustradamusModule
from utile.display import console

try:
    import requests
except ImportError:
    requests = None

try:
    from rich.table import Table
    from rich.panel import Panel
except ImportError:
    Table = None
    Panel = None


NUMBER_TYPE_LABELS = {
    PhoneNumberType.MOBILE: "Mobile",
    PhoneNumberType.FIXED_LINE: "Fixe",
    PhoneNumberType.FIXED_LINE_OR_MOBILE: "Fixe ou mobile",
    PhoneNumberType.TOLL_FREE: "Numéro vert / gratuit",
    PhoneNumberType.PREMIUM_RATE: "Numéro surtaxé",
    PhoneNumberType.SHARED_COST: "Coût partagé",
    PhoneNumberType.VOIP: "VoIP",
    PhoneNumberType.PERSONAL_NUMBER: "Numéro personnel",
    PhoneNumberType.PAGER: "Pager",
    PhoneNumberType.UAN: "UAN",
    PhoneNumberType.VOICEMAIL: "Messagerie vocale",
    PhoneNumberType.UNKNOWN: "Inconnu",
}

SOCIAL_TARGETS = ["instagram", "facebook", "linkedin", "twitter", "whatsapp", "telegram"]


class PhonyNode(JustradamusModule):

    TIMEOUT = float(os.getenv("PHONE_HTTP_TIMEOUT", "8"))
    MAX_WORKERS = 6
    DEFAULT_REGION = os.getenv("PHONE_DEFAULT_REGION", "FR")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = None
        if requests:
            self.session = requests.Session()
            self.session.headers.update({
                "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                               "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"),
                "Accept-Language": "fr,en;q=0.8",
            })

    # ------------------------------------------------------------------ #
    #  Point d'entrée
    # ------------------------------------------------------------------ #
    def run_scan(self):
        raw = (getattr(self, "target", "") or "").strip()
        if not raw:
            console.print("[error]Aucun numéro fourni.[/error]")
            return

        parsed = self._parse(raw)
        if parsed is None:
            console.print(f"[error]Numéro illisible ou invalide : {raw}[/error]")
            return

        intel = self._offline_intel(parsed, raw)
        intel["score_confiance"] = self._confidence(intel)

        if self.session:
            console.print("[info]▸ Collecte locale terminée, enrichissement en ligne…[/info]")
            intel["en_ligne"] = self._online_enrichment(intel)
        else:
            intel["en_ligne"] = {"info": "module 'requests' absent — enrichissement en ligne désactivé"}

        intel["meta"] = {
            "scanne_le": datetime.utcnow().isoformat() + "Z",
            "source_brute": raw,
        }

        self.save_finding("Phone_Intel", intel)
        self._render(intel, parsed)
        self._export(intel, parsed)

    # ------------------------------------------------------------------ #
    #  Parsing tolérant
    # ------------------------------------------------------------------ #
    def _parse(self, raw):
        base = raw.strip()
        digits = re.sub(r"[^\d+]", "", base)
        candidates = [base, digits]
        if not base.startswith("+"):
            candidates += ["+" + digits, "+" + base]
        for cand in candidates:
            for region in (None, self.DEFAULT_REGION):
                try:
                    parsed = phonenumbers.parse(cand, region)
                    if parsed and parsed.country_code:
                        return parsed
                except phonenumbers.NumberParseException:
                    continue
        return None

    # ------------------------------------------------------------------ #
    #  Collecte hors-ligne (libphonenumber)
    # ------------------------------------------------------------------ #
    def _offline_intel(self, parsed, raw):
        region = region_code_for_number(parsed)
        ntype = number_type(parsed)
        tz = list(pn_timezone.time_zones_for_number(parsed))

        def geo(lang):
            try:
                return geocoder.description_for_number(parsed, lang)
            except Exception:
                return ""

        intel = {
            "numéro_brut": raw,
            "valide": phonenumbers.is_valid_number(parsed),
            "possible": phonenumbers.is_possible_number(parsed),
            "e164": phonenumbers.format_number(parsed, PhoneNumberFormat.E164),
            "international": phonenumbers.format_number(parsed, PhoneNumberFormat.INTERNATIONAL),
            "national": phonenumbers.format_number(parsed, PhoneNumberFormat.NATIONAL),
            "rfc3966": phonenumbers.format_number(parsed, PhoneNumberFormat.RFC3966),
            "indicatif_pays": f"+{parsed.country_code}",
            "code_pays_iso": region,
            "pays": geocoder.country_name_for_number(parsed, "fr"),
            "pays_en": geocoder.country_name_for_number(parsed, "en"),
            "région": geo("fr"),
            "région_en": geo("en"),
            "opérateur": carrier.name_for_number(parsed, "fr") or carrier.name_for_number(parsed, "en"),
            "type_ligne": NUMBER_TYPE_LABELS.get(ntype, "Inconnu"),
            "type_code": int(ntype),
            "fuseaux_horaires": tz or [],
            "extension": parsed.extension,
            "longueur_nationale": len(str(parsed.national_number)),
            "est_mobile": ntype in (PhoneNumberType.MOBILE, PhoneNumberType.FIXED_LINE_OR_MOBILE),
            "est_voip": ntype == PhoneNumberType.VOIP,
            "sms_possible": ntype in (PhoneNumberType.MOBILE, PhoneNumberType.FIXED_LINE_OR_MOBILE),
            "formats_possibles": list(dict.fromkeys(filter(None, [
                phonenumbers.format_number(parsed, PhoneNumberFormat.E164),
                phonenumbers.format_number(parsed, PhoneNumberFormat.INTERNATIONAL),
                phonenumbers.format_number(parsed, PhoneNumberFormat.NATIONAL),
                phonenumbers.format_number(parsed, PhoneNumberFormat.RFC3966),
                str(parsed.national_number),
            ]))),
        }

        if tz:
            try:
                intel["heure_locale_estimee"] = datetime.now(ZoneInfo(tz[0])).strftime("%Y-%m-%d %H:%M:%S %Z")
            except Exception:
                intel["heure_locale_estimee"] = None

        # Liens d'action directs
        e164 = intel["e164"]
        intel["liens"] = {
            "appel": f"tel:{e164}",
            "whatsapp": f"https://wa.me/{e164.lstrip('+')}",
            "telegram": f"https://t.me/{e164}",
            "viber": f"viber://chat?number={e164}",
            "skype": f"skype:{e164}?call",
        }
        return intel

    @staticmethod
    def _confidence(intel):
        """Score heuristique 0-100 de fiabilité des métadonnées."""
        score = 0
        if intel.get("valide"):
            score += 40
        if intel.get("opérateur"):
            score += 20
        if intel.get("région"):
            score += 15
        if intel.get("fuseaux_horaires"):
            score += 10
        if not intel.get("est_voip"):
            score += 10
        if intel.get("type_ligne") not in ("Inconnu", None):
            score += 5
        return min(score, 100)

    # ------------------------------------------------------------------ #
    #  Enrichissement en ligne (concurrent)
    # ------------------------------------------------------------------ #
    def _online_enrichment(self, intel):
        e164 = intel["e164"]
        tasks = {
            "réputation_web": lambda: self._web_reputation(intel),
            "réseaux_sociaux": lambda: self._social_presence(e164),
            "validation_api": lambda: self._api_validation(e164),
        }
        out = {}
        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as pool:
            futures = {pool.submit(fn): name for name, fn in tasks.items()}
            for fut in as_completed(futures):
                name = futures[fut]
                try:
                    out[name] = fut.result()
                except Exception as e:
                    out[name] = {"erreur": str(e)}
        return out

    def _web_reputation(self, intel):
        mentions = {k: 0 for k in SOCIAL_TARGETS + ["site_web"]}
        resultats = {}
        for variant in dict.fromkeys([intel["e164"], intel.get("international"), intel.get("national")]):
            if not variant:
                continue
            hits = self._ddg(f'"{variant}"')
            resultats[variant] = hits
            for h in hits:
                blob = f'{h.get("titre", "")} {h.get("extrait", "")}'.lower()
                for key in mentions:
                    if key in blob:
                        mentions[key] += 1
        total = sum(len(v) for v in resultats.values())
        return {
            "occurrences_totales": total,
            "mentions": mentions,
            "resultats": resultats,
            "verdict": ("numéro très présent en ligne" if total > 15
                        else "présence modérée" if total > 4
                        else "peu ou pas référencé"),
        }

    def _social_presence(self, e164):
        found = {}
        for site in SOCIAL_TARGETS:
            hits = self._ddg(f'"{e164}" site:{site}.com', limit=3)
            if hits:
                found[site] = hits
        return found or {"info": "aucun profil social détecté"}

    def _api_validation(self, e164):
        out = {}
        key = os.getenv("NUMVERIFY_KEY") or os.getenv("APILAYER_KEY")
        if key:
            try:
                r = self.session.get(
                    "http://apilayer.net/api/validate",
                    params={"access_key": key, "number": e164, "format": 1},
                    timeout=self.TIMEOUT,
                )
                out["numverify"] = r.json()
            except Exception as e:
                out["numverify"] = {"erreur": str(e)}

        akey = os.getenv("ABSTRACTAPI_KEY")
        if akey:
            try:
                r = self.session.get(
                    "https://phonevalidation.abstractapi.com/v1/",
                    params={"api_key": akey, "phone": e164},
                    timeout=self.TIMEOUT,
                )
                out["abstractapi"] = r.json()
            except Exception as e:
                out["abstractapi"] = {"erreur": str(e)}

        return out or {"info": "aucune clé d'API configurée"}

    def _ddg(self, query, limit=8):
        if not self.session:
            return []
        try:
            r = self.session.get("https://html.duckduckgo.com/html/", params={"q": query}, timeout=self.TIMEOUT)
            r.raise_for_status()
        except Exception:
            return []

        page = r.text
        titres = [self._clean(html.unescape(re.sub("<[^>]+>", "", m))) for m in
                  re.findall(r'result__a"[^>]*>(.*?)</a>', page, re.S)]
        extraits = [self._clean(html.unescape(re.sub("<[^>]+>", "", m))) for m in
                    re.findall(r'result__snippet"[^>]*>(.*?)</a>', page, re.S)]

        out = []
        for i, t in enumerate(titres[:limit]):
            if not t:
                continue
            out.append({"titre": t, "extrait": extraits[i] if i < len(extraits) else ""})
        return out

    @staticmethod
    def _clean(text):
        return re.sub(r"\s+", " ", text or "").strip()

    # ------------------------------------------------------------------ #
    #  Affichage
    # ------------------------------------------------------------------ #
    def _render(self, intel, parsed):
        if not Table:
            self.display_results("Intelligence Téléphonique", intel)
            return

        console.print()
        console.print(Panel.fit(
            f"[bold cyan]{intel['e164']}[/bold cyan]  ·  {intel.get('pays') or '?'}"
            f"  ·  {intel.get('opérateur') or 'opérateur inconnu'}",
            title="📡 Phone Intel", border_style="cyan",
        ))

        table = Table(show_header=False, box=None, pad_edge=False)
        table.add_column("Champ", style="bold green", no_wrap=True)
        table.add_column("Valeur", style="white")

        for label, key in [
            ("Pays", "pays"), ("Région", "région"), ("Opérateur", "opérateur"),
            ("Type de ligne", "type_ligne"), ("Fuseaux", "fuseaux_horaires"),
            ("Heure locale", "heure_locale_estimee"), ("Valide", "valide"),
            ("E.164", "e164"), ("International", "international"),
            ("National", "national"), ("RFC3966", "rfc3966"),
            ("Confiance", "score_confiance"),
        ]:
            val = intel.get(key)
            if isinstance(val, list):
                val = ", ".join(val) or "—"
            if val in (None, ""):
                val = "—"
            table.add_row(label, str(val))

        console.print(table)

        en_ligne = intel.get("en_ligne", {})
        rep = en_ligne.get("réputation_web")
        if rep:
            console.print(f"\n[bold]Réputation web :[/bold] {rep.get('verdict')} "
                          f"({rep.get('occurrences_totales', 0)} occurrences)")
            mentions = {k: v for k, v in rep.get("mentions", {}).items() if v}
            if mentions:
                console.print("  Mentions : " + ", ".join(f"{k}={v}" for k, v in mentions.items()))

        sociaux = en_ligne.get("réseaux_sociaux")
        if sociaux and "info" not in sociaux:
            console.print("[bold]Réseaux sociaux détectés :[/bold] " + ", ".join(sociaux.keys()))

    # ------------------------------------------------------------------ #
    #  Export JSON + vCard
    # ------------------------------------------------------------------ #
    def _export(self, intel, parsed):
        outdir = os.getenv("PHONE_OUTPUT_DIR", "./phone_intel")
        os.makedirs(outdir, exist_ok=True)
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        slug = re.sub(r"\D", "", intel["e164"]) or "phone"

        with open(os.path.join(outdir, f"{slug}_{stamp}.json"), "w", encoding="utf-8") as f:
            json.dump(intel, f, ensure_ascii=False, indent=2)

        vcard = (
            "BEGIN:VCARD\nVERSION:3.0\n"
            f"N:;{intel.get('pays') or ''};;;;\n"
            f"FN:{intel.get('opérateur') or intel['e164']}\n"
            f"TEL;TYPE=CELL,VOICE:{intel['e164']}\n"
            f"ORG:{intel.get('opérateur') or ''}\n"
            f"ADR:;;;{intel.get('région') or ''};{intel.get('pays') or ''};;\n"
            "END:VCARD\n"
        )
        with open(os.path.join(outdir, f"{slug}_{stamp}.vcf"), "w", encoding="utf-8") as f:
            f.write(vcard)

        console.print(f"\n[info]↳ Export : {outdir}/{slug}_{stamp}.json + .vcf[/info]")