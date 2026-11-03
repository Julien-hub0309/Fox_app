#!/usr/bin/env python3
import hashlib
import hmac
import argparse
import sys
import time
from itertools import product
import string

def hash_password(password, algorithm='sha256'):
    """Hash un mot de passe avec l'algorithme spécifié"""
    if algorithm == 'md5':
        return hashlib.md5(password.encode()).hexdigest()
    elif algorithm == 'sha1':
        return hashlib.sha1(password.encode()).hexdigest()
    elif algorithm == 'sha256':
        return hashlib.sha256(password.encode()).hexdigest()
    elif algorithm == 'sha512':
        return hashlib.sha512(password.encode()).hexdigest()
    else:
        raise ValueError(f"Algorithme non supporté: {algorithm}")

def dictionary_attack(hash_to_crack, algorithm, wordlist_path):
    """Attaque par dictionnaire"""
    try:
        with open(wordlist_path, 'r', encoding='utf-8', errors='ignore') as file:
            for word in file:
                word = word.strip()
                hashed_word = hash_password(word, algorithm)
                if hashed_word == hash_to_crack.lower():
                    return word
    except FileNotFoundError:
        print(f"Erreur: Fichier '{wordlist_path}' non trouvé.")
        return None
    return None

def brute_force_attack(hash_to_crack, algorithm, max_length=8, charset=None):
    """Attaque par force brute"""
    if charset is None:
        charset = string.ascii_lowercase + string.digits
    
    for length in range(1, max_length + 1):
        for attempt in product(charset, repeat=length):
            password = ''.join(attempt)
            hashed_password = hash_password(password, algorithm)
            if hashed_password == hash_to_crack.lower():
                return password
    return None

def identify_hash_type(hash_string):
    """Essaye d'identifier le type de hash basé sur sa longueur"""
    hash_length = len(hash_string)
    
    if hash_length == 32:
        return "md5"
    elif hash_length == 40:
        return "sha1"
    elif hash_length == 64:
        return "sha256"
    elif hash_length == 128:
        return "sha512"
    else:
        return None

def main():
    parser = argparse.ArgumentParser(description='Outil de déhashage de mots de passe')
    parser.add_argument('hash', help='Le hash à déchiffrer')
    parser.add_argument('-a', '--algorithm', choices=['md5', 'sha1', 'sha256', 'sha512', 'auto'], 
                        default='auto', help='Algorithme de hashage (auto pour détection automatique)')
    parser.add_argument('-w', '--wordlist', help='Chemin vers un fichier de dictionnaire')
    parser.add_argument('-b', '--bruteforce', action='store_true', help='Utiliser la force brute')
    parser.add_argument('-l', '--length', type=int, default=6, help='Longueur max pour la force brute')
    parser.add_argument('-c', '--charset', help='Caractères à utiliser pour la force brute')
    
    args = parser.parse_args()
    
    # Détection automatique du type de hash si nécessaire
    algorithm = args.algorithm
    if algorithm == 'auto':
        algorithm = identify_hash_type(args.hash)
        if algorithm is None:
            print("Impossible de déterminer automatiquement le type de hash. Veuillez spécifier l'algorithme.")
            sys.exit(1)
        print(f"Type de hash détecté: {algorithm}")
    
    print(f"Tentative de déhashage: {args.hash} (algorithme: {algorithm})")
    start_time = time.time()
    
    # Attaque par dictionnaire si un wordlist est fourni
    if args.wordlist:
        print("Attaque par dictionnaire en cours...")
        result = dictionary_attack(args.hash, algorithm, args.wordlist)
        if result:
            elapsed = time.time() - start_time
            print(f"Mot de passe trouvé: {result}")
            print(f"Temps écoulé: {elapsed:.2f} secondes")
            return
    
    # Attaque par force brute si demandée
    if args.bruteforce:
        charset = args.charset if args.charset else string.ascii_lowercase + string.digits
        print(f"Attaque par force brute en cours (max {args.length} caractères, charset: {charset[:20]}{'...' if len(charset) > 20 else ''})...")
        result = brute_force_attack(args.hash, algorithm, args.length, charset)
        if result:
            elapsed = time.time() - start_time
            print(f"Mot de passe trouvé: {result}")
            print(f"Temps écoulé: {elapsed:.2f} secondes")
            return
    
    # Si aucune méthode n'a fonctionné
    elapsed = time.time() - start_time
    print(f"Mot de passe non trouvé avec les méthodes spécifiées.")
    print(f"Temps écoulé: {elapsed:.2f} secondes")

if __name__ == "__main__":
    main()