"""
Capa plata (Liga): normaliza el catalogo crudo y lo deja con las mismas
columnas que las demas farmacias, para que la capa oro pueda cruzarlas
sin distinguir el origen.

Entrada:
    data/bronce/liga_catalogo_AAAA-MM-DD.json

Salidas:
    data/plata/liga_productos.csv
    data/plata/liga_precios.csv

Esta fuente es la mas estructurada de todas: publica registro sanitario,
principio activo, concentracion y contenido como campos separados. Lo que
obliga a resolver:

    - El contenido usa abreviaturas ("30 Compr. Lib. Prolongada"). Se
      expanden para reconocer la forma farmaceutica y llevar la unidad
      del envase al mismo vocabulario que las otras farmacias, porque la
      clave de equivalencia incluye el envase.

    - Las combinaciones se declaran con "+" ("LOSARTAN+HIDROCLOROTIAZIDA").
      Se separan con espacio, como en las otras fuentes, para que la capa
      oro no las tome por un principio activo desconocido.

    - Los productos sin registro sanitario (suplementos, dispositivos)
      traen "SR", "DM" u otros valores que no son registros.

    - La bioequivalencia viene como BE / NO / REF / NAP. Los referentes
      se marcan como no bioequivalentes, igual que en el catalogo del ISP.

Uso:
    python normalizar_liga.py
    python normalizar_liga.py liga_catalogo_2026-10-19.json
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

URL_SITIO = "https://ligafarmacia.cl"

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
    "solucion para nebulizacion",
    "suspension inyectable",
    "solucion inyectable",
    "suspension oral",
    "solucion oral",
    "solucion oftalmica",
    "solucion nasal",
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

# Abreviaturas y variantes del campo contenido, en el orden en que se
# aplican. Llevan el texto al vocabulario de FORMAS.
EXPANSIONES = [
    (r"\bcomp(?:r)?\.\s*", "comprimidos "),
    (r"\bcomprimidps\b", "comprimidos"),
    (r"\bcomprimido\b", "comprimidos"),
    (r"\bcaps\.\s*", "capsulas "),
    (r"\bcapsula\b", "capsulas"),
    (r"\blib\.\s*", "liberacion "),
    (r"\brec\.\s*", "recubiertos "),
    (r"\brecubierto\b", "recubiertos"),
    (r"\b(?:buco)?dispersable\b", "dispersables"),
    (r"\bbucodispersables\b", "dispersables"),
    (r"\bsublingual\b", "sublinguales"),
    (r"\befervescente\b", "efervescentes"),
    (r"\bblanda\b", "blandas"),
    (r"\bampolla\b", "ampollas"),
    (r"\bparche\b", "parches"),
    (r"\bsachet\b", "sobres"),
    (r"\bsolucion nebulizacion\b", "solucion para nebulizacion"),
    # Todas las variantes de liberacion modificada son la misma familia
    (r"\bliberacion (?:osmotica )?(?:prolongada|extendida)\b", "de liberacion prolongada"),
    (r"\b(?:lp|retard)\b", "de liberacion prolongada"),
    (r"\bde de\b", "de"),
    (r"\s+", " "),
]

# Unidad del envase, en el vocabulario que usan las demas farmacias
UNIDADES_ENVASE = [
    (r"comprimidos", "comprimidos"),
    (r"capsulas", "capsulas"),
    (r"sobres", "sobres"),
    (r"ampollas", "ampollas"),
    (r"supositorios", "supositorios"),
    (r"ovulos", "ovulos"),
    (r"parches", "parches"),
    (r"grageas", "grageas"),
    (r"ml\b", "ml"),
    (r"(?:gramos|gr|g)\b", "g"),
]

PATRON_ENVASE = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(.*)$")

PATRON_CONCENTRACION = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*"
    r"(mg|g|mcg|µg|UI|%)"
    r"(?:\s*/\s*(\d+(?:[.,]\d+)?)?\s*(mL|ml|g|mg|dosis))?",
    re.IGNORECASE,
)

PATRON_REGISTRO = re.compile(r"^[A-Z]{1,3}-\d+$")

# BE: bioequivalente. NO: no bioequivalente. REF: referente, que el ISP
# no clasifica como bioequivalente. NAP: no aplica (no es medicamento).
BIOEQUIVALENCIA = {"BE": True, "NO": False, "REF": False}


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


def extraer_forma(contenido, nombre):
    # El contenido es la fuente mas confiable; el nombre rara vez la trae
    for texto in (contenido, nombre):
        comparable = expandir(texto)
        for forma in FORMAS:
            if forma in comparable:
                return forma
    return ""


def extraer_envase(contenido):
    """
    "30 Comprimidos" -> ("30", "comprimidos")
    "15 mL Gotas"    -> ("15", "ml")
    "12 Sachet de 10 mL" -> ("12", "sobres")
    """
    m = PATRON_ENVASE.match(expandir(contenido))
    if not m:
        return "", ""

    cantidad, resto = m.group(1).replace(",", "."), m.group(2)
    for patron, unidad in UNIDADES_ENVASE:
        if re.match(patron, resto):
            return cantidad, unidad

    # Unidades propias de pocos productos (inhalador, jeringa, penfill):
    # se conservan tal cual
    palabra = resto.split()[0] if resto else ""
    return cantidad, palabra


def extraer_concentracion(concentracion, nombre):
    for texto in (concentracion, nombre):
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
    """'LOSARTAN+HIDROCLOROTIAZIDA' -> 'HIDROCLOROTIAZIDA LOSARTAN'"""
    partes = [limpiar(p) for p in (texto or "").split("+")]
    return " ".join(sorted(p.upper() for p in partes if p))


def url_producto(kinf2, nombre):
    """Mismo patron con que el sitio arma el enlace a la ficha."""
    slug = re.sub(r"\s+", "-", nombre)
    slug = re.sub(r"[.,%/]", "", slug).lower()
    return f"{URL_SITIO}/product/{kinf2}-{slug}"


def main():
    if len(sys.argv) > 1:
        archivo = ENTRADA / sys.argv[1]
    else:
        candidatos = sorted(ENTRADA.glob("liga_catalogo_*.json"))
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
        nombre = limpiar(p.get("nombre_medicamento"))
        pid = p.get("kinf2")
        if not nombre or not pid:
            continue

        precio_normal = p.get("precio") or None
        precio_oferta = p.get("precio_con_dscto") or precio_normal
        if precio_oferta is None:
            continue

        contenido = limpiar(p.get("contenido"))
        registro = limpiar(p.get("reg_sanitario")).upper()
        principio = extraer_principio(p.get("principio_activo"))
        forma = extraer_forma(contenido, nombre)
        cantidad, unidad = extraer_envase(contenido)
        valor, uni, ref_valor, ref_unidad = extraer_concentracion(
            p.get("concentracion"), nombre
        )
        imagenes = p.get("imagenes") or []

        productos.append(
            {
                "id_producto": pid,
                "sku": p.get("kinfln", ""),
                "nombre_publicado": f"{nombre} {contenido}".strip(),
                "marca": limpiar(p.get("laboratorio")),
                "url_producto": url_producto(pid, nombre),
                "url_imagen": imagenes[0] if imagenes else "",
                "ean": "",
                "registro_declarado": registro,
                # "SR", "DM" y similares no son registros del ISP
                "registro_raiz": registro if PATRON_REGISTRO.match(registro) else "",
                "principio_activo": principio,
                "principio_origen": "campo" if principio else "",
                "forma_farmaceutica": forma,
                "forma_origen": "contenido" if forma else "",
                "concentracion_valor": valor if valor is not None else "",
                "concentracion_unidad": uni,
                "referencia_valor": ref_valor if ref_valor is not None else "",
                "referencia_unidad": ref_unidad,
                "cantidad_envase": cantidad,
                "unidad_envase": unidad,
                "clase_producto": "",
                "bioequivalente_declarado": BIOEQUIVALENCIA.get(
                    p.get("bioequivalente"), ""
                ),
                "bioequivalente_tipo": "",
                "condicion_venta": limpiar(p.get("tipo_venta")),
            }
        )

        precios.append(
            {
                "id_producto": pid,
                "fecha_muestreo": fecha,
                "precio_normal": precio_normal or precio_oferta,
                "precio_oferta": precio_oferta,
                # Sin stock o fuera de la venta online no se puede comprar
                "disponible": bool(p.get("stock")) and bool(p.get("comercio_elec")),
            }
        )

    if not productos:
        print("No se normalizo ningun producto.")
        return

    SALIDA.mkdir(parents=True, exist_ok=True)

    with (SALIDA / "liga_productos.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(productos[0].keys()))
        w.writeheader()
        w.writerows(productos)

    with (SALIDA / "liga_precios.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(precios[0].keys()))
        w.writeheader()
        w.writerows(precios)

    total = len(productos)
    con_reg = sum(1 for x in productos if x["registro_raiz"])
    con_pri = sum(1 for x in productos if x["principio_activo"])
    con_forma = sum(1 for x in productos if x["forma_farmaceutica"])
    con_env = sum(1 for x in productos if x["cantidad_envase"])
    con_conc = sum(1 for x in productos if x["concentracion_valor"] != "")
    disponibles = sum(1 for x in precios if x["disponible"])

    print(f"\n{total} productos normalizados")
    print(f"  registro sanitario: {con_reg:5} ({100*con_reg/total:.1f}%)")
    print(f"  principio activo:   {con_pri:5} ({100*con_pri/total:.1f}%)")
    print(f"  forma:              {con_forma:5} ({100*con_forma/total:.1f}%)")
    print(f"  envase:             {con_env:5} ({100*con_env/total:.1f}%)")
    print(f"  concentracion:      {con_conc:5} ({100*con_conc/total:.1f}%)")
    print(f"\n{len(precios)} precios para {fecha} ({disponibles} disponibles)")
    print(f"\nGuardado en {SALIDA}")


if __name__ == "__main__":
    main()
