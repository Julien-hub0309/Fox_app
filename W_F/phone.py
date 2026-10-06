import phonenumbers
from phonenumbers import geocoder, carrier
from core.base import JustradamusModule
from utile.display import console

class PhonyNode(JustradamusModule):
    def run_scan(self):
        try:
            num = "+" + self.target.replace("+", "")
            parsed = phonenumbers.parse(num)
            
            info = {
                "Pays": geocoder.country_name_for_number(parsed, "fr"),
                "Operateur": carrier.name_for_number(parsed, "fr"),
                "Validite": phonenumbers.is_valid_number(parsed),
                "Spam_Score": "Recherche de réputation en cours..."
            }
            
            self.save_finding("Phone_Intel", info)
            self.display_results("Intelligence Téléphonique", info)
        except Exception as e:
            console.print(f"[error]Erreur Phone : {e}[/error]")