"""
Capa plata (Cruz Verde): normaliza el catalogo crudo y lo deja con las
mismas columnas que las demas farmacias, para que la capa oro pueda
cruzarlas sin distinguir el origen.

Entrada:
    data/bronce/cruzverde_catalogo_AAAA-MM-DD.json

Salidas:
    data/plata/cruzverde_productos.csv
    data/plata/cruzverde_precios.csv

Diferencias con Dr. Simi que esta fuente obliga a resolver:

    - No publica registro sanitario. Los productos no pueden vincularse
      al catalogo del ISP por registro; la comparacion se hace por clave
      de equivalencia, derivada del nombre.

    - No publica principio activo como campo. Se extrae del nombre.

    - Devuelve pdpUrl solo en una fraccion minima de los productos, pero
      el patron del enlace es deducible a partir del nombre y el id.

Uso:
    python normalizar_cruzverde.py
    python normalizar_cruzverde.py cruzverde_catalogo_2026-09-08.json
"""

import csv
import json
import re
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
ENTRADA = RAIZ / "data" / "bronce"
SALIDA = RAIZ / "data" / "plata"

# Formas farmaceuticas reconocidas, de la mas especifica a la mas general
FORMAS = [
    "comprimidos recubiertos de liberacion prolongada",
    "comprimidos recubiertos de liberacion modificada",
    "comprimidos con recubrimiento enterico",
    "comprimidos de liberacion prolongada",
    "capsulas de liberacion prolongada",
    "comprimidos recubiertos",
    "comprimidos dispersables",
    "comprimidos masticables",
    "comprimidos sublinguales",
    "comprimidos efervescentes",
    "polvo para suspension oral",
    "polvo para solucion oral",
    "solucion para gotas orales",
    "solucion para nebulizacion",
    "suspension inyectable",
    "solucion inyectable",
    "suspension oral",
    "solucion oral",
    "solucion oftalmica",
    "solucion nasal",
    "solucion otica",
    "solucion topica",
    "gel topico",
    "capsulas blandas",
    "frasco ampolla",
    "comprimidos",
    "comprimido",
    "capsulas",
    "capsula",
    "supositorios",
    "ampollas",
    "ovulos",
    "grageas",
    "jarabe",
    "unguento",
    "pomada",
    "crema",
    "parches",
    "aerosol",
    "sobres",
    "sobre",
    "gotas",
    "polvo",
    "gel",
]

# Unidades que denotan tamanio de envase, no concentracion
ENVASE_CONTABLE = (
    r"(comprimidos|comprimido|capsulas|capsula|sobres|sobre|supositorios|"
    r"ovulos|ampollas|grageas|parches|obleas|tabletas|baterias)"
)

PATRON_UNIDADES = re.compile(r"\b(\d+)\s+" + ENVASE_CONTABLE)
PATRON_VOLUMEN = re.compile(r"(\d+(?:[.,]\d+)?)\s*(ml|l|gr|g)\b")
PATRON_RAZON = re.compile(r"/\s*\d+(?:[.,]\d+)?\s*(ml|l|g)\b")

PATRON_CONCENTRACION = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*"
    r"(mg|g|mcg|µg|UI|%)"
    r"(?:\s*/\s*(\d+(?:[.,]\d+)?)?\s*(mL|ml|g|mg|dosis))?",
    re.IGNORECASE,
)


def sin_tildes(texto):
    n = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in n if unicodedata.category(c) != "Mn").strip()


def limpiar(texto):
    return re.sub(r"\s+", " ", (texto or "").replace("\xa0", " ")).strip()


def url_producto(nombre, product_id):
    """
    Reconstruye el enlace a la ficha.

    La API devuelve pdpUrl solo en una fraccion minima de los productos,
    pero el patron es deducible: el nombre normalizado como slug seguido
    del identificador. Se verifico contra los casos que si lo traen.
    """
    n = sin_tildes(nombre).replace(" ", "-")
    n = re.sub(r"[^a-z0-9%\-]", "", n)
    n = re.sub(r"-+", "-", n).strip("-")
    return f"https://www.cruzverde.cl//{n}/{product_id}.html"


def extraer_forma(nombre):
    comparable = sin_tildes(nombre)
    for forma in FORMAS:
        if forma in comparable:
            return forma
    return ""


def extraer_concentracion(nombre):
    m = PATRON_CONCENTRACION.search(nombre)
    if not m:
        return None, "", None, ""

    valor = float(m.group(1).replace(",", "."))
    unidad = m.group(2).lower()

    ref_valor = None
    ref_unidad = m.group(4) or ""
    if ref_unidad:
        ref_valor = float(m.group(3).replace(",", ".")) if m.group(3) else 1.0

    return valor, unidad, ref_valor, ref_unidad.lower()


def extraer_envase(nombre):
    """
    Extrae el tamanio del envase. Devuelve cantidad y unidad.

    El envase aparece al final del nombre y la concentracion al principio,
    por eso ante varias coincidencias de volumen se toma la ultima.
    """
    texto = sin_tildes(nombre)

    m = PATRON_UNIDADES.search(texto)
    if m:
        return m.group(1), m.group(2)

    limpio = PATRON_RAZON.sub("/ REF", texto)
    coincidencias = PATRON_VOLUMEN.findall(limpio)
    if coincidencias:
        valor, unidad = coincidencias[-1]
        return valor.replace(",", "."), "g" if unidad == "gr" else unidad

    return "", ""


def extraer_principio(nombre, vocabulario):
    """
    Cruz Verde no publica el principio activo como campo. Se identifica
    dentro del nombre usando el vocabulario oficial del ISP, que es la
    nomenclatura de referencia.
    """
    texto = sin_tildes(nombre)
    hallados = [p for p in vocabulario if p in texto]
    if not hallados:
        return []

    # Descartar los contenidos en otro mas largo: "acido acetilsalicilico"
    # contiene "acido", y solo el primero es el principio activo real
    resultado = []
    for p in sorted(hallados, key=len, reverse=True):
        if not any(p in otro for otro in resultado):
            resultado.append(p)

    return sorted(resultado)


def cargar_vocabulario():
    """Principios activos del ISP, para reconocerlos dentro del nombre."""
    ruta = SALIDA / "isp_composicion.csv"
    if not ruta.exists():
        raise SystemExit(
            f"Falta {ruta}.\nEjecuta primero normalizacion_isp.py: el "
            "vocabulario de principios activos sale de ahi."
        )

    vocabulario = set()
    with ruta.open(encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            p = sin_tildes(fila["principio_activo"])
            # Los muy cortos generan falsos positivos dentro de otras palabras
            if len(p) > 5:
                vocabulario.add(p)

    return vocabulario


def main():
    if len(sys.argv) > 1:
        archivo = ENTRADA / sys.argv[1]
    else:
        candidatos = sorted(ENTRADA.glob("cruzverde_catalogo_*.json"))
        if not candidatos:
            print(f"No se encontro ningun catalogo en {ENTRADA}")
            return
        archivo = candidatos[-1]

    print(f"Leyendo {archivo.name}")
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    fecha = datos.get("fecha_muestreo", "")

    vocabulario = cargar_vocabulario()
    print(f"Vocabulario del ISP: {len(vocabulario)} principios activos")

    productos = []
    precios = []

    for p in datos.get("productos", []):
        nombre = limpiar(p.get("productName"))
        pid = p.get("productId")
        if not nombre or not pid:
            continue

        precio = p.get("prices") or {}
        precio_oferta = precio.get("price-sale-cl")
        precio_normal = precio.get("price-list-cl") or p.get("mrp")

        # Sin precio de venta el producto no aporta a la comparacion
        if precio_oferta is None and precio_normal is None:
            continue
        if precio_oferta is None:
            precio_oferta = precio_normal
        if precio_normal is None:
            precio_normal = precio_oferta

        principios = extraer_principio(nombre, vocabulario)
        forma = extraer_forma(nombre)
        cantidad, unidad = extraer_envase(nombre)
        valor, uni, ref_valor, ref_unidad = extraer_concentracion(nombre)

        bio = p.get("isBioequivalent")
        stock = p.get("stock")

        productos.append(
            {
                "id_producto": str(pid),
                "sku": str(pid),
                "nombre_publicado": nombre,
                "marca": limpiar(p.get("productBrand")),
                "url_producto": p.get("pdpUrl") or url_producto(nombre, pid),
                "url_imagen": p.get("imageUrl") or "",
                "ean": "",
                # Esta fuente no publica registro sanitario: la vinculacion
                # al ISP no es posible por esa via
                "registro_declarado": "",
                "registro_raiz": "",
                "principio_activo": " ".join(principios).upper(),
                "principio_origen": "nombre" if principios else "",
                "forma_farmaceutica": forma,
                "forma_origen": "nombre" if forma else "",
                "concentracion_valor": valor if valor is not None else "",
                "concentracion_unidad": uni,
                "referencia_valor": ref_valor if ref_valor is not None else "",
                "referencia_unidad": ref_unidad,
                "cantidad_envase": cantidad,
                "unidad_envase": unidad,
                "clase_producto": "",
                "bioequivalente_declarado": bool(bio) if bio is not None else "",
                "bioequivalente_tipo": "",
                "condicion_venta": "",
            }
        )

        precios.append(
            {
                "id_producto": str(pid),
                "fecha_muestreo": fecha,
                "precio_normal": precio_normal,
                "precio_oferta": precio_oferta,
                "disponible": bool(stock) if stock is not None else "",
            }
        )

    if not productos:
        print("No se normalizo ningun producto.")
        return

    SALIDA.mkdir(parents=True, exist_ok=True)

    with (SALIDA / "cruzverde_productos.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        w = csv.DictWriter(f, fieldnames=list(productos[0].keys()))
        w.writeheader()
        w.writerows(productos)

    with (SALIDA / "cruzverde_precios.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        w = csv.DictWriter(f, fieldnames=list(precios[0].keys()))
        w.writeheader()
        w.writerows(precios)

    total = len(productos)
    con_pri = sum(1 for x in productos if x["principio_activo"])
    con_forma = sum(1 for x in productos if x["forma_farmaceutica"])
    con_env = sum(1 for x in productos if x["cantidad_envase"])
    con_conc = sum(1 for x in productos if x["concentracion_valor"] != "")
    comparables = sum(
        1
        for x in productos
        if x["principio_activo"] and x["forma_farmaceutica"] and x["concentracion_valor"] != ""
    )

    print(f"\n{total} productos normalizados")
    print(f"  principio activo:  {con_pri:5} ({100*con_pri/total:.1f}%)")
    print(f"  forma:             {con_forma:5} ({100*con_forma/total:.1f}%)")
    print(f"  envase:            {con_env:5} ({100*con_env/total:.1f}%)")
    print(f"  concentracion:     {con_conc:5} ({100*con_conc/total:.1f}%)")
    print(f"  con los tres:      {comparables:5} ({100*comparables/total:.1f}%)")
    print(f"\n{len(precios)} precios para {fecha}")
    print(f"\nGuardado en {SALIDA}")


if __name__ == "__main__":
    main()
