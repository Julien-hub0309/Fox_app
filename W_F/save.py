import pytsk3
import os
import sys

def recover_deleted_files():
    # Demande interactive du chemin d'accès
    print("--- Assistant de Récupération de Données ---")
    image_path = input("Entrez le chemin de l'image disque ou du disque physique (ex: sdb1, image.dd) : ").strip()

    # Vérification sommaire de l'existence du chemin
    if not os.path.exists(image_path) and not image_path.startswith('\\\\.\\'):
        print(f"Erreur : Le chemin '{image_path}' est introuvable.")
        return

    try:
        # Chargement de l'image disque
        img_info = pytsk3.Img_Info(image_path)
        
        # Ouverture du système de fichiers
        fs_info = pytsk3.FS_Info(img_info)
        
        print(f"\nAnalyse en cours sur : {image_path}")
        print("-" * 40)

        # Parcours de la racine
        root_dir = fs_info.open_dir(path="/")
        found_any = False
        
        for fs_object in root_dir:
            # On cherche les métadonnées marquées comme non allouées
            if fs_object.info.meta and fs_object.info.meta.flags & pytsk3.TSK_FS_META_FLAG_UNALLOC:
                
                # Récupération du nom (gestion de l'encodage)
                try:
                    name = fs_object.info.name.name.decode('utf-8')
                except:
                    name = "Nom_Inconnu"

                if name in [".", ".."]:
                    continue
                
                print(f"[TROUVÉ] Nom : {name} | Taille : {fs_object.info.meta.size} octets")
                found_any = True

        if not found_any:
            print("Aucun fichier supprimé n'a été détecté dans le répertoire racine.")

    except Exception as e:
        print(f"\nErreur critique : {e}")
        print("Note : Sous Windows, lancez le terminal en Administrateur pour les disques physiques.")

if __name__ == "__main__":
    recover_deleted_files()