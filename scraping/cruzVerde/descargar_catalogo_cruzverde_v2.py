"""
Capa bronce: descarga el catalogo de medicamentos de Cruz Verde desde la
API publica que alimenta su sitio.

Version sin cookies de sesion ni user-agent falso. La version anterior
copiaba la sesion del navegador, lo que tiene dos problemas: las cookies
caducan en pocos dias y contradice el compromiso de extraccion
identificable que declara el proyecto.

Uso:
    python descargar_catalogo_cruzverde.py
    python descargar_catalogo_cruzverde.py --diagnostico   una sola pagina
"""

import json
import sys
import time
from datetime import date
from pathlib import Path

import requests

API = "https://api.cruzverde.cl/product-service/products/search"

DESTINO = Path(__file__).resolve().parents[2] / "data" / "bronce"

POR_PAGINA = 50
PAUSA = 2
MAX_PAGINAS = 100

CABECERAS = {
    "User-Agent": "bioEqui-academico/0.1 (proyecto universitario)",
    "Accept": "application/json",
}

# La API exige una zona de inventario porque los precios varian por
# region. Se deja explicita para que el dato sea interpretable: los
# precios corresponden a esta zona y no al pais completo.
ZONA = "Zonapañales1119"

PARAMETROS_BASE = {
    "limit": POR_PAGINA,
    "sort": "",
    "q": "",
    "refine[]": "cgid=ver-todo-medicamentos",
    "isAndes": "true",
    "requestPage": "CLP",
    "inventoryId": ZONA,
    "inventoryZone": ZONA,
}


def pedir(offset):
    parametros = dict(PARAMETROS_BASE, offset=offset)
    r = requests.get(API, params=parametros, headers=CABECERAS, timeout=30)
    r.raise_for_status()
    return r.json()


def diagnostico():
    """Pide una sola pagina y reporta que campos llegan completos."""
    print("Pidiendo una pagina de prueba sin cookies...\n")

    try:
        datos = pedir(0)
    except requests.HTTPError as e:
        print(f"La API respondio {e.response.status_code}.")
        print("Es probable que exija sesion. Revisa el cuerpo de la respuesta:")
        print((e.response.text or "")[:400])
        return
    except requests.RequestException as e:
        print(f"Error de conexion: {e}")
        return

    items = datos.get("hits") or datos.get("products") or []
    print(f"Productos recibidos: {len(items)}")

    if not items:
        print("La respuesta no trae productos. Claves recibidas:")
        print(list(datos.keys()))
        return

    campos = [
        "productId",
        "productName",
        "productBrand",
        "pdpUrl",
        "imageUrl",
        "prices",
        "isBioequivalent",
        "pum",
        "stock",
    ]

    print("\nCompletitud de campos en esta pagina:")
    for c in campos:
        n = sum(1 for p in items if p.get(c) not in (None, "", [], {}))
        print(f"  {c:18} {n:3}/{len(items)}")

    print("\nPrimer producto:")
    for c in campos:
        print(f"  {c:18} {str(items[0].get(c))[:70]}")


def descargar():
    productos = []
    offset = 0

    for _ in range(MAX_PAGINAS):
        print(f"  productos {offset} a {offset + POR_PAGINA - 1}...")

        try:
            datos = pedir(offset)
        except requests.RequestException as e:
            print(f"  error: {e}")
            break

        items = datos.get("hits") or datos.get("products") or []
        if not items:
            break

        productos.extend(items)

        if len(items) < POR_PAGINA:
            break

        offset += POR_PAGINA
        time.sleep(PAUSA)

    return productos


def main():
    if "--diagnostico" in sys.argv:
        diagnostico()
        return

    print("Descargando catalogo de Cruz Verde")
    productos = descargar()

    if not productos:
        print("No se obtuvo ningun producto.")
        print("Ejecuta con --diagnostico para ver que responde la API.")
        return

    # Deduplicar: un producto puede repetirse entre paginas
    vistos = {}
    for p in productos:
        pid = p.get("productId")
        if pid and pid not in vistos:
            vistos[pid] = p

    DESTINO.mkdir(parents=True, exist_ok=True)
    archivo = DESTINO / f"cruzverde_catalogo_{date.today().isoformat()}.json"

    archivo.write_text(
        json.dumps(
            {
                "fuente": "cruzverde.cl",
                "categoria_raiz": "ver-todo-medicamentos",
                "zona_inventario": ZONA,
                "fecha_muestreo": date.today().isoformat(),
                "total": len(vistos),
                "productos": list(vistos.values()),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\n{len(vistos)} productos unicos guardados en:")
    print(f"  {archivo}")


if __name__ == "__main__":
    main()