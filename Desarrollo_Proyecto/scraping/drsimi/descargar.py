"""
Capa bronce: descarga productos desde la API de catalogo de Dr. Simi
y los guarda tal cual llegan, sin transformar nada.

Uso:
    python descargar.py paracetamol
    python descargar.py ibuprofeno
"""

import json
import sys
import time
from datetime import date
from pathlib import Path

import requests

BASE = "https://www.drsimi.cl/api/catalog_system/pub/products/search"

# Carpeta de destino, relativa a la raiz del proyecto
DESTINO = Path(__file__).resolve().parents[2] / "data" / "bronce"

# Cuantos productos pide por vez. VTEX no permite mas de 50.
POR_PAGINA = 50

# Pausa entre peticiones, en segundos. No la bajes: es lo que hace
# que la extraccion sea respetuosa con el servidor.
PAUSA = 2

# Tope de seguridad para no quedar en un bucle infinito
MAX_PAGINAS = 20

CABECERAS = {
    "User-Agent": "bioEqui-academico/0.1 (proyecto universitario)",
    "Accept": "application/json",
}


def pedir_pagina(termino, desde):
    """Pide un tramo de resultados. Devuelve la lista de productos."""
    hasta = desde + POR_PAGINA - 1
    parametros = {"ft": termino, "_from": desde, "_to": hasta}

    respuesta = requests.get(
        BASE, params=parametros, headers=CABECERAS, timeout=30
    )
    respuesta.raise_for_status()
    return respuesta.json()


def descargar(termino):
    productos = []
    desde = 0

    for _ in range(MAX_PAGINAS):
        print(f"  pidiendo productos {desde} a {desde + POR_PAGINA - 1}...")

        try:
            pagina = pedir_pagina(termino, desde)
        except requests.HTTPError as e:
            # VTEX responde 206 cuando quedan menos resultados de los pedidos
            if e.response is not None and e.response.status_code == 416:
                break
            raise

        if not pagina:
            break

        productos.extend(pagina)

        if len(pagina) < POR_PAGINA:
            break

        desde += POR_PAGINA
        time.sleep(PAUSA)

    return productos


def guardar(termino, productos):
    DESTINO.mkdir(parents=True, exist_ok=True)
    archivo = DESTINO / f"drsimi_{termino}_{date.today().isoformat()}.json"

    contenido = {
        "fuente": "drsimi.cl",
        "termino": termino,
        "fecha_muestreo": date.today().isoformat(),
        "total": len(productos),
        "productos": productos,
    }

    archivo.write_text(
        json.dumps(contenido, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return archivo


def main():
    if len(sys.argv) < 2:
        print("Falta el termino de busqueda.")
        print("Ejemplo:  python descargar.py paracetamol")
        sys.exit(1)

    termino = sys.argv[1]
    print(f"Buscando '{termino}' en drsimi.cl")

    productos = descargar(termino)

    if not productos:
        print("No se obtuvo ningun producto. Revisa el termino o la conexion.")
        sys.exit(1)

    archivo = guardar(termino, productos)
    print(f"\n{len(productos)} productos guardados en:")
    print(f"  {archivo}")


if __name__ == "__main__":
    main()