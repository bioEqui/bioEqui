"""
Levanta BioEqui completo con un solo comando y abre la pagina.

    1. Docker    abre Docker Desktop si esta cerrado y espera a que responda
    2. Base      enciende el contenedor de PostgreSQL y espera la conexion
    3. API       inicia FastAPI en http://localhost:8000 (documentacion en /docs)
    4. Web       inicia la pagina (Vite) en http://localhost:5173
    5. Abre la pagina en el navegador

Si la API o la web ya estaban corriendo, no se vuelven a iniciar.
Para detener la API y la web: Ctrl+C en esta ventana (o cerrarla).
La base de datos queda encendida en Docker.

Lo que muestran la API y la web queda en logs/api.log y logs/web.log.

Uso:
    python levantar.py              levanta todo y abre el navegador
    python levantar.py --sin-abrir  levanta todo sin abrir el navegador
"""

import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

from actualizar import base_disponible

RAIZ = Path(__file__).resolve().parent
LOGS = RAIZ / "logs"
COMPOSE = RAIZ / "db" / "propuesta" / "docker-compose.yml"
CONTENEDOR = "bioequi_postgres_v2"
DOCKER_DESKTOP = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker" / "Docker" / "Docker Desktop.exe"

URL_API = "http://localhost:8000"
URL_WEB = "http://localhost:5173"


def paso(texto):
    print(f"[{time.strftime('%H:%M:%S')}] {texto}", flush=True)


def responde(url):
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return r.status < 500
    except Exception:
        return False


def esperar(condicion, segundos, cada=2):
    limite = time.time() + segundos
    while time.time() < limite:
        if condicion():
            return True
        time.sleep(cada)
    return False


def docker(*args):
    return subprocess.run(["docker", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def detener(proceso):
    """Cierra el proceso y sus hijos (npm abre node por debajo)."""
    if proceso and proceso.poll() is None:
        subprocess.run(["taskkill", "/PID", str(proceso.pid), "/T", "/F"],
                       capture_output=True)


def levantar_docker():
    if docker("info").returncode == 0:
        paso("1. Docker ya estaba abierto")
        return True
    if not DOCKER_DESKTOP.exists():
        paso(f"1. No se encontro Docker Desktop en {DOCKER_DESKTOP}")
        return False
    paso("1. Abriendo Docker Desktop (puede tardar hasta 2 minutos)...")
    subprocess.Popen([str(DOCKER_DESKTOP)])
    if esperar(lambda: docker("info").returncode == 0, 180, cada=3):
        paso("   Docker listo")
        return True
    paso("   Docker no respondio a tiempo. Abrelo a mano y vuelve a ejecutar.")
    return False


def levantar_base():
    existe = CONTENEDOR in docker("ps", "-a", "--format", "{{.Names}}").stdout.split()
    r = docker("start", CONTENEDOR) if existe else docker("compose", "-f", str(COMPOSE), "up", "-d")
    if r.returncode != 0:
        paso("2. No se pudo encender la base de datos:")
        print("   " + (r.stderr or r.stdout).strip().replace("\n", "\n   "))
        return False
    paso("2. Esperando la base de datos...")
    if esperar(lambda: base_disponible()[0], 60):
        paso("   Base de datos lista (puerto 5433)")
        return True
    paso(f"   La base no respondio: {base_disponible()[1]}")
    return False


def iniciar(nombre, comando, carpeta, url, log, espera):
    if responde(url):
        paso(f"   {nombre} ya estaba corriendo en {url}")
        return None, True
    archivo = (LOGS / log).open("w", encoding="utf-8")
    entorno = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    proceso = subprocess.Popen(comando, cwd=carpeta, stdout=archivo, stderr=subprocess.STDOUT, env=entorno)
    ok = esperar(lambda: responde(url) or proceso.poll() is not None, espera, cada=1) and proceso.poll() is None
    if ok:
        paso(f"   {nombre} lista en {url}")
    else:
        paso(f"   {nombre} no partio. Revisa logs/{log}")
    return proceso, ok


def main():
    sys.stdout.reconfigure(line_buffering=True)  # que cada mensaje se vea al instante
    abrir = "--sin-abrir" not in sys.argv
    LOGS.mkdir(exist_ok=True)
    print("Levantando BioEqui\n")

    if not levantar_docker() or not levantar_base():
        return 1

    paso("3. Iniciando la API...")
    api, ok_api = iniciar("API", [sys.executable, "-m", "uvicorn", "main:app", "--port", "8000"],
                          RAIZ / "api", URL_API + "/docs", "api.log", 40)
    if not ok_api:
        detener(api)
        return 1

    paso("4. Iniciando la pagina web...")
    frontend = RAIZ / "frontend"
    npm = shutil.which("npm") or "npm.cmd"
    if not (frontend / "node_modules").exists():
        paso("   Primera vez: instalando dependencias de la web (npm install)...")
        if subprocess.run([npm, "install"], cwd=frontend).returncode != 0:
            detener(api)
            return 1
    web, ok_web = iniciar("Pagina", [npm, "run", "dev", "--", "--port", "5173", "--strictPort"],
                          frontend, URL_WEB, "web.log", 60)
    if not ok_web:
        detener(api)
        detener(web)
        return 1

    print()
    print("  BioEqui esta funcionando")
    print(f"    Pagina:             {URL_WEB}")
    print(f"    API (documentacion): {URL_API}/docs")
    print()
    if abrir:
        webbrowser.open(URL_WEB)

    propios = [p for p in (api, web) if p]
    if not propios:
        print("  Todo ya estaba corriendo desde antes; esta ventana se puede cerrar.")
        return 0

    print("  Para detener: Ctrl+C o cierra esta ventana.")
    try:
        while True:
            for nombre, p in (("La API", api), ("La pagina", web)):
                if p and p.poll() is not None:
                    paso(f"{nombre} se detuvo inesperadamente. Revisa la carpeta logs/.")
                    detener(api)
                    detener(web)
                    return 1
            time.sleep(2)
    except KeyboardInterrupt:
        print()
        paso("Deteniendo la API y la pagina...")
        detener(api)
        detener(web)
        paso("Listo. La base de datos sigue encendida en Docker.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
