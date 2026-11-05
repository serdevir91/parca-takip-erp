# PyInstaller spec for the Windows desktop app. Build from the repo root after `npm run build` in frontend/:
#   pyinstaller desktop/parca_takip.spec --noconfirm
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
BACKEND = ROOT / "backend"
APP_MODULES = sorted(".".join(p.relative_to(BACKEND).with_suffix("").parts).removesuffix(".__init__")
                     for p in (BACKEND / "app").rglob("*.py"))

a = Analysis(
    [str(ROOT / "desktop" / "parca_takip_desktop.py")],
    pathex=[str(BACKEND)],
    datas=[
        (str(BACKEND / "alembic.ini"), "."),
        # Not "alembic": a folder of that name in the bundle root would shadow the alembic package
        (str(BACKEND / "alembic"), "migrations"),
        (str(ROOT / "frontend" / "dist"), "frontend_dist"),
        (str(BACKEND / "app" / "locales"), "app/locales"),
        (str(ROOT / "desktop" / "setup.html"), "."),
        # "Sunucuma kur" uploads the backend source and this script to a Linux server
        (str(ROOT / "desktop" / "server_install.sh"), "."),
        (str(BACKEND / "app"), "server_src/app"),
        (str(BACKEND / "alembic"), "server_src/alembic"),
        (str(BACKEND / "alembic.ini"), "server_src"),
        (str(BACKEND / "requirements.txt"), "server_src"),
        (str(ROOT / "desktop" / "icon.ico"), "."),
    ],
    # Routers are found with pkgutil at runtime and uvicorn loads its protocols by name. The app modules are
    # listed from the files: collect_submodules runs in a subprocess that does not see pathex.
    hiddenimports=APP_MODULES + collect_submodules("uvicorn") + ["python_multipart", "multipart", "remote_install", "pystray._win32", "shell_i18n"] + collect_submodules("paramiko"),
    excludes=["psycopg", "psycopg_binary", "tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="LabERP",
    icon=str(ROOT / "desktop" / "icon.ico"),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="LabERP", upx=False)
