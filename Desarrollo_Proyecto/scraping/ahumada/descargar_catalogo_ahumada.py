"""
Capa bronce: descarga el catalogo de medicamentos de Farmacias Ahumada.

El sitio opera sobre Salesforce Commerce Cloud y entrega los datos en el
HTML, sin necesidad de ejecutar JavaScript. Se extrae en dos fases:

    Fase 1 (cada ejecucion)
        Recorre las categorias de medicamentos y obtiene de cada producto
        su identificador, enlace y precios. Unas 90 peticiones.

    Fase 2 (solo productos nuevos)
        Visita la ficha de cada producto para obtener registro sanitario,
        principio activo, concentracion, forma y laboratorio. Estos datos
        no cambian, asi que se guardan en cache y no se vuelven a pedir.

Restricciones que impone el robots.txt del sitio y que se respetan:
    - Prohibe los parametros start, srule, pmin, pmax y pref, que son
      los que usa la paginacion. Se usa solo el parametro sz, que fija
      cuantos productos entrega cada categoria y no esta prohibido.
    - Las categorias se toman del sitemap que el propio sitio publica.

Uso:
    python descargar_catalogo_ahumada.py
    python descargar_catalogo_ahumada.py --diagnostico    una categoria y una ficha
    python descargar_catalogo_ahumada.py --sin-fichas     solo fase 1
"""

import json
import re
import sys
import time
from datetime import date
from pathlib import Path
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

DOMINIO = "https://www.farmaciasahumada.cl"
SITEMAP_CATEGORIAS = f"{DOMINIO}/sitemap_2-category.xml"

RAIZ = Path(__file__).resolve().parents[2]
DESTINO = RAIZ / "data" / "bronce"
CACHE_FICHAS = DESTINO / "ahumada_fichas.json"

PAUSA = 2

# Cantidad de productos que se piden por categoria. Si una categoria
# devuelve exactamente este numero, puede estar truncada y se avisa.
POR_CATEGORIA = 1000

CABECERAS = {
    "User-Agent": "bioEqui-academico/0.1 (proyecto universitario)",
    "Accept": "text/html,application/xml",
    "Accept-Language": "es-CL,es;q=0.9",
}

# Tipos de precio promocional. El precio con tarjeta CMR requiere un medio
# de pago especifico: no es comparable con el precio que cualquier persona
# paga en otra farmacia, asi que se registra aparte.
BADGE_TARJETA = "cmr_falabella"


def pedir(url, params=None):
    r = requests.get(url, params=params, headers=CABECERAS, timeout=30)
    r.raise_for_status()
    return r.text


def categorias_medicamentos():
    """Rutas de las categorias de medicamentos, segun el sitemap."""
    xml = pedir(SITEMAP_CATEGORIAS)
    raiz = ElementTree.fromstring(xml.encode("utf-8"))

    rutas = []
    for loc in raiz.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc"):
        url = (loc.text or "").strip()
        ruta = url.replace(DOMINIO, "")
        # Solo las hojas: /medicamentos/grupo/subcategoria
        if ruta.startswith("/medicamentos/") and ruta.count("/") >= 3:
            rutas.append(ruta)

    return sorted(set(rutas))


def numero(texto):
    """'$1.309' -> 1309"""
    limpio = re.sub(r"[^\d]", "", texto or "")
    return int(limpio) if limpio else None


def leer_tarjeta(tarjeta):
    """Extrae identificador, enlace y precios de una tarjeta del listado."""
    pid = tarjeta.get("data-pid")
    if not pid:
        return None

    interno = tarjeta.select_one("[data-categories]")
    categorias = interno.get("data-categories", "") if interno else ""

    # Enlace a la ficha: termina en -{pid}.html
    url = ""
    for a in tarjeta.select("a[href]"):
        href = a["href"]
        if href.endswith(f"-{pid}.html"):
            url = href if href.startswith("http") else DOMINIO + href
            break

    html = str(tarjeta)

    valores = [
        int(v["content"])
        for v in tarjeta.select(".price span.value[content]")
        if v["content"].isdigit()
    ]
    precio_normal = max(valores) if valores else None

    # El precio promocional va en el contenedor del distintivo
    contenedor = tarjeta.select_one(".promotion-badge-container")
    promo = numero(contenedor.get_text(" ", strip=True).split()[0]) if contenedor else None

    es_tarjeta = BADGE_TARJETA in (str(contenedor) if contenedor else "")

    precio_tarjeta = None
    if es_tarjeta:
        precio_tarjeta = promo
        # Con tarjeta CMR puede haber ademas un precio publico rebajado
        # (el valor intermedio). Si no lo hay, el publico es el normal.
        publicos = sorted(v for v in valores if v != precio_normal)
        precio_oferta = publicos[0] if publicos else precio_normal
    else:
        precio_oferta = promo or precio_normal

    return {
        "pid": pid,
        "url": url,
        "categorias": categorias,
        "precio_normal": precio_normal,
        "precio_oferta": precio_oferta,
        "precio_tarjeta": precio_tarjeta,
        "bioequivalente": "bioequivalent-badge" in html,
        "disponible": 'data-is-unavailable="true"' not in html,
    }


def listar_categoria(ruta):
    html = pedir(DOMINIO + ruta, params={"sz": POR_CATEGORIA})
    sopa = BeautifulSoup(html, "lxml")

    productos = []
    for t in sopa.select("div.product-tile-wrapper[data-pid]"):
        fila = leer_tarjeta(t)
        if fila:
            productos.append(fila)

    return productos


def leer_ficha(html):
    """Extrae los datos estables de la ficha: registro, composicion, etc."""
    sopa = BeautifulSoup(html, "lxml")

    especificaciones = {}
    for th in sopa.find_all("th"):
        td = th.find_next_sibling("td")
        if td:
            clave = th.get_text(strip=True)
            if clave and clave not in especificaciones:
                especificaciones[clave] = td.get_text(" ", strip=True)

    datos = {
        "nombre": "",
        "marca": "",
        "imagen": "",
        "precio_ficha": None,
        "especificaciones": especificaciones,
    }

    # Nombre, marca, imagen y precio vienen en los datos estructurados
    for bloque in sopa.select('script[type="application/ld+json"]'):
        try:
            j = json.loads(bloque.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(j, dict) and j.get("@type") == "Product":
            datos["nombre"] = j.get("name") or ""
            marca = j.get("brand") or {}
            datos["marca"] = marca.get("name", "") if isinstance(marca, dict) else ""
            imagenes = j.get("image") or []
            datos["imagen"] = imagenes[0] if imagenes else ""
            oferta = j.get("offers") or {}
            datos["precio_ficha"] = numero(str(oferta.get("price", "")))
            break

    if not datos["nombre"]:
        h1 = sopa.select_one("h1")
        datos["nombre"] = h1.get_text(strip=True) if h1 else ""

    return datos


def cargar_cache():
    if CACHE_FICHAS.exists():
        return json.loads(CACHE_FICHAS.read_text(encoding="utf-8"))
    return {}


def guardar_cache(cache):
    DESTINO.mkdir(parents=True, exist_ok=True)
    CACHE_FICHAS.write_text(
        json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def diagnostico():
    print("Leyendo sitemap de categorias...")
    rutas = categorias_medicamentos()
    print(f"  {len(rutas)} categorias de medicamentos")
    if not rutas:
        return

    ruta = rutas[0]
    print(f"\nProbando categoria {ruta}")
    productos = listar_categoria(ruta)
    print(f"  {len(productos)} productos")
    for p in productos[:3]:
        print(f"  {p}")

    if productos and productos[0]["url"]:
        print(f"\nProbando ficha {productos[0]['url']}")
        time.sleep(PAUSA)
        ficha = leer_ficha(pedir(productos[0]["url"]))
        print(json.dumps(ficha, ensure_ascii=False, indent=2))


def main():
    if "--diagnostico" in sys.argv:
        diagnostico()
        return

    sin_fichas = "--sin-fichas" in sys.argv

    print("Fase 1: precios por categoria")
    rutas = categorias_medicamentos()
    print(f"  {len(rutas)} categorias de medicamentos\n")

    listado = {}
    for i, ruta in enumerate(rutas, 1):
        try:
            productos = listar_categoria(ruta)
        except requests.RequestException as e:
            print(f"  [{i}/{len(rutas)}] {ruta}: error {e}")
            time.sleep(PAUSA)
            continue

        nuevos = 0
        for p in productos:
            if p["pid"] not in listado:
                listado[p["pid"]] = p
                nuevos += 1

        aviso = "  (puede estar truncada)" if len(productos) >= POR_CATEGORIA else ""
        print(f"  [{i}/{len(rutas)}] {ruta}: {len(productos)} ({nuevos} nuevos){aviso}")
        time.sleep(PAUSA)

    print(f"\n{len(listado)} productos unicos en el listado")

    cache = cargar_cache()

    if not sin_fichas:
        pendientes = [p for pid, p in listado.items() if pid not in cache and p["url"]]
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

    archivo = DESTINO / f"ahumada_catalogo_{date.today().isoformat()}.json"
    archivo.write_text(
        json.dumps(
            {
                "fuente": "farmaciasahumada.cl",
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
        print(f"  {sin_ficha} sin ficha: quedaran sin registro sanitario")


if __name__ == "__main__":
    main()
