import requests
try:
    import stem.process
    from stem.util import term
    STEM_AVAILABLE = True
except ImportError:  # Tor reste optionnel : le web normal fonctionne sans stem
    STEM_AVAILABLE = False
    term = None
import argparse
import time
import socket
from bs4 import BeautifulSoup
import re
from urllib.parse import quote_plus, urlparse, parse_qs, unquote
import json
from datetime import datetime
import os
import sys

class InformationValidator:
    def __init__(self):
        self.trusted_sources = [
            'reuters.com', 'ap.org', 'afp.com', 'bbc.com', 'nytimes.com',
            'washingtonpost.com', 'theguardian.com', 'lemonde.fr', 'lefigaro.fr',
            'liberation.fr', 'france24.com', 'rfi.fr', 'sciencesetavenir.fr'
        ]
        self.suspicious_sources = [
            'theonion.com', 'dailycurrant.com', 'weeklyworldnews.com'
        ]
        
    def validate_source(self, url):
        """Évalue la fiabilité d'une source"""
        domain = re.sub(r'^https?://(?:www\.)?([^/]+).*', r'\1', url.lower())
        
        if any(trusted in domain for trusted in self.trusted_sources):
            return 'fiable'
        elif any(suspicious in domain for suspicious in self.suspicious_sources):
            return 'satire'
        else:
            return 'inconnu'
    
    def analyze_content_credibility(self, content, query):
        """Analyse la crédibilité du contenu par rapport à la requête"""
        # Indicateurs de fausses nouvelles
        fake_indicators = [
            r'vous ne croirez jamais',
            r'ce que les médias ne vous disent pas',
            r'la vérité cachée',
            r'révélations choquantes',
            r'le gouvernement vous ment',
            r'big pharma',
            r'complot',
            r'illuminati',
            r'chemtrails'
        ]
        
        # Indicateurs de journalisme sérieux
        credible_indicators = [
            r'selon des experts',
            r'a déclaré',
            r'a confirmé',
            r'a rapporté',
            r'lors d\'.*conférence',
            r'étude publiée',
            r'données officielles',
            r'enquête de'
        ]
        
        fake_score = 0
        credible_score = 0
        
        for indicator in fake_indicators:
            if re.search(indicator, content, re.IGNORECASE):
                fake_score += 1
                
        for indicator in credible_indicators:
            if re.search(indicator, content, re.IGNORECASE):
                credible_score += 1
        
        # Vérifier si la requête est présente dans le contenu
        query_present = query.lower() in content.lower()
        
        # Déterminer la crédibilité
        if credible_score > fake_score and query_present:
            return 'crédible'
        elif fake_score > credible_score:
            return 'suspect'
        elif query_present:
            return 'moyen'
        else:
            return 'non pertinent'
    
    def extract_author(self, soup, url):
        """Extrait le nom de l'auteur de l'article"""
        # Essayer différentes métadonnées communes pour l'auteur
        author_selectors = [
            'meta[name="author"]',
            'meta[property="article:author"]',
            'meta[name="sailthru.author"]',
            '.author',
            '.byline',
            '.by-author',
            '.post-author',
            '.article-author',
            '[rel="author"]'
        ]
        
        for selector in author_selectors:
            author_element = soup.select_one(selector)
            if author_element:
                if author_element.name == 'meta':
                    author = author_element.get('content', '')
                else:
                    author = author_element.get_text().strip()
                
                # Nettoyer le nom de l'auteur
                author = re.sub(r'^par\s+', '', author, flags=re.IGNORECASE)
                author = re.sub(r'\s+.*\$', '', author)  # Garder seulement le premier nom
                
                if author and len(author) > 2:
                    return author
        
        # Essayer de trouver l'auteur dans l'URL (ex: /author/nom-auteur)
        author_match = re.search(r'/author/([^/]+)', url, re.IGNORECASE)
        if author_match:
            return author_match.group(1).replace('-', ' ').title()
        
        return 'Inconnu'

class TorSearchEngine:
    def __init__(self):
        self.session = requests.Session()
        self.session.proxies = {}
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        self.tor_process = None
        self.socks_port = 9050
        self.control_port = 9051
        self.validator = InformationValidator()
        
    def is_tor_running(self):
        """Vérifie si un Tor écoute déjà sur le port SOCKS"""
        try:
            with socket.create_connection(('127.0.0.1', self.socks_port), timeout=2):
                return True
        except OSError:
            return False

    def check_tor_connection(self):
        """Vérifie que le trafic passe réellement par Tor (retourne l'IP de sortie ou None)"""
        try:
            proxies = {
                'http': f'socks5h://127.0.0.1:{self.socks_port}',
                'https': f'socks5h://127.0.0.1:{self.socks_port}'
            }
            r = requests.get('https://check.torproject.org/api/ip', proxies=proxies, timeout=20)
            data = r.json()
            return data.get('IP') if data.get('IsTor') else None
        except Exception:
            return None

    def stop_tor(self):
        """Arrête l'instance Tor lancée par cette application"""
        if self.tor_process:
            try:
                self.tor_process.terminate()
            except Exception:
                pass
            self.tor_process = None

    def start_tor(self, msg_handler=None):
        """Démarre une instance Tor si nécessaire"""
        if not STEM_AVAILABLE:
            print("Erreur : le module 'stem' n'est pas installé (pip install stem)")
            return False
        if msg_handler is None:
            msg_handler = print
        try:
            self.tor_process = stem.process.launch_tor_with_config(
                config={
                    'SocksPort': str(self.socks_port),
                    'ControlPort': str(self.control_port),
                    'ExitNodes': '{fr}',  # Optionnel: forcer les sorties françaises
                },
                init_msg_handler=msg_handler,
            )
            print("Tor a démarré avec succès")
            return True
        except Exception as e:
            print(f"Erreur lors du démarrage de Tor: {e}")
            return False
    
    def configure_tor_proxies(self):
        """Configure le session pour utiliser Tor"""
        self.session.proxies = {
            'http': f'socks5h://127.0.0.1:{self.socks_port}',
            'https': f'socks5h://127.0.0.1:{self.socks_port}'
        }
    
    @staticmethod
    def clean_result_url(href):
        """DuckDuckGo renvoie des liens de redirection (//duckduckgo.com/l/?uddg=...) :
        on récupère l'URL réelle pour que l'évaluation de la source et l'analyse fonctionnent"""
        if href.startswith('//'):
            href = 'https:' + href
        parsed = urlparse(href)
        if 'duckduckgo.com' in parsed.netloc and parsed.path.startswith('/l/'):
            target = parse_qs(parsed.query).get('uddg')
            if target:
                return unquote(target[0])
        return href

    def search_on_surface_web(self, query, num_results=10):
        """Recherche sur le web normal"""
        print(f"Recherche de '{query}' sur le web normal...")
        
        # DuckDuckGo est plus respectueux de la vie privée
        url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        try:
            response = self.session.get(url, headers=headers, timeout=30)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            results = []
            for result in soup.select('.result'):
                link = result.select_one('.result__a')
                if link is None or not link.get('href'):
                    continue
                title = link.text.strip()
                url = self.clean_result_url(link['href'])
                snippet = result.select_one('.result__snippet').text if result.select_one('.result__snippet') else ""
                
                # Évaluer la source
                source_reliability = self.validator.validate_source(url)
                
                results.append({
                    'title': title,
                    'url': url,
                    'snippet': snippet,
                    'source_reliability': source_reliability
                })
                
                if len(results) >= num_results:
                    break
                    
            return results
        except Exception as e:
            print(f"Erreur lors de la recherche sur le web normal: {e}")
            return []
    
    def search_on_tor(self, query, num_results=10):
        """Recherche sur les moteurs de recherche Tor"""
        print(f"Recherche de '{query}' sur le réseau Tor...")
        
        # Ahmia est un moteur de recherche pour les sites .onion
        tor_search_engines = [
            f"http://juhanurmihxlp77nkq76byazcldy5h4lrqf53ubqg4rcy2hxdn7dlr4id.onion/search?q={quote_plus(query)}",
            f"http://xmh57jrzrnw6insl.onion/cgi-bin/omega/omega?P={quote_plus(query)}"
        ]
        
        results = []
        for engine_url in tor_search_engines:
            try:
                print(f"Recherche sur: {engine_url}")
                response = self.session.get(engine_url, timeout=30)
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Parser les résultats (varie selon le moteur)
                for item in soup.select('li')[:num_results]:
                    link = item.select_one('a')
                    if link and link.get('href'):
                        title = link.text
                        url = link['href']
                        snippet = item.text.replace(title, '').strip()
                        
                        # Évaluer la source (pour Tor, on considère tout comme inconnu par défaut)
                        source_reliability = 'inconnu (Tor)'
                        
                        results.append({
                            'title': title,
                            'url': url,
                            'snippet': snippet,
                            'source_reliability': source_reliability,
                            'source': 'Tor'
                        })
                        
                        if len(results) >= num_results:
                            break
                            
                if results:
                    break
                    
            except Exception as e:
                print(f"Erreur avec {engine_url}: {e}")
                continue
                
        return results
    
    def search_content_in_pages(self, query, urls, max_pages=5, progress=None):
        """Cherche le contenu spécifique dans les pages trouvées
        progress(i, total, url) est un callback optionnel appelé avant chaque page"""
        print(f"Analyse du contenu dans {len(urls)} pages...")
        
        exact_matches = []
        partial_matches = []
        
        for i, url_data in enumerate(urls[:max_pages]):
            url = url_data['url']
            if progress:
                progress(i, min(len(urls), max_pages), url)
            print(f"Analyse de la page {i+1}/{min(len(urls), max_pages)}: {url}")
            
            try:
                response = self.session.get(url, timeout=30)
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Extraire le texte principal
                text_content = soup.get_text()
                
                # Extraire l'auteur de l'article
                author = self.validator.extract_author(soup, url)
                
                # Analyser la crédibilité du contenu
                credibility = self.validator.analyze_content_credibility(text_content, query)
                
                # Vérifier les correspondances exactes
                if query.lower() in text_content.lower():
                    # Trouver le contexte autour de la correspondance
                    query_lower = query.lower()
                    text_lower = text_content.lower()
                    match_pos = text_lower.find(query_lower)
                    
                    context_start = max(0, match_pos - 100)
                    context_end = min(len(text_content), match_pos + len(query) + 100)
                    context = text_content[context_start:context_end].replace('\n', ' ').strip()
                    
                    exact_matches.append({
                        'url': url,
                        'title': url_data.get('title', 'Sans titre'),
                        'author': author,
                        'context': context,
                        'match_type': 'exact',
                        'credibility': credibility,
                        'source_reliability': url_data.get('source_reliability', 'inconnu')
                    })
                # Vérifier les correspondances partielles (mots de la requête)
                elif any(word.lower() in text_content.lower() for word in query.split() if len(word) > 3):
                    partial_matches.append({
                        'url': url,
                        'title': url_data.get('title', 'Sans titre'),
                        'author': author,
                        'match_type': 'partial',
                        'credibility': credibility,
                        'source_reliability': url_data.get('source_reliability', 'inconnu')
                    })
                    
                # Respecter les limites de temps pour éviter de surcharger les serveurs
                time.sleep(1)
                
            except Exception as e:
                print(f"Erreur lors de l'analyse de {url}: {e}")
                continue
                
        return exact_matches, partial_matches
    
    def get_input_interactive(self):
        """Demande à l'utilisateur de saisir la phrase à rechercher"""
        print("\n" + "="*50)
        print("SYSTÈME DE RECHERCHE ET VALIDATION D'INFORMATIONS")
        print("="*50)
        
        query = input("\nEntrez la phrase ou l'idée que vous souhaitez rechercher : ").strip()
        
        if not query:
            print("Erreur : Vous devez entrer une phrase valide.")
            sys.exit(1)
            
        use_tor = input("Voulez-vous utiliser le réseau Tor pour cette recherche ? (o/n) : ").strip().lower()
        use_tor = use_tor in ('o', 'oui', 'y', 'yes')
        
        start_tor = False
        if use_tor:
            start_tor = input("Voulez-vous démarrer une nouvelle instance Tor ? (o/n) : ").strip().lower()
            start_tor = start_tor in ('o', 'oui', 'y', 'yes')
        
        analyze_content = input("Voulez-vous analyser le contenu détaillé des pages trouvées ? (o/n) : ").strip().lower()
        analyze_content = analyze_content in ('o', 'oui', 'y', 'yes')
        
        num_results = input("Combien de résultats souhaitez-vous obtenir ? (10 par défaut) : ").strip()
        try:
            num_results = int(num_results) if num_results else 10
            num_results = max(1, min(num_results, 50))  # Limiter entre 1 et 50
        except ValueError:
            num_results = 10
            
        return {
            'query': query,
            'tor': use_tor,
            'start_tor': start_tor,
            'analyze': analyze_content,
            'results': num_results
        }
    
    @staticmethod
    def summarize_credibility(exact_matches):
        """Même règle de conclusion que display_results, sous forme de données"""
        credible = sum(1 for m in exact_matches if m['credibility'] == 'crédible')
        suspect = sum(1 for m in exact_matches if m['credibility'] == 'suspect')
        if credible > suspect:
            verdict = 'crédible'
        elif suspect > credible:
            verdict = 'suspect'
        else:
            verdict = 'mitigé'
        return {'credible': credible, 'suspect': suspect, 'verdict': verdict}

    def display_results(self, search_results, exact_matches, partial_matches):
        """Affiche les résultats de manière structurée"""
        print("\n" + "="*50)
        print("RÉSULTATS DE LA RECHERCHE")
        print("="*50)
        
        # Afficher les résultats de la recherche initiale
        for i, result in enumerate(search_results, 1):
            print(f"\n{i}. {result['title']}")
            print(f"   URL: {result['url']}")
            print(f"   Fiabilité de la source: {result.get('source_reliability', 'inconnu')}")
            print(f"   Extrait: {result.get('snippet') or 'Pas d extrait disponible'}")
        
        # Afficher les résultats détaillés si disponibles
        if exact_matches or partial_matches:
            print("\n" + "="*50)
            print("ANALYSE DÉTAILLÉE DU CONTENU")
            print("="*50)
            
            # Afficher les correspondances exactes
            print(f"\nCorrespondances exactes ({len(exact_matches)}):")
            for i, match in enumerate(exact_matches, 1):
                print(f"\n{i}. {match['title']}")
                print(f"   Auteur: {match['author']}")
                print(f"   URL: {match['url']}")
                print(f"   Fiabilité de la source: {match['source_reliability']}")
                print(f"   Crédibilité du contenu: {match['credibility']}")
                print(f"   Contexte: {match['context']}")
            
            # Afficher les correspondances partielles
            print(f"\nCorrespondances partielles ({len(partial_matches)}):")
            for i, match in enumerate(partial_matches, 1):
                print(f"\n{i}. {match['title']}")
                print(f"   Auteur: {match['author']}")
                print(f"   URL: {match['url']}")
                print(f"   Fiabilité de la source: {match['source_reliability']}")
                print(f"   Crédibilité du contenu: {match['credibility']}")
            
            # Résumé de la crédibilité
            credible_count = sum(1 for match in exact_matches if match['credibility'] == 'crédible')
            suspect_count = sum(1 for match in exact_matches if match['credibility'] == 'suspect')
            
            print(f"\nRÉSUMÉ DE LA CRÉDIBILITÉ:")
            print(f"Sources crédibles: {credible_count}")
            print(f"Sources suspectes: {suspect_count}")
            
            if credible_count > suspect_count:
                print("CONCLUSION: L'information semble globalement crédible.")
            elif suspect_count > credible_count:
                print("CONCLUSION: L'information semble suspecte, vérifiez avec d'autres sources.")
            else:
                print("CONCLUSION: Les sources sont mitigées, approfondissez votre recherche.")

def main():
    searcher = TorSearchEngine()
    
    # Obtenir les paramètres de manière interactive
    params = searcher.get_input_interactive()
    
    # Démarrer Tor si demandé
    if params['start_tor']:
        if not searcher.start_tor():
            print("Impossible de démarrer Tor. Utilisation du web normal.")
            params['tor'] = False
    
    # Configurer les proxies Tor si nécessaire
    if params['tor']:
        searcher.configure_tor_proxies()
        print("Recherche via le réseau Tor activée")
        search_results = searcher.search_on_tor(params['query'], params['results'])
    else:
        print("Recherche via le web normal")
        search_results = searcher.search_on_surface_web(params['query'], params['results'])
    
    # Analyser le contenu des pages si demandé
    exact_matches = []
    partial_matches = []
    
    if params['analyze'] and search_results:
        exact_matches, partial_matches = searcher.search_content_in_pages(params['query'], search_results)
    
    # Afficher les résultats
    searcher.display_results(search_results, exact_matches, partial_matches)
    
    # Option pour sauvegarder les résultats
    save_results = input("\nVoulez-vous sauvegarder les résultats dans un fichier ? (o/n) : ").strip().lower()
    if save_results in ('o', 'oui', 'y', 'yes'):
        filename = f"recherche_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump({
                'query': params['query'],
                'timestamp': datetime.now().isoformat(),
                'search_results': search_results,
                'exact_matches': exact_matches,
                'partial_matches': partial_matches
            }, f, ensure_ascii=False, indent=2)
        print(f"Résultats sauvegardés dans {filename}")

if __name__ == "__main__":
    main()