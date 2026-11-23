"""
Actualizacion completa: ejecuta todo el flujo de datos con un solo comando.

    1. Bronce   descarga el catalogo de cada farmacia
    2. Control  compara cuantos productos trajo cada farmacia con su
                muestreo anterior; si cae bajo el umbral, la descarga se
                aparta y esa farmacia no se procesa
    3. Plata    normaliza cada farmacia descargada sin problemas
    4. Oro      cruza con el ISP y arma los grupos comparables
    5. Carga    lleva todo a PostgreSQL

Reglas:
    - Una farmacia que falla no detiene a las demas: se informa y se sigue.
      Su ultimo dato bueno sigue en plata, asi que oro y la carga no pierden
      nada (la carga es idempotente).
    - Si falla oro o la carga, el proceso se detiene: no tiene sentido
      seguir con datos a medio construir.
    - Una descarga sospechosa no se borra (bronce nunca se borra): se mueve
      a data/bronce/rechazados/ para revisarla.
    - Todo queda registrado en logs/actualizacion_AAAA-MM-DD_HHMM.log

Cruz Verde exige una sesion de navegador (cookie en el .env) que caduca en
horas. Si la cookie no esta o vencio, su descarga falla y se informa; el
resto de la actualizacion sigue normalmente.

Uso:
    python actualizar.py                    flujo completo
    python actualizar.py --sin-descarga     solo reprocesa plata, oro y carga
    python actualizar.py --sin-cruzverde    omite Cruz Verde
    python actualizar.py --isp              ademas reprocesa el catalogo del ISP

Codigo de salida: 0 todo bien, 2 alguna farmacia no se actualizo,
1 error que detuvo el proceso.
"""

import json
import os
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
BRONCE = RAIZ / "data" / "bronce"
RECHAZADOS = BRONCE / "rechazados"
LOGS = RAIZ / "logs"

# Si una farmacia trae menos de este porcentaje de productos respecto de su
# muestreo anterior, la descarga se considera incompleta. Entre muestreos
# normales la variacion es menor al 5%; la caida de Profar (1.950 a 390)
# fue al 20% y paso inadvertida varias semanas.
UMBRAL = 0.80

# Tiempo maximo por paso, en segundos
LIMITE_DESCARGA = 60 * 60
LIMITE_PROCESO = 20 * 60

FARMACIAS = [
    # nombre, prefijo del archivo, script de descarga, script de normalizacion
    ("Dr. Simi", "drsimi", "scraping/drsimi/descargar_catalogo.py", "scraping/drsimi/normalizar_drsimi.py"),
    ("Cruz Verde", "cruzverde", "scraping/cruzVerde/descargar_catalogo_cruzverde.py", "scraping/cruzVerde/normalizar_cruzverde.py"),
    ("Ahumada", "ahumada", "scraping/ahumada/descargar_catalogo_ahumada.py", "scraping/ahumada/normalizar_ahumada.py"),
    ("Profar", "profar", "scraping/profar/descargar_catalogo_profar.py", "scraping/profar/normalizar_profar.py"),
    ("Liga", "liga", "scraping/liga/descargar_catalogo_liga.py", "scraping/liga/normalizar_liga.py"),
    ("Novasalud", "novasalud", "scraping/novasalud/descargar_catalogo_novasalud.py", "scraping/novasalud/normalizar_novasalud.py"),
]


class Registro:
    """Escribe en pantalla y en el archivo de log a la vez."""

    def __init__(self, ruta):
        self.archivo = ruta.open("w", encoding="utf-8")

    def __call__(self, texto="", solo_archivo=False):
        linea = f"[{datetime.now():%H:%M:%S}] {texto}" if texto else ""
        self.archivo.write(linea + "\n")
        self.archivo.flush()
        if not solo_archivo:
            print(linea, flush=True)

    def cerrar(self):
        self.archivo.close()


def ejecutar(log, script, argumentos=(), limite=LIMITE_PROCESO):
    """Corre un script del proyecto. Su salida completa va solo al log."""
    entorno = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    inicio = time.time()
    log(f"--- {script} {' '.join(argumentos)}", solo_archivo=True)
    try:
        r = subprocess.run(
            [sys.executable, str(RAIZ / script), *argumentos],
            cwd=RAIZ,
            env=entorno,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=limite,
        )
        salida = (r.stdout or "") + (r.stderr or "")
        codigo = r.returncode
    except subprocess.TimeoutExpired:
        salida, codigo = f"Se supero el limite de {limite // 60} minutos", -1

    for linea in salida.rstrip().splitlines():
        log("    " + linea, solo_archivo=True)

    ultima = next((l for l in reversed(salida.strip().splitlines()) if l.strip()), "")
    return codigo == 0, ultima.strip(), time.time() - inicio


def total_productos(ruta):
    """Cantidad de productos declarada en un catalogo de bronce."""
    with ruta.open(encoding="utf-8") as f:
        datos = json.load(f)
    return datos.get("total", len(datos.get("productos", [])))


def descarga_incompleta(total, total_previo):
    """True si la descarga trajo menos del UMBRAL del muestreo anterior."""
    return bool(total_previo) and total < UMBRAL * total_previo


def anterior(prefijo, hoy):
    """Ultimo catalogo de la farmacia anterior al de hoy."""
    previos = sorted(
        p for p in BRONCE.glob(f"{prefijo}_catalogo_*.json") if p.name != hoy.name
    )
    return previos[-1] if previos else None


def base_disponible():
    """Comprueba la conexion antes de empezar, para no descargar en vano."""
    try:
        import psycopg2
        from dotenv import load_dotenv
    except ImportError as e:
        return False, f"falta una dependencia: {e.name}"

    load_dotenv(RAIZ / ".env")
    try:
        psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5433"),
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            connect_timeout=5,
        ).close()
        return True, ""
    except Exception as e:
        return False, str(e).strip().splitlines()[0]


def main():
    sin_descarga = "--sin-descarga" in sys.argv
    sin_cruzverde = "--sin-cruzverde" in sys.argv
    con_isp = "--isp" in sys.argv

    LOGS.mkdir(exist_ok=True)
    ruta_log = LOGS / f"actualizacion_{datetime.now():%Y-%m-%d_%H%M}.log"
    log = Registro(ruta_log)
    inicio = time.time()
    hoy = date.today().isoformat()

    log(f"Actualizacion de BioEqui - {hoy}")
    log(f"Registro completo en {ruta_log.relative_to(RAIZ)}")
    log()

    ok, motivo = base_disponible()
    if not ok:
        log("DETENIDO: no hay conexion con la base de datos.")
        log(f"  {motivo}")
        log("  Abre Docker Desktop y verifica que el contenedor este corriendo.")
        log.cerrar()
        return 1

    resultado = {}  # nombre -> (estado, detalle)
    a_normalizar = []

    # 1-2. Bronce y control de volumen
    if sin_descarga:
        log("Descarga omitida (--sin-descarga): se reprocesan los ultimos catalogos")
        a_normalizar = [(n, p, norm, None) for n, p, _, norm in FARMACIAS]
    else:
        log("1. Descarga (bronce)")
        for nombre, prefijo, descarga, normalizacion in FARMACIAS:
            if prefijo == "cruzverde" and sin_cruzverde:
                resultado[nombre] = ("omitida", "--sin-cruzverde")
                log(f"   {nombre:11} omitida")
                continue

            archivo = BRONCE / f"{prefijo}_catalogo_{hoy}.json"
            previo = anterior(prefijo, archivo)

            # Si ya habia un catalogo de hoy (otra ejecucion), solo cuenta
            # si esta descarga lo volvio a escribir
            antes = time.time()
            exito, ultima, segundos = ejecutar(log, descarga, limite=LIMITE_DESCARGA)
            if not exito or not archivo.exists() or archivo.stat().st_mtime < antes:
                detalle = ultima or "no genero el catalogo"
                if prefijo == "cruzverde":
                    detalle += " (cookie vencida? renueva CRUZVERDE_COOKIE en el .env)"
                resultado[nombre] = ("fallo", detalle)
                log(f"   {nombre:11} FALLO   {detalle}")
                continue

            total = total_productos(archivo)
            texto = f"{total:>5} productos en {segundos / 60:.1f} min"

            if previo:
                total_previo = total_productos(previo)
                if descarga_incompleta(total, total_previo):
                    RECHAZADOS.mkdir(exist_ok=True)
                    archivo.replace(RECHAZADOS / archivo.name)
                    detalle = (f"trajo {total} productos y antes {total_previo} "
                               f"({100 * total / total_previo:.0f}%); se aparto en bronce/rechazados")
                    resultado[nombre] = ("rechazada", detalle)
                    log(f"   {nombre:11} RECHAZADA  {detalle}")
                    continue
                texto += f" (anterior: {total_previo})"

            resultado[nombre] = ("ok", texto)
            log(f"   {nombre:11} ok      {texto}")
            a_normalizar.append((nombre, prefijo, normalizacion, archivo.name))

        if not a_normalizar:
            log()
            log("DETENIDO: ninguna farmacia se descargo correctamente.")
            log.cerrar()
            return 1

    # 3. Plata
    log()
    log("2. Normalizacion (plata)")
    if con_isp:
        for script in ("ingesta_isp/consolidar_isp.py", "ingesta_isp/normalizacion_isp.py"):
            exito, ultima, _ = ejecutar(log, script)
            if not exito:
                log(f"DETENIDO: fallo {script}: {ultima}")
                log.cerrar()
                return 1
        log("   ISP         ok")

    for nombre, prefijo, normalizacion, archivo in a_normalizar:
        argumentos = [archivo] if archivo and prefijo != "profar" else []
        exito, ultima, _ = ejecutar(log, normalizacion, argumentos)
        if exito:
            log(f"   {nombre:11} ok")
            if nombre not in resultado:
                resultado[nombre] = ("ok", "reprocesada")
        else:
            resultado[nombre] = ("fallo", f"normalizacion: {ultima}")
            log(f"   {nombre:11} FALLO   {ultima}")

    # 4-5. Oro y carga: si fallan, se detiene todo
    for paso, script in (("3. Cruce (oro)", "cruce/construccion_oro.py"),
                         ("4. Carga a PostgreSQL", "db/cargar.py")):
        log()
        log(paso)
        exito, ultima, segundos = ejecutar(log, script)
        if not exito:
            log(f"DETENIDO: {ultima}")
            log(f"Revisa el detalle en {ruta_log.relative_to(RAIZ)}")
            log.cerrar()
            return 1
        log(f"   ok en {segundos:.0f} s")

    # Resumen
    problemas = {n: r for n, r in resultado.items() if r[0] not in ("ok",)}
    log()
    log(f"Terminado en {(time.time() - inicio) / 60:.1f} min. "
        f"Farmacias actualizadas: {sum(1 for r in resultado.values() if r[0] == 'ok')} de {len(FARMACIAS)}")
    for nombre, (estado, detalle) in problemas.items():
        log(f"   {nombre}: {estado} - {detalle}")
    log.cerrar()
    return 2 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
