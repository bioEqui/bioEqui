"""
Capa bronce: descarga el catalogo de medicamentos de Farmacias Novasalud.

El sitio opera sobre Magento y entrega los datos en el HTML. Se extrae en
dos fases, igual que Ahumada:

    Fase 1 (cada ejecucion)
        Recorre las paginas de /medicamentos y obtiene de cada producto su
        identificador, enlace, imagen y precios. Unas 40 peticiones.

    Fase 2 (solo productos nuevos)
        Visita la ficha de cada producto para obtener principio activo,
        forma farmaceutica, dosis, condicion de venta, laboratorio y precio
        fraccionado. Estos datos no cambian, asi que se guardan en cache y
        no se vuelven a pedir. La primera ejecucion tarda unos 50 minutos;
        las siguientes, un par.

Restricciones del robots.txt que se respetan: solo se usa el parametro
de paginacion p, que es el unico que el sitio permite en los listados.

Uso:
    python descargar_catalogo_novasalud.py
    python descargar_catalogo_novasalud.py --sin-fichas     solo fase 1
"""

import json
import math
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DOMINIO = "https://www.novasalud.cl"
URL_LISTADO = f"{DOMINIO}/medicamentos"

RAIZ = Path(__file__).resolve().parents[2]
DESTINO = RAIZ / "data" / "bronce"
CACHE_FICHAS = DESTINO / "novasalud_fichas.json"

PAUSA = 2

# Tope de seguridad: con 36 productos por pagina alcanza para 3600
MAX_PAGINAS = 100

CABECERAS = {
    "User-Agent": "bioEqui-academico/0.1 (proyecto universitario)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "es-CL,es;q=0.9",
}

session = requests.Session()
retries = Retry(
    total=5,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
)
session.mount("https://", HTTPAdapter(max_retries=retries))


def pedir(url, params=None):
    r = session.get(url, params=params, headers=CABECERAS, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def numero(texto):
    """'$39.900' -> 39900"""
    digitos = re.sub(r"[^\d]", "", texto or "")
    return int(digitos) if digitos else None


def leer_tarjeta(tarjeta):
    enlace = tarjeta.select_one("a.product-item-link[href]")
    if not enlace:
        return None

    caja_precio = tarjeta.select_one("[data-role=priceBox][data-product-id]")
    pid = caja_precio.get("data-product-id") if caja_precio else ""
    if not pid:
        pid = tarjeta.get("id", "").replace("product-item-info_", "")

    precios = {}
    for p in tarjeta.select("[data-price-type][data-price-amount]"):
        precios[p["data-price-type"]] = int(float(p["data-price-amount"]))

    sku = tarjeta.select_one("[data-product-sku]")
    imagen = tarjeta.select_one("img.product-image-photo")

    return {
        "pid": pid,
        "sku": sku.get("data-product-sku", "") if sku else "",
        "nombre": enlace.get_text(" ", strip=True),
        "url": enlace["href"],
        "url_imagen": imagen.get("src", "") if imagen else "",
        # finalPrice es lo que se paga; oldPrice solo aparece si hay oferta
        "precio_final": precios.get("finalPrice"),
        "precio_normal": precios.get("oldPrice"),
        # El listado marca "Agotado" y quita el boton de compra. Se toma de
        # aca y no de la ficha porque la ficha queda en cache
        "disponible": tarjeta.select_one(".stock.unavailable") is None,
    }


def total_productos(soup):
    """'Articulos 1 - 36 de 1430' -> 1430"""
    caja = soup.select_one(".toolbar-amount")
    numeros = re.findall(r"\d+", caja.get_text(" ", strip=True)) if caja else []
    return int(numeros[-1]) if numeros else None


def leer_ficha(soup):
    """
    Los datos clinicos estan en la tabla de atributos de la ficha. Se
    leen por nombre de fila, no por posicion: no todas las fichas traen
    las mismas filas.
    """
    atributos = {}
    for fila in soup.select("table.additional-attributes tr"):
        th, td = fila.find("th"), fila.find("td")
        if th and td:
            atributos[th.get_text(" ", strip=True)] = td.get_text(" ", strip=True)

    titulo = soup.select_one("h1.page-title")
    canonico = soup.select_one("link[rel=canonical]")

    return {
        "titulo": titulo.get_text(" ", strip=True) if titulo else "",
        "url_canonica": canonico.get("href", "") if canonico else "",
        "atributos": atributos,
    }


def cargar_cache():
    if CACHE_FICHAS.exists():
        return json.loads(CACHE_FICHAS.read_text(encoding="utf-8"))
    return {}


def guardar_cache(cache):
    DESTINO.mkdir(parents=True, exist_ok=True)
    CACHE_FICHAS.write_text(
        json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def main():
    sin_fichas = "--sin-fichas" in sys.argv

    print("Fase 1: listado de medicamentos")
    listado = {}
    paginas = MAX_PAGINAS

    pagina = 1
    while pagina <= paginas:
        try:
            soup = pedir(URL_LISTADO, params={"p": pagina})
        except requests.RequestException as e:
            print(f"  pagina {pagina}: error {e}")
            print(f"ATENCION: listado incompleto, {len(listado)} productos")
            break

        if pagina == 1:
            total = total_productos(soup)
            tarjetas_por_pagina = len(soup.select("div.product-item-info")) or 1
            if total:
                paginas = min(MAX_PAGINAS, math.ceil(total / tarjetas_por_pagina))
                print(f"  {total} productos en {paginas} paginas")

        nuevos = 0
        for tarjeta in soup.select("div.product-item-info"):
            p = leer_tarjeta(tarjeta)
            if p and p["pid"] and p["pid"] not in listado:
                listado[p["pid"]] = p
                nuevos += 1

        print(f"  [{pagina}/{paginas}] {nuevos} nuevos")

        # Magento repite la ultima pagina si se pide una que no existe
        if not nuevos:
            break

        pagina += 1
        time.sleep(PAUSA)

    print(f"\n{len(listado)} productos unicos en el listado")

    cache = cargar_cache()

    if not sin_fichas:
        pendientes = [p for pid, p in listado.items() if pid not in cache]
        print(f"\nFase 2: {len(pendientes)} fichas nuevas ({len(cache)} ya en cache)")

        for i, p in enumerate(pendientes, 1):
            try:
                cache[p["pid"]] = leer_ficha(pedir(p["url"]))
            except requests.RequestException as e:
                print(f"  {p['pid']}: error {e}")

            # Guardar cada cierto tiempo: si se interrumpe, no se pierde
            # lo avanzado
            if i % 50 == 0:
                guardar_cache(cache)
                print(f"  {i}/{len(pendientes)}")

            time.sleep(PAUSA)

        guardar_cache(cache)

    productos = []
    sin_ficha = 0
    for pid, p in listado.items():
        ficha = cache.get(pid)
        if not ficha:
            sin_ficha += 1
        productos.append({**p, "ficha": ficha or {}})

    DESTINO.mkdir(parents=True, exist_ok=True)
    archivo = DESTINO / f"novasalud_catalogo_{date.today().isoformat()}.json"
    archivo.write_text(
        json.dumps(
            {
                "fuente": "novasalud.cl",
                "categoria_raiz": "medicamentos",
                "fecha_muestreo": date.today().isoformat(),
                "total": len(productos),
                "sin_ficha": sin_ficha,
                "productos": productos,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    print(f"\n{len(productos)} productos guardados en {archivo.name}")
    if sin_ficha:
        print(f"  {sin_ficha} sin ficha: quedaran sin principio activo")


if __name__ == "__main__":
    main()
