"""
Capa plata (Dr. Simi): normaliza el catalogo crudo extraido del sitio
comercial y lo deja listo para cruzar con el catalogo del ISP.

Entrada:
    data/bronce/drsimi_catalogo_AAAA-MM-DD.json

Salidas:
    data/plata/drsimi_productos.csv   un producto por fila
    data/plata/drsimi_precios.csv     un precio por producto y fecha

Transformaciones aplicadas:
    - Extrae los campos POR NOMBRE, nunca por posicion: las fichas del
      sitio traen distinta cantidad de campos y en distinto orden
    - Limpia el marcado HTML embebido en los valores de texto
    - Separa el tipo de producto en sus dos dimensiones
    - Unifica cantidad y volumen de envase en un solo par de campos
    - Rellena principio activo y forma farmaceutica desde el nombre
      cuando el campo estructurado viene vacio
    - Deriva el registro sin sufijo de anio para permitir el cruce

Uso:
    python normalizar_drsimi.py
    python normalizar_drsimi.py drsimi_catalogo_2026-09-07.json
"""

import csv
import html
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
    "polvo para solucion oral",
    "polvo para suspension oral",
    "solucion para gotas orales",
    "solucion para nebulizacion",
    "solucion inyectable",
    "suspension inyectable",
    "suspension oral",
    "solucion oral",
    "solucion oftalmica",
    "solucion topica",
    "solucion nasal",
    "solucion otica",
    "capsulas blandas",
    "frasco ampolla",
    "capsulas",
    "comprimidos",
    "supositorios",
    "ampollas",
    "ovulos",
    "grageas",
    "jarabe",
    "crema",
    "unguento",
    "parches",
    "aerosol",
    "obleas",
    "polvo",
    "gotas",
    "sobres",
    "gel",
]

PATRON_CONCENTRACION = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*"
    r"(mg|g|mcg|µg|UI|%)"
    r"(?:\s*/\s*(\d+(?:[.,]\d+)?)?\s*(mL|ml|g|mg|dosis))?",
    re.IGNORECASE,
)


def limpiar(texto):
    """Decodifica entidades, quita etiquetas HTML y normaliza espacios."""
    if not texto:
        return ""
    t = html.unescape(str(texto))
    t = re.sub(r"<[^>]+>", " ", t)
    t = t.replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


def sin_tildes(texto):
    n = unicodedata.normalize("NFD", texto)
    return "".join(c for c in n if unicodedata.category(c) != "Mn").lower()


def campo(producto, nombre):
    """
    Lee un campo del producto por su nombre.

    El sitio entrega las propiedades como listas de un elemento, y no todas
    las fichas traen los mismos campos, por eso todo acceso es tolerante.
    """
    valor = producto.get(nombre)
    if isinstance(valor, list):
        valor = valor[0] if valor else None
    return limpiar(valor)


def separar_tipo(tipo):
    """
    El campo de tipo combina dos dimensiones independientes.

    "GENERICO BIOEQUIVALENTE" -> ("generico", True)
    "MARCA NO BIOEQUIVALENTE" -> ("marca", False)
    """
    if not tipo:
        return "", ""

    t = sin_tildes(tipo)

    if "combinacion" in t:
        clase = "combinacion"
    elif "generico" in t:
        clase = "generico"
    elif "marca" in t:
        clase = "marca"
    else:
        clase = ""

    # El orden importa: "no bioequivalente" contiene "bioequivalente"
    if "no bioequivalente" in t:
        bio = False
    elif "bioequivalente" in t:
        bio = True
    else:
        bio = ""

    return clase, bio


def extraer_forma(nombre):
    comparable = sin_tildes(nombre)
    for forma in FORMAS:
        if forma in comparable:
            return forma
    return ""

def cargar_vocabulario():
    """
    Principios activos del ISP, para reconocerlos dentro del nombre
    cuando la ficha no publica el campo. Es la misma nomenclatura que
    usa el normalizador de las demas farmacias.
    """
    ruta = SALIDA / "isp_composicion.csv"
    if not ruta.exists():
        return set()

    vocabulario = set()
    with ruta.open(encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            p = sin_tildes(fila["principio_activo"])
            # Los muy cortos generan falsos positivos dentro de otras palabras
            if len(p) > 5:
                vocabulario.add(p)
    return vocabulario


def extraer_principio(nombre, vocabulario):
    """Identifica los principios activos mencionados en el nombre."""
    texto = sin_tildes(nombre)
    hallados = [
        p for p in vocabulario
        if re.search(r"\b" + re.escape(p) + r"\b", texto)
    ]
    if not hallados:
        return []

    # Descartar los contenidos en otro mas largo: "tretinoina" esta
    # dentro de "isotretinoina" y solo el segundo es el principio real
    resultado = []
    for p in sorted(hallados, key=len, reverse=True):
        if not any(p in otro for otro in resultado):
            resultado.append(p)
    return sorted(resultado)


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


def envase(producto):
    """
    Unifica los dos campos de envase. Los productos solidos declaran
    cantidad de unidades y los liquidos volumen total: son la misma
    propiedad bajo nombres distintos.
    """
    cantidad = campo(producto, "Cantidad por envase")
    if cantidad:
        forma = campo(producto, "Forma farmaceutica") or campo(
            producto, "Forma farmacéutica"
        )
        return cantidad, forma or "unidades"

    volumen = campo(producto, "Volumen total por envase")
    if volumen:
        return volumen, campo(producto, "Unidad de medida por envase")

    return "", ""


def oferta(producto):
    """Precio, disponibilidad e imagen viven dentro del primer item."""
    items = producto.get("items") or []
    if not items:
        return {}

    item = items[0]
    vendedores = item.get("sellers") or []
    comercial = vendedores[0].get("commertialOffer", {}) if vendedores else {}

    imagenes = item.get("images") or []

    return {
        "sku": item.get("itemId", ""),
        "ean": item.get("ean", ""),
        "url_imagen": imagenes[0].get("imageUrl", "") if imagenes else "",
        "precio_oferta": comercial.get("Price"),
        "precio_normal": comercial.get("ListPrice"),
        "disponible": comercial.get("IsAvailable"),
    }


def main():
    if len(sys.argv) > 1:
        archivo = ENTRADA / sys.argv[1]
    else:
        candidatos = sorted(ENTRADA.glob("drsimi_catalogo_*.json"))
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
        registro = campo(p, "Registro Sanitario")
        clase, bio_tipo = separar_tipo(campo(p, "Tipo de Producto"))

        # El campo booleano y el de tipo pueden discrepar entre si
        bio_campo = campo(p, "Bioequivalente").upper()
        bio_declarado = True if bio_campo == "SI" else (False if bio_campo == "NO" else "")

        forma = campo(p, "Forma farmaceutica") or campo(p, "Forma farmacéutica")
        forma_origen = "campo"
        if not forma:
            forma = extraer_forma(nombre)
            forma_origen = "nombre" if forma else ""

        principio = campo(p, "Principio Activo")
        principio_origen = "campo" if principio else ""
        # Cuando la ficha no lo trae, se identifica en el nombre con el
        # vocabulario oficial. Sin esto el producto queda sin clave de
        # equivalencia y fuera de toda comparacion.
        if not principio and vocabulario:
            hallados = extraer_principio(nombre, vocabulario)
            if hallados:
                principio = " ".join(hallados).upper()
                principio_origen = "nombre"

        cantidad, unidad = envase(p)
        valor, uni, ref_valor, ref_unidad = extraer_concentracion(nombre)
        o = oferta(p)

        productos.append(
            {
                "id_producto": p.get("productId", ""),
                "sku": o.get("sku", ""),
                "nombre_publicado": nombre,
                "marca": limpiar(p.get("brand")),
                "url_producto": p.get("link", ""),
                "url_imagen": o.get("url_imagen", ""),
                "ean": o.get("ean", "") or campo(p, "EANCode"),
                "registro_declarado": registro,
                "registro_raiz": registro.split("/")[0].strip().upper(),
                "principio_activo": principio,
                "principio_origen": principio_origen,
                "forma_farmaceutica": forma,
                "forma_origen": forma_origen,
                "concentracion_valor": valor if valor is not None else "",
                "concentracion_unidad": uni,
                "referencia_valor": ref_valor if ref_valor is not None else "",
                "referencia_unidad": ref_unidad,
                "cantidad_envase": cantidad,
                "unidad_envase": unidad,
                "clase_producto": clase,
                "bioequivalente_declarado": bio_declarado,
                "bioequivalente_tipo": bio_tipo,
                "condicion_venta": campo(p, "Condición de Venta")
                or campo(p, "Condicion de Venta"),
            }
        )

        if o.get("precio_oferta") is not None:
            precios.append(
                {
                    "id_producto": p.get("productId", ""),
                    "fecha_muestreo": fecha,
                    "precio_normal": o.get("precio_normal"),
                    "precio_oferta": o.get("precio_oferta"),
                    "disponible": o.get("disponible"),
                }
            )

    SALIDA.mkdir(parents=True, exist_ok=True)

    ruta_prod = SALIDA / "drsimi_productos.csv"
    with ruta_prod.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(productos[0].keys()))
        w.writeheader()
        w.writerows(productos)

    ruta_pre = SALIDA / "drsimi_precios.csv"
    with ruta_pre.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(precios[0].keys()))
        w.writeheader()
        w.writerows(precios)

    total = len(productos)
    con_reg = sum(1 for x in productos if x["registro_raiz"])
    pri_campo = sum(1 for x in productos if x["principio_origen"] == "campo")
    for_campo = sum(1 for x in productos if x["forma_origen"] == "campo")
    for_nombre = sum(1 for x in productos if x["forma_origen"] == "nombre")
    con_env = sum(1 for x in productos if x["cantidad_envase"])
    con_conc = sum(1 for x in productos if x["concentracion_valor"] != "")

    print(f"\n{total} productos normalizados")
    print(f"  con registro sanitario:  {con_reg} ({100*con_reg/total:.1f}%)")
    print(f"  principio activo:        {pri_campo} desde campo")
    print(f"  forma farmaceutica:      {for_campo} desde campo, "
          f"{for_nombre} recuperadas del nombre")
    print(f"  con envase:              {con_env} ({100*con_env/total:.1f}%)")
    print(f"  con concentracion:       {con_conc} ({100*con_conc/total:.1f}%)")
    print(f"\n{len(precios)} precios registrados para {fecha}")
    print(f"\nGuardado en {SALIDA}")


if __name__ == "__main__":
    main()