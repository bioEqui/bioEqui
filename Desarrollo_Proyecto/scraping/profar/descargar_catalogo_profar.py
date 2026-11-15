"""
Capa bronce: descarga el catálogo completo de medicamentos de Farmacias Profar
desde la API GraphQL de Magento (https://profar.cl/graphql).

El listado HTML no sirve: robots.txt prohíbe paginar (/*?p=) y el redirect de
www a profar.cl descarta el parámetro, así que siempre llegaba la página 1.
La API entrega todo el catálogo por páginas, con precio, stock, registro ISP,
principio activo y bioequivalencia, sin abrir la ficha de cada producto.

Se guarda con el mismo formato que usaba el scraper HTML para que
normalizar_profar.py lo siga leyendo igual.

Uso:
    python descargar_catalogo_profar.py
"""

import json
import time
from datetime import date
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DESTINO = Path(__file__).resolve().parents[2] / "data" / "bronce"

URL_API = "https://profar.cl/graphql"
URL_SITIO = "https://profar.cl/"
ID_CATEGORIA = "3"  # Medicamentos
POR_PAGINA = 100
PAUSA = 2

CABECERAS = {
    "User-Agent": "bioEqui-academico/0.1 (proyecto universitario)",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# Los atributos propios de Profar no salen en los campos normales del
# producto: hay que pedirlos con custom_attributesV2. Pedirlos todos de una
# vez da "Internal server error" en algunos productos, por eso se piden dos
# grupos que si responden: el de la ficha (registro, principio, venta) y el
# de los filtros (marca)
CONSULTA = """
query ($pagina: Int!, $tamano: Int!) {
  products(filter: {category_id: {eq: "%s"}}, pageSize: $tamano, currentPage: $pagina) {
    total_count
    page_info { total_pages }
    items {
      sku
      name
      url_key
      url_suffix
      stock_status
      small_image { url }
      price_range {
        minimum_price {
          regular_price { value }
          final_price { value }
        }
      }
      ficha: custom_attributesV2(filters: {is_html_allowed_on_front: true}) {
        items {
          code
          ... on AttributeValue { value }
          ... on AttributeSelectedOptions { selected_options { label } }
        }
      }
      filtros: custom_attributesV2(filters: {is_filterable: true}) {
        items {
          code
          ... on AttributeValue { value }
          ... on AttributeSelectedOptions { selected_options { label } }
        }
      }
    }
  }
}
""" % ID_CATEGORIA

# Nombre con que el scraper HTML guardaba cada atributo de la ficha
ETIQUETAS = {
    "registro_isp": "Registro ISP",
    "principio_activo": "Principio Activo",
    "condicion_de_venta": "Condición de Venta",
    "forma_farmaceutica": "Forma Farmacéutica",
    "marca": "Marca",
}

session = requests.Session()
reintentos = Retry(
    total=5,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["POST"],
)
session.mount("https://", HTTPAdapter(max_retries=reintentos))


def atributos(grupo):
    """Convierte la lista de custom_attributesV2 en {codigo: texto}."""
    salida = {}
    for item in (grupo or {}).get("items") or []:
        if "selected_options" in item:
            valor = ", ".join(o["label"] for o in item["selected_options"] or [])
        else:
            valor = item.get("value") or ""
        salida[item["code"]] = valor.strip()
    return salida


def precio(rango, tipo):
    # Magento guarda el precio neto; price_range ya trae el IVA incluido,
    # que es el precio que muestra la tienda
    valor = ((rango or {}).get("minimum_price") or {}).get(tipo, {}).get("value")
    return round(valor) if valor else None


def pedir_pagina(pagina):
    respuesta = session.post(
        URL_API,
        json={"query": CONSULTA, "variables": {"pagina": pagina, "tamano": POR_PAGINA}},
        headers=CABECERAS,
        timeout=60,
    )
    respuesta.raise_for_status()
    datos = respuesta.json()
    if datos.get("errors"):
        print(f"  aviso en página {pagina}: {datos['errors'][0].get('message')}")
    return (datos.get("data") or {}).get("products") or {}


def convertir(item):
    ficha = atributos(item.get("ficha"))
    ficha.update({k: v for k, v in atributos(item.get("filtros")).items() if v})

    especificaciones = {
        etiqueta: ficha[codigo] for codigo, etiqueta in ETIQUETAS.items() if ficha.get(codigo)
    }

    return {
        "sku": item.get("sku"),
        "productName": item.get("name"),
        "price-sale-cl": precio(item.get("price_range"), "final_price"),
        "price-list-cl": precio(item.get("price_range"), "regular_price"),
        "pdpUrl": f"{URL_SITIO}{item.get('url_key')}{item.get('url_suffix') or '.html'}",
        "imageUrl": (item.get("small_image") or {}).get("url", ""),
        "isBioequivalent": ficha.get("bioequivalente") == "1",
        "disponible": item.get("stock_status") == "IN_STOCK",
        "ean": ficha.get("ean", ""),
        "especificaciones": especificaciones,
    }


def extraer_profar():
    print("Descargando catálogo de Profar desde la API GraphQL...")
    primera = pedir_pagina(1)
    total_paginas = (primera.get("page_info") or {}).get("total_pages") or 0
    print(f"  {primera.get('total_count')} productos en {total_paginas} páginas")

    productos = {}
    for pagina in range(1, total_paginas + 1):
        datos = primera if pagina == 1 else pedir_pagina(pagina)
        items = [i for i in datos.get("items") or [] if i]
        for item in items:
            productos[item["sku"]] = convertir(item)
        print(f"  página {pagina}/{total_paginas}: {len(items)} productos ({len(productos)} únicos)")
        if pagina < total_paginas:
            time.sleep(PAUSA)

    return list(productos.values()), primera.get("total_count")


def main():
    productos, esperados = extraer_profar()

    if not productos:
        print("No se encontraron productos.")
        return
    if esperados and len(productos) < esperados:
        print(f"ATENCION: llegaron {len(productos)} de {esperados} productos")

    DESTINO.mkdir(parents=True, exist_ok=True)
    archivo = DESTINO / f"profar_catalogo_{date.today().isoformat()}.json"

    archivo.write_text(
        json.dumps(
            {
                "fuente": "profar.cl/graphql",
                "categoria_raiz": "medicamentos",
                "fecha_muestreo": date.today().isoformat(),
                "total": len(productos),
                "productos": productos,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\n{len(productos)} productos guardados en: {archivo}")


if __name__ == "__main__":
    main()
