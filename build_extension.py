"""
Script utilitario para empaquetar el Add-on/Extensión en formato .zip listo para Blender.
Uso: python build_extension.py
"""

import os
import zipfile

def build_zip(zip_name="blender_ai_agent.zip", root_folder="blender_ai_agent"):
    exclude_dirs = {".git", "tests", "__pycache__", ".pytest_cache"}
    exclude_files = {".gitignore", zip_name, "build_extension.py"}

    temp_zip = f"{zip_name}.tmp"
    if os.path.exists(temp_zip):
        try:
            os.remove(temp_zip)
        except OSError:
            pass

    # Empaquetar en blender_ai_agent_v0.1.0.zip y blender_ai_agent.zip
    target_names = ["blender_ai_agent.zip", "blender_ai_agent_v0.1.0.zip"]
    
    for zname in target_names:
        try:
            with zipfile.ZipFile(zname, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk("."):
                    dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith(".")]
                    for f in files:
                        if f in exclude_files or f.endswith(".pyc") or f.endswith(".zip") or f.endswith(".tmp"):
                            continue
                        filepath = os.path.join(root, f)
                        relpath = os.path.relpath(filepath, ".")
                        arcname = os.path.join(root_folder, relpath)
                        zf.write(filepath, arcname)
            print(f"¡Éxito! Empaquetado '{os.path.abspath(zname)}'.")
        except PermissionError:
            print(f"Aviso: '{zname}' está bloqueado por Blender. Se generará la versión alternativa.")

if __name__ == "__main__":
    build_zip()
