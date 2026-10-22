"""
Capa plata (Novasalud): normaliza el catalogo crudo y lo deja con las
mismas columnas que las demas farmacias, para que la capa oro pueda
cruzarlas sin distinguir el origen.

Entrada:
    data/bronce/novasalud_catalogo_AAAA-MM-DD.json

Salidas:
    data/plata/novasalud_productos.csv
    data/plata/novasalud_precios.csv

Lo que esta fuente obliga a resolver:

    - No publica registro sanitario. La comparacion se hace por clave de
      equivalencia, como en Cruz Verde. A diferencia de Cruz Verde, el
      principio activo, la forma y la dosis vienen como campos de la ficha.

    - El nombre visible esta escrito para buscadores ("Aciclovir 200mg -
      24 Comprimidos para tu salud") y a veces no coincide con el producto
      real. El envase se toma de la URL, que es mas fiel, y se contrasta
      con el precio fraccionado: precio / precio por unidad = unidades.

    - No declara bioequivalencia por producto. Su seccion /bioequivalentes
      mezcla bioequivalentes con genericos, asi que no sirve para marcarlos.

Uso:
    python normalizar_novasalud.py
    python normalizar_novasalud.py novasalud_catalogo_2026-10-20.json
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
    "capsulas blandas",
    "frasco ampolla",
    "comprimidos",
    "capsulas",
    "supositorios",
    "ampollas",
    "ovulos",
    "grageas",
    "jarabe",
    "unguento",
    "crema",
    "parches",
    "aerosol",
    "sobres",
    "gotas",
    "polvo",
    "gel",
]

# Variantes de escritura que se llevan al vocabulario de FORMAS
EXPANSIONES = [
    (r"\bcomprimido\b", "comprimidos"),
    (r"\bcapsula\b", "capsulas"),
    (r"\brecubierto\b", "recubiertos"),
    (r"\b(?:buco)?dispersables?\b", "dispersables"),
    (r"\bmasticable\b", "masticables"),
    (r"\bsublingual\b", "sublinguales"),
    (r"\befervescente\b", "efervescentes"),
    (r"\bblanda\b", "blandas"),
    (r"\bampolla\b", "ampollas"),
    (r"\bparche\b", "parches"),
    (r"\bsobre\b", "sobres"),
    (r"\bovulo\b", "ovulos"),
    (r"\bsupositorio\b", "supositorios"),
    (r"\bliberacion (?:osmotica )?(?:prolongada|extendida|modificada)\b", "de liberacion prolongada"),
    (r"\bde de\b", "de"),
    (r"\s+", " "),
]

# Unidades que denotan tamanio de envase, en el vocabulario que usan las
# demas farmacias. La clave de equivalencia incluye el envase.
CONTABLES = {
    "comprimidos": "comprimidos",
    "comprimido": "comprimidos",
    "capsulas": "capsulas",
    "capsula": "capsulas",
    "sobres": "sobres",
    "sobre": "sobres",
    "ampollas": "ampollas",
    "ampolla": "ampollas",
    "supositorios": "supositorios",
    "ovulos": "ovulos",
    "parches": "parches",
    "grageas": "grageas",
}

PATRON_UNIDADES = re.compile(r"\b(\d+)\s+(" + "|".join(CONTABLES) + r")\b")
PATRON_VOLUMEN = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*(ml|gr|g)\b")

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


def expandir(texto):
    t = sin_tildes(texto)
    for patron, reemplazo in EXPANSIONES:
        t = re.sub(patron, reemplazo, t)
    return t.strip()


def texto_url(url):
    """'.../aciclovir-200mg-25-comprimidos' -> 'aciclovir 200mg 25 comprimidos'"""
    return url.rstrip("/").rsplit("/", 1)[-1].replace(".html", "").replace("-", " ")


def numero(texto):
    digitos = re.sub(r"[^\d]", "", texto or "")
    return int(digitos) if digitos else None


def campo(atributos, inicio):
    """
    Busca una fila de la ficha por el inicio de su nombre, sin tildes ni
    mayusculas: el sitio escribe "Farmaceútica" en unas fichas y
    "Farmacéutica" en otras.
    """
    for nombre, valor in atributos.items():
        if sin_tildes(nombre).startswith(inicio):
            return valor
    return ""


def extraer_forma(*textos):
    for texto in textos:
        comparable = expandir(texto)
        for forma in FORMAS:
            if forma in comparable:
                return forma
    return ""


def extraer_envase(texto_producto, precio, fraccionado):
    """
    Devuelve cantidad y unidad del envase.

    Para los productos que se venden por unidades se contrasta con el
    precio fraccionado. Si el cociente da un entero distinto al del texto,
    manda el cociente: es el que usa la farmacia para cobrar.
    """
    texto = sin_tildes(texto_producto)

    m = PATRON_UNIDADES.search(texto)
    if m:
        cantidad, unidad = int(m.group(1)), CONTABLES[m.group(2)]
        if precio and fraccionado and fraccionado < precio:
            unidades = precio / fraccionado
            if abs(unidades - round(unidades)) < 0.05 and round(unidades) > 1:
                cantidad = round(unidades)
        return str(cantidad), unidad

    # El envase va al final del texto y la concentracion al principio,
    # por eso ante varios volumenes se toma el ultimo
    volumenes = PATRON_VOLUMEN.findall(texto)
    if volumenes:
        valor, unidad = volumenes[-1]
        return valor.replace(",", "."), "g" if unidad == "gr" else unidad

    return "", ""


def extraer_concentracion(*textos):
    for texto in textos:
        m = PATRON_CONCENTRACION.search(texto or "")
        if m:
            break
    else:
        return None, "", None, ""

    valor = float(m.group(1).replace(",", "."))
    unidad = m.group(2).lower()

    ref_valor = None
    ref_unidad = m.group(4) or ""
    if ref_unidad:
        ref_valor = float(m.group(3).replace(",", ".")) if m.group(3) else 1.0

    return valor, unidad, ref_valor, ref_unidad.lower()


def extraer_principio(texto):
    """
    'Losartan Potasico + Hidroclorotiazida' -> 'HIDROCLOROTIAZIDA LOSARTAN POTASICO'

    Se deja sin tildes y en mayusculas, y las combinaciones separadas por
    espacio, como en las otras fuentes.
    """
    partes = re.split(r"\s*[+/;,]\s*", sin_tildes(texto))
    return " ".join(sorted(p.upper() for p in partes if p))


def main():
    if len(sys.argv) > 1:
        archivo = ENTRADA / sys.argv[1]
    else:
        candidatos = sorted(ENTRADA.glob("novasalud_catalogo_*.json"))
        if not candidatos:
            print(f"No se encontro ningun catalogo en {ENTRADA}")
            return
        archivo = candidatos[-1]

    print(f"Leyendo {archivo.name}")
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    fecha = datos.get("fecha_muestreo", "")

    productos = []
    precios = []

    for p in datos.get("productos", []):
        pid = p.get("pid")
        ficha = p.get("ficha") or {}
        atributos = ficha.get("atributos") or {}
        nombre = limpiar(ficha.get("titulo") or p.get("nombre"))
        if not pid or not nombre:
            continue

        precio_oferta = p.get("precio_final")
        if precio_oferta is None:
            continue
        precio_normal = p.get("precio_normal") or precio_oferta

        url = ficha.get("url_canonica") or p.get("url", "")
        descripcion = texto_url(url)

        principio = extraer_principio(campo(atributos, "principio activo"))
        forma = extraer_forma(campo(atributos, "forma farmac"))
        forma_origen = "campo" if forma else ""
        if not forma:
            forma = extraer_forma(descripcion, nombre)
            forma_origen = "nombre" if forma else ""

        cantidad, unidad = extraer_envase(
            descripcion,
            precio_oferta,
            numero(campo(atributos, "precio fraccionado")),
        )
        valor, uni, ref_valor, ref_unidad = extraer_concentracion(
            campo(atributos, "dosis"), nombre
        )

        productos.append(
            {
                "id_producto": pid,
                "sku": p.get("sku", ""),
                "nombre_publicado": nombre,
                "marca": limpiar(campo(atributos, "laboratorio")),
                "url_producto": url,
                "url_imagen": p.get("url_imagen", ""),
                "ean": "",
                # Esta fuente no publica registro sanitario
                "registro_declarado": "",
                "registro_raiz": "",
                "principio_activo": principio,
                "principio_origen": "campo" if principio else "",
                "forma_farmaceutica": forma,
                "forma_origen": forma_origen,
                "concentracion_valor": valor if valor is not None else "",
                "concentracion_unidad": uni,
                "referencia_valor": ref_valor if ref_valor is not None else "",
                "referencia_unidad": ref_unidad,
                "cantidad_envase": cantidad,
                "unidad_envase": unidad,
                "clase_producto": "",
                "bioequivalente_declarado": "",
                "bioequivalente_tipo": "",
                "condicion_venta": limpiar(campo(atributos, "condicion de venta")),
            }
        )

        precios.append(
            {
                "id_producto": pid,
                "fecha_muestreo": fecha,
                "precio_normal": precio_normal,
                "precio_oferta": precio_oferta,
                "disponible": p.get("disponible", ""),
            }
        )

    if not productos:
        print("No se normalizo ningun producto.")
        return

    SALIDA.mkdir(parents=True, exist_ok=True)

    with (SALIDA / "novasalud_productos.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(productos[0].keys()))
        w.writeheader()
        w.writerows(productos)

    with (SALIDA / "novasalud_precios.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(precios[0].keys()))
        w.writeheader()
        w.writerows(precios)

    total = len(productos)
    con_pri = sum(1 for x in productos if x["principio_activo"])
    con_forma = sum(1 for x in productos if x["forma_farmaceutica"])
    con_env = sum(1 for x in productos if x["cantidad_envase"])
    con_conc = sum(1 for x in productos if x["concentracion_valor"] != "")
    disponibles = sum(1 for x in precios if x["disponible"])

    print(f"\n{total} productos normalizados")
    print(f"  principio activo:  {con_pri:5} ({100*con_pri/total:.1f}%)")
    print(f"  forma:             {con_forma:5} ({100*con_forma/total:.1f}%)")
    print(f"  envase:            {con_env:5} ({100*con_env/total:.1f}%)")
    print(f"  concentracion:     {con_conc:5} ({100*con_conc/total:.1f}%)")
    print(f"\n{len(precios)} precios para {fecha} ({disponibles} disponibles)")
    print(f"\nGuardado en {SALIDA}")


if __name__ == "__main__":
    main()
