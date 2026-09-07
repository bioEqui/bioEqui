"""
Capa bronce: descarga el catalogo completo de medicamentos de Dr. Simi
recorriendo el arbol de categorias.

La API de VTEX corta alrededor de los 2500 resultados por consulta, por eso
se recorre categoria por categoria en vez de pedir todo de una vez.

Uso:
    python descargar_catalogo.py            # solo Medicamentos
    python descargar_catalogo.py --arbol    # muestra el arbol y no descarga
"""

import json
import sys
import time
from datetime import date
from pathlib import Path

import requests

DOMINIO = "https://www.drsimi.cl"
API_ARBOL = f"{DOMINIO}/api/catalog_system/pub/category/tree/5"
API_BUSCAR = f"{DOMINIO}/api/catalog_system/pub/products/search"

DESTINO = Path(__file__).resolve().parents[2] / "data" / "bronce"

# Id de la categoria raiz que interesa. 147 = Medicamentos.
RAIZ = 147

POR_PAGINA = 50
PAUSA = 2
MAX_PAGINAS = 60  # tope por categoria: 3000 productos

CABECERAS = {
    "User-Agent": "bioEqui-academico/0.1 (proyecto universitario)",
    "Accept": "application/json",
}


def obtener_arbol():
    r = requests.get(API_ARBOL, headers=CABECERAS, timeout=30)
    r.raise_for_status()
    return r.json()


def buscar_raiz(arbol, id_raiz):
    """Busca la rama que corresponde al id indicado."""
    for nodo in arbol:
        if nodo["id"] == id_raiz:
            return nodo
        encontrado = buscar_raiz(nodo.get("children", []), id_raiz)
        if encontrado:
            return encontrado
    return None


def listar_hojas(nodo, camino=None):
    """
    Devuelve las categorias hoja (sin hijos) con su ruta completa.
    La ruta es lo que la API espera en el filtro: /147/159/164/
    """
    camino = (camino or []) + [nodo["id"]]
    hijos = nodo.get("children", [])

    if not hijos:
        ruta = "/" + "/".join(str(x) for x in camino) + "/"
        return [(nodo["name"], ruta)]

    hojas = []
    for hijo in hijos:
        hojas.extend(listar_hojas(hijo, camino))
    return hojas


def descargar_categoria(ruta):
    """Descarga todos los productos de una categoria hoja."""
    productos = []
    desde = 0

    for _ in range(MAX_PAGINAS):
        parametros = {
            "fq": f"C:{ruta}",
            "_from": desde,
            "_to": desde + POR_PAGINA - 1,
        }

        r = requests.get(
            API_BUSCAR, params=parametros, headers=CABECERAS, timeout=30
        )

        # 206 es normal: significa que devuelve menos de lo pedido
        if r.status_code not in (200, 206):
            break

        pagina = r.json()
        if not pagina:
            break

        productos.extend(pagina)

        if len(pagina) < POR_PAGINA:
            break

        desde += POR_PAGINA
        time.sleep(PAUSA)

    return productos


def main():
    print("Obteniendo arbol de categorias...")
    arbol = obtener_arbol()
    raiz = buscar_raiz(arbol, RAIZ)

    if raiz is None:
        print(f"No se encontro la categoria {RAIZ}.")
        print("Categorias disponibles en el primer nivel:")
        for n in arbol:
            print(f"  {n['id']:5}  {n['name']}")
        sys.exit(1)

    hojas = listar_hojas(raiz)
    print(f"Categoria raiz: {raiz['name']}")
    print(f"Categorias hoja encontradas: {len(hojas)}\n")

    if "--arbol" in sys.argv:
        for nombre, ruta in hojas:
            print(f"  {ruta:22} {nombre}")
        return

    vistos = {}
    for i, (nombre, ruta) in enumerate(hojas, 1):
        print(f"[{i}/{len(hojas)}] {nombre}")
        try:
            productos = descargar_categoria(ruta)
        except requests.RequestException as e:
            print(f"    error: {e}")
            continue

        nuevos = 0
        for p in productos:
            pid = p.get("productId")
            if pid and pid not in vistos:
                vistos[pid] = p
                nuevos += 1

        print(f"    {len(productos)} productos, {nuevos} nuevos")
        time.sleep(PAUSA)

    DESTINO.mkdir(parents=True, exist_ok=True)
    archivo = DESTINO / f"drsimi_catalogo_{date.today().isoformat()}.json"

    archivo.write_text(
        json.dumps(
            {
                "fuente": "drsimi.cl",
                "categoria_raiz": raiz["name"],
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