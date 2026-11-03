import os
from PIL import Image
from PIL.ExifTags import TAGS
from hachoir.parser import createParser
from hachoir.metadata import extractMetadata
from utile.display import console

class MetadataExtractor:
    def __init__(self, path):
        self.path = path.replace('"', '').replace("'", "")

    def run_scan(self):
        if not os.path.exists(self.path):
            console.print("[bold red]❌ Fichier introuvable.[/bold red]")
            return

        # Métadonnées Image
        if self.path.lower().endswith(('.jpg', '.jpeg', '.png')):
            try:
                with Image.open(self.path) as img:
                    info = img._getexif()
                    if info:
                        console.print("\n[bold cyan]--- EXIF DATA ---[/bold cyan]")
                        for tag, value in info.items():
                            console.print(f"{TAGS.get(tag, tag)}: {value}")
            except Exception: pass

        # Métadonnées Générales (Hachoir)
        parser = createParser(self.path)
        if parser:
            metadata = extractMetadata(parser)
            if metadata:
                console.print("\n[bold cyan]--- METADATA DOCUMENT ---[/bold cyan]")
                for line in metadata.exportPlaintext():
                    console.print(line)
            parser.stream._input.close()