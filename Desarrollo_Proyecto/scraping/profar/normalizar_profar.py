"""
Capa plata (Profar): normaliza el catálogo extraído y lo deja con las
mismas columnas que las demás farmacias.

El principio activo se obtiene, en este orden:
    1. Por el registro ISP que publica Profar: los principios oficiales de
       ese registro (data/plata/isp_composicion.csv).
    2. Por el campo "Principio Activo" de la ficha de Profar.
    3. Reconociendo dentro del nombre un principio activo del vocabulario
       oficial del ISP, por palabra completa (igual que Cruz Verde).
Si ninguno funciona, el producto queda sin principio y no se compara: es
preferible no comparar a comparar productos distintos.

Como toda la capa plata, lee de bronce y de la plata del ISP; no depende de
la base de datos.
"""

import csv
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
ENTRADA = RAIZ / "data" / "bronce"
SALIDA = RAIZ / "data" / "plata"

FORMAS = [
    "comprimidos recubiertos de liberacion prolongada", "comprimidos con recubrimiento enterico",
    "comprimidos de liberacion prolongada", "capsulas de liberacion prolongada",
    "comprimidos recubiertos", "comprimidos dispersables", "comprimidos masticables",
    "comprimidos sublinguales", "comprimidos efervescentes", "polvo para suspension oral",
    "polvo para solucion oral", "solucion para gotas orales", "solucion para nebulizacion",
    "suspension inyectable", "solucion inyectable", "suspension oral", "solucion oral",
    "solucion oftalmica", "solucion nasal", "solucion otica", "solucion topica",
    "capsulas blandas", "frasco ampolla", "comprimidos", "capsulas", "supositorios",
    "ampollas", "ovulos", "grageas", "jarabe", "unguento", "crema", "parches",
    "aerosol", "sobres", "gotas", "polvo", "gel",
]

PATRON_CONCENTRACION = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(mg|g|mcg|µg|UI|%)(?:\s*/\s*(\d+(?:[.,]\d+)?)?\s*(mL|ml|g|mg|dosis))?",
    re.IGNORECASE,
)

ENVASE_CONTABLE = r"(comprimidos|comprimido|comp|capsulas|capsula|sobres|sobre|supositorios|ovulos|ampollas|grageas|parches|tabletas)"
PATRON_UNIDADES = re.compile(r"\bx?\s*(\d+)\s+" + ENVASE_CONTABLE)

def sin_tildes(texto):
    n = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in n if unicodedata.category(c) != "Mn").strip()

def limpiar(texto):
    return re.sub(r"\s+", " ", (texto or "").replace("\xa0", " ")).strip()

def extraer_forma(texto):
    comparable = sin_tildes(texto)
    for forma in FORMAS:
        if forma in comparable:
            return forma
    return ""

def extraer_concentracion(texto):
    m = PATRON_CONCENTRACION.search(texto or "")
    if not m: return None, "", None, ""
    valor = float(m.group(1).replace(",", "."))
    unidad = m.group(2).lower()
    ref_valor = None
    ref_unidad = m.group(4) or ""
    if ref_unidad: ref_valor = float(m.group(3).replace(",", ".")) if m.group(3) else 1.0
    return valor, unidad, ref_valor, ref_unidad.lower()

# Profar abrevia la forma en el nombre ("X 30 COMP. REC.", "X 60 CAPS.").
# Se expande antes de buscar forma y envase, porque la capa oro solo
# reconoce las formas escritas completas
EXPANSIONES = [
    (r"\bcomp\.?\s*rec\.?\s*lib\.?\s*prol\.?", "comprimidos recubiertos de liberacion prolongada"),
    (r"\bcomp\.?\s*lib\.?\s*prol\.?", "comprimidos de liberacion prolongada"),
    (r"\bcomp\.?\s*rec\.?", "comprimidos recubiertos"),
    (r"\bcomp\.?\s*disp\.?", "comprimidos dispersables"),
    (r"\bcomp\.?\s*mast\.?", "comprimidos masticables"),
    (r"\bcomp\.?\s*efer\w*\.?", "comprimidos efervescentes"),
    (r"\bcomp\b\.?", "comprimidos"),
    (r"\bcaps\.?\s*bland\w*\.?", "capsulas blandas"),
    (r"\bcaps\b\.?", "capsulas"),
    (r"\btabletas?\b", "comprimidos"),
    (r"\bsusp\.?\s*oral\b", "suspension oral"),
    (r"\bsol\.?\s*oral\b", "solucion oral"),
    (r"\bsol\.?\s*iny\w*\.?", "solucion inyectable"),
    (r"\bsol\.?\s*oft\w*\.?", "solucion oftalmica"),
    (r"\bsupos?\.?\b", "supositorios"),
]

# Forma que entrega la API cuando el nombre no la trae
FORMAS_API = {
    "comprimido": "comprimidos", "tabletas": "comprimidos", "capsulas": "capsulas",
    "suspension oral": "suspension oral", "solucion oral": "solucion oral",
    "solucion inyectable": "solucion inyectable", "jarabe": "jarabe", "crema": "crema",
    "gotas": "gotas", "polvo": "polvo", "gel": "gel", "unguento": "unguento",
    "frasco ampolla": "frasco ampolla", "solucion oftalmologica": "solucion oftalmica",
    "solucion nasal": "solucion nasal", "supositorio": "supositorios", "sachet": "sobres",
}

PATRON_ML = re.compile(r"\bx\s*(\d+(?:[.,]\d+)?)\s*ml\b")

def expandir(nombre):
    texto = sin_tildes(nombre)
    for patron, reemplazo in EXPANSIONES:
        texto = re.sub(patron, reemplazo, texto)
    return texto

def extraer_envase(nombre):
    texto = expandir(nombre)
    m = PATRON_UNIDADES.search(texto)
    if m:
        unidad = m.group(2)
        unidad = {"comp": "comprimidos", "comprimido": "comprimidos", "capsula": "capsulas",
                  "tabletas": "comprimidos", "sobre": "sobres"}.get(unidad, unidad)
        return m.group(1), unidad
    m = PATRON_ML.search(texto)
    if m: return m.group(1).replace(",", "."), "ml"
    return "", ""

def cargar_isp():
    """
    Composicion oficial del ISP: los principios activos de cada registro
    y el vocabulario completo, para reconocerlos dentro de un nombre.
    """
    ruta = SALIDA / "isp_composicion.csv"
    if not ruta.exists():
        raise SystemExit(f"Falta {ruta}. Ejecuta primero ingesta_isp/normalizacion_isp.py.")

    por_registro = defaultdict(set)
    vocabulario = set()
    with ruta.open(encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            principio = sin_tildes(fila["principio_activo"])
            if not principio:
                continue
            por_registro[fila["registro_raiz"].strip().upper()].add(principio)
            # Los nombres muy cortos generan falsos positivos
            if len(principio) > 5:
                vocabulario.add(principio)
    return por_registro, vocabulario


def principio_en_nombre(nombre, vocabulario):
    """
    Principios activos del ISP mencionados en el nombre, por palabra
    completa: "tretinoina" no debe reconocerse dentro de "isotretinoina".
    Si uno esta contenido en otro mas largo, se queda el largo
    ("acido acetilsalicilico" y no "acido").
    """
    texto = expandir(nombre)
    hallados = [p for p in vocabulario if re.search(r"\b" + re.escape(p) + r"\b", texto)]
    resultado = []
    for p in sorted(hallados, key=len, reverse=True):
        if not any(p in otro for otro in resultado):
            resultado.append(p)
    return sorted(resultado)

def main():
    candidatos = sorted(ENTRADA.glob("profar_catalogo_*.json"))
    if not candidatos:
        print(f"No se encontró ningún catálogo en {ENTRADA}")
        return
    archivo = candidatos[-1]

    print(f"Leyendo {archivo.name}")
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    fecha = datos.get("fecha_muestreo", "")

    composicion_isp, vocabulario = cargar_isp()
    print(f"Vocabulario del ISP: {len(vocabulario)} principios activos")

    productos = []
    precios = []

    for p in datos.get("productos", []):
        nombre = limpiar(p.get("productName"))
        if not nombre: continue

        url_producto = p.get("pdpUrl", "")
        # El id es el numero final de la URL ("...-x-20-comp-114046.html"):
        # la URL completa excede el largo de la columna en la base. Sin URL
        # se usa un hash estable del nombre (hash() cambia en cada ejecucion)
        # La API GraphQL trae el sku, que es el mismo numero de la URL
        m_id = re.search(r"-(\d+)\.html$", url_producto)
        sku = p.get("sku") or (m_id.group(1) if m_id else "n" + hashlib.md5(nombre.encode("utf-8")).hexdigest()[:12])
        especificaciones = p.get("especificaciones", {})

        principio = ""
        principio_origen = ""
        registro_raiz = ""
        registro_declarado = especificaciones.get("Registro ISP", "")

        # Limpiar registro (Captura F-, B-, E-)
        if registro_declarado:
            match_limpio = re.search(r'([A-Z]-\d+)', registro_declarado, re.IGNORECASE)
            if match_limpio:
                registro_raiz = match_limpio.group(1).upper()
        else:
            match_reg = re.search(r'([A-Z]-\d{4,6})', json.dumps(p), re.IGNORECASE)
            if match_reg:
                registro_raiz = match_reg.group(1).upper()
                registro_declarado = registro_raiz

        # ESTRATEGIA 1: principios oficiales del registro ISP declarado
        if registro_raiz and registro_raiz in composicion_isp:
            principio = " ".join(sorted(composicion_isp[registro_raiz])).upper()
            principio_origen = "registro_isp"

        # ESTRATEGIA 2: Especificaciones explícitas
        if not principio:
            pa_declarado = especificaciones.get("Principio Activo", "")
            if pa_declarado:
                principio = pa_declarado.upper()
                principio_origen = "ficha_tecnica"

        # ESTRATEGIA 3: principio activo del ISP reconocido en el nombre.
        # Antes se buscaba cualquier palabra del nombre dentro de los nombres
        # comerciales del ISP y se tomaba el primero: "COMP" esta en casi
        # todos, asi que se asignaban medicamentos sin relacion y se armaban
        # comparaciones falsas (Rybelsus agrupado con melatonina).
        if not principio:
            encontrados = principio_en_nombre(nombre, vocabulario)
            if encontrados:
                principio = " ".join(encontrados).upper()
                principio_origen = "nombre"

        forma = extraer_forma(expandir(nombre))
        forma_origen = "nombre" if forma else ""
        if not forma:
            forma = FORMAS_API.get(sin_tildes(especificaciones.get("Forma Farmacéutica", "")), "")
            forma_origen = "api" if forma else ""
        valor, uni, ref_valor, ref_unidad = extraer_concentracion(nombre)
        cantidad, unidad = extraer_envase(nombre)

        productos.append({
            "id_producto": sku, "sku": sku, "nombre_publicado": nombre, "marca": especificaciones.get("Marca", ""),
            "url_producto": url_producto, "url_imagen": p.get("imageUrl", ""), "ean": p.get("ean", ""),
            "registro_declarado": registro_declarado, "registro_raiz": registro_raiz,
            "principio_activo": principio, "principio_origen": principio_origen,
            "forma_farmaceutica": forma, "forma_origen": forma_origen,
            "concentracion_valor": valor if valor is not None else "", "concentracion_unidad": uni,
            "referencia_valor": ref_valor if ref_valor is not None else "", "referencia_unidad": ref_unidad,
            "cantidad_envase": cantidad, "unidad_envase": unidad, "clase_producto": "",
            "bioequivalente_declarado": bool(p.get("isBioequivalent")), "bioequivalente_tipo": "", "condicion_venta": especificaciones.get("Condición de Venta", ""),
        })

        precio_oferta = p.get("price-sale-cl")
        if precio_oferta is not None and precio_oferta > 0:
            precios.append({
                "id_producto": sku, "fecha_muestreo": fecha,
                "precio_normal": p.get("price-list-cl") or precio_oferta,
                "precio_oferta": precio_oferta, "disponible": p.get("disponible", True),
            })

    SALIDA.mkdir(parents=True, exist_ok=True)
    for nombre_archivo, filas in [("profar_productos.csv", productos), ("profar_precios.csv", precios)]:
        with (SALIDA / nombre_archivo).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
            w.writeheader()
            w.writerows(filas)

    total = len(productos)
    con_reg = sum(1 for x in productos if x["registro_raiz"])
    con_pri = sum(1 for x in productos if x["principio_activo"])
    origen_isp = sum(1 for x in productos if x["principio_origen"] == "registro_isp")
    origen_ficha = sum(1 for x in productos if x["principio_origen"] == "ficha_tecnica")
    origen_nombre = sum(1 for x in productos if x["principio_origen"] == "nombre")

    print(f"\n{total} productos normalizados")
    print(f"  con registro ISP detectado:  {con_reg:4} ({100*con_reg/total if total else 0:.1f}%)")
    print(f"  con principio activo:        {con_pri:4} ({100*con_pri/total if total else 0:.1f}%)")
    print(f"  -> por registro ISP:         {origen_isp:4} ({100*origen_isp/total if total else 0:.1f}%)")
    print(f"  -> por ficha de Profar:      {origen_ficha:4} ({100*origen_ficha/total if total else 0:.1f}%)")
    print(f"  -> reconocido en el nombre:  {origen_nombre:4} ({100*origen_nombre/total if total else 0:.1f}%)")
    print(f"\nGuardado en {SALIDA}")

if __name__ == "__main__":
    main()