"""
Ejecuta el pipeline completo en orden y deja registro de lo ocurrido.

Pensado para ejecucion desatendida: si un paso falla, se detiene ahi en
lugar de seguir con datos incompletos, y el registro queda en logs/ para
poder revisar despues que paso.

El catalogo del ISP se omite por defecto porque cambia poco y sus
archivos se descargan a mano desde el portal. Se incluye con --con-isp
cuando se hayan actualizado.

Uso:
    python actualizar.py              solo precios (uso diario)
    python actualizar.py --con-isp    incluye el catalogo del ISP
    python actualizar.py --sin-carga  hasta oro, sin tocar la base
"""

import subprocess
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
LOGS = RAIZ / "logs"

# Cada paso es (descripcion, ruta del script, solo_con_isp)
PASOS = [
    ("Consolidar listados del ISP", "ingesta_isp/consolidar_isp.py", True),
    ("Normalizar catalogo del ISP", "ingesta_isp/normalizacion_isp.py", True),
    ("Descargar catalogo Dr. Simi", "scraping/drsimi/descargar_catalogo.py", False),
    ("Normalizar catalogo Dr. Simi", "scraping/drsimi/normalizar_drsimi.py", False),
    ("Cruzar fuentes y construir oro", "cruce/construccion_oro.py", False),
]

PASO_CARGA = ("Cargar a PostgreSQL", "db/cargar.py")


def registrar(mensaje, archivo):
    """Escribe en pantalla y en el archivo de registro."""
    print(mensaje)
    archivo.write(mensaje + "\n")
    archivo.flush()


def ejecutar(descripcion, script, log):
    ruta = RAIZ / script

    if not ruta.exists():
        registrar(f"  ERROR: no existe {script}", log)
        return False

    inicio = datetime.now()
    registrar(f"\n{descripcion}", log)
    registrar(f"  {script}", log)

    resultado = subprocess.run(
        [sys.executable, str(ruta)],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    duracion = (datetime.now() - inicio).total_seconds()

    # La salida del script se guarda completa en el registro
    for linea in (resultado.stdout or "").splitlines():
        log.write(f"    {linea}\n")

    if resultado.returncode != 0:
        registrar(f"  FALLO despues de {duracion:.0f}s", log)
        for linea in (resultado.stderr or "").splitlines()[-15:]:
            registrar(f"    {linea}", log)
        return False

    registrar(f"  OK ({duracion:.0f}s)", log)
    return True


def main():
    con_isp = "--con-isp" in sys.argv
    sin_carga = "--sin-carga" in sys.argv

    LOGS.mkdir(exist_ok=True)
    marca = datetime.now()
    archivo_log = LOGS / f"actualizacion_{marca:%Y-%m-%d_%H%M}.log"

    pasos = [p for p in PASOS if not p[2] or con_isp]
    if not sin_carga:
        pasos.append((PASO_CARGA[0], PASO_CARGA[1], False))

    with archivo_log.open("w", encoding="utf-8") as log:
        registrar(f"Actualizacion iniciada {marca:%Y-%m-%d %H:%M}", log)
        if con_isp:
            registrar("Incluye catalogo del ISP", log)

        for descripcion, script, _ in pasos:
            if not ejecutar(descripcion, script, log):
                # Detenerse aqui evita cargar datos incompletos a la base
                registrar("\nProceso interrumpido. Revisa el registro.", log)
                registrar(f"Registro en {archivo_log}", log)
                sys.exit(1)

        total = (datetime.now() - marca).total_seconds()
        registrar(f"\nActualizacion completa en {total/60:.1f} minutos", log)
        registrar(f"Registro en {archivo_log}", log)


if __name__ == "__main__":
    main()