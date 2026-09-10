"""
Script utilitario para empaquetar el Add-on/Extensión en formato .zip listo para Blender.
Uso: python build_extension.py
"""

import os
import zipfile

def build_zip(zip_name="blender_ai_agent.zip", root_folder="blender_ai_agent"):
    exclude_dirs = {".git", "tests", "__pycache__", ".pytest_cache"}
    exclude_files = {".gitignore", zip_name, "build_extension.py"}

    if os.path.exists(zip_name):
        os.remove(zip_name)

    print(f"Empaquetando extensión en '{zip_name}'...")
    count = 0

    with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk("."):
            dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith(".")]
            for f in files:
                if f in exclude_files or f.endswith(".pyc") or f.endswith(".zip"):
                    continue
                filepath = os.path.join(root, f)
                relpath = os.path.relpath(filepath, ".")
                arcname = os.path.join(root_folder, relpath)
                zf.write(filepath, arcname)
                count += 1

    print(f"¡Éxito! Se empaquetaron {count} archivos en '{os.path.abspath(zip_name)}'.")

if __name__ == "__main__":
    build_zip()
