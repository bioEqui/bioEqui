"""
Ingesta ISP: junta los tres listados de equivalencia terapeutica
publicados por el Instituto de Salud Publica en un solo archivo.

Los archivos vienen con extension .xls pero en realidad son tablas HTML
codificadas en latin-1. Por eso no se abren con un lector de Excel.

Este script solo extrae y junta. No normaliza, no deriva campos y no
descarta nada: eso corresponde a la capa siguiente.

Uso:
    python consolidar_isp.py
"""

import csv
from pathlib import Path

from bs4 import BeautifulSoup

RAIZ = Path(__file__).resolve().parents[1]
ENTRADA = RAIZ / "data" / "bronce" / "isp"
SALIDA = RAIZ / "data" / "bronce"

# Nombre del archivo y el listado del que proviene
ARCHIVOS = [
    ("Referentes.xls", "referente"),
    ("Alternativas.xls", "alternativa"),
    ("Hibridos.xls", "hibrido"),
]

# Encabezados tal como vienen en la tabla, sin la primera columna vacia
COLUMNAS = [
    "registro",
    "nombre",
    "fecha_registro",
    "empresa",
    "principio_activo",
    "control_legal",
]


def leer_listado(ruta, origen):
    """Extrae las filas de un listado tal como vienen."""
    html = ruta.read_bytes().decode("latin-1")
    sopa = BeautifulSoup(html, "lxml")

    filas = []
    # La primera fila es el encabezado
    for tr in sopa.find_all("tr")[1:]:
        celdas = tr.find_all("td")
        # La primera celda viene vacia en el formato del ISP
        valores = [c.get_text(strip=True) for c in celdas[1:]]

        if len(valores) < len(COLUMNAS):
            continue
        if not valores[0]:
            continue

        fila = dict(zip(COLUMNAS, valores))
        fila["origen"] = origen
        filas.append(fila)

    return filas


def main():
    if not ENTRADA.exists():
        print(f"No existe la carpeta {ENTRADA}")
        print("Coloca alli los tres archivos descargados del ISP.")
        return

    todas = []

    for nombre, origen in ARCHIVOS:
        ruta = ENTRADA / nombre
        if not ruta.exists():
            print(f"Falta {nombre}, se omite.")
            continue

        filas = leer_listado(ruta, origen)
        print(f"{nombre}: {len(filas)} filas")
        todas.extend(filas)

    if not todas:
        print("No se extrajo ninguna fila.")
        return

    SALIDA.mkdir(parents=True, exist_ok=True)
    archivo = SALIDA / "isp_consolidado.csv"

    with archivo.open("w", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUMNAS + ["origen"])
        escritor.writeheader()
        escritor.writerows(todas)

    print(f"\n{len(todas)} filas en total")
    print(f"Guardado en {archivo}")


if __name__ == "__main__":
    main()