"""
Capa plata (Ahumada): normaliza el catalogo y lo deja con las mismas
columnas que las demas farmacias, para que la capa oro las cruce sin
distinguir el origen.

Entrada:
    data/bronce/ahumada_catalogo_AAAA-MM-DD.json

Salidas:
    data/plata/ahumada_productos.csv
    data/plata/ahumada_precios.csv

A diferencia de las otras cadenas, la ficha de Ahumada publica en campos
estructurados el registro sanitario, el principio activo, la
concentracion y la forma farmaceutica. El nombre se usa solo como
respaldo cuando algun campo falta.

El precio que se compara es el que paga cualquier persona. El precio con
tarjeta CMR se descarta aqui porque exige un medio de pago especifico y
no es equivalente al precio publico de otra farmacia.

Uso:
    python normalizar_ahumada.py
    python normalizar_ahumada.py ahumada_catalogo_2026-09-20.json
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

# La ficha escribe la forma en singular; la capa oro espera el plural
SINGULAR_A_PLURAL = {
    "comprimido": "comprimidos",
    "comprimido recubierto": "comprimidos recubiertos",
    "comprimido masticable": "comprimidos masticables",
    "comprimido efervescente": "comprimidos efervescentes",
    "comprimido dispersable": "comprimidos dispersables",
    "comprimido sublingual": "comprimidos sublinguales",
    "capsula": "capsulas",
    "capsula blanda": "capsulas blandas",
    "supositorio": "supositorios",
    "ampolla": "ampollas",
    "ovulo": "ovulos",
    "sobre": "sobres",
    "parche": "parches",
    "gragea": "grageas",
}

ENVASE_CONTABLE = (
    r"(comprimidos|comprimido|comp|capsulas|capsula|sobres|sobre|"
    r"supositorios|ovulos|ampollas|grageas|parches|tabletas)"
)

# Ahumada suele escribir el envase como "x 16 comprimidos"
PATRON_UNIDADES = re.compile(r"\bx?\s*(\d+)\s+" + ENVASE_CONTABLE)
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


def extraer_forma(texto):
    comparable = sin_tildes(texto)
    for forma in FORMAS:
        if forma in comparable:
            return forma
    return ""


def normalizar_forma(forma_ficha, nombre):
    """
    Prefiere la forma deducida del nombre, porque sigue la misma lista que
    usan las demas farmacias. Si el nombre no la trae, usa la de la ficha
    llevada a plural.
    """
    desde_nombre = extraer_forma(nombre)
    if desde_nombre:
        return desde_nombre, "nombre"

    f = sin_tildes(forma_ficha)
    if not f:
        return "", ""
    return SINGULAR_A_PLURAL.get(f, f), "campo"


def extraer_concentracion(texto):
    m = PATRON_CONCENTRACION.search(texto or "")
    if not m:
        return None, "", None, ""

    valor = float(m.group(1).replace(",", "."))
    unidad = m.group(2).lower()

    ref_valor = None
    ref_unidad = m.group(4) or ""
    if ref_unidad:
        ref_valor = float(m.group(3).replace(",", ".")) if m.group(3) else 1.0

    return valor, unidad, ref_valor, ref_unidad.lower()


def extraer_envase(nombre, forma=""):
    texto = sin_tildes(nombre)

    m = PATRON_UNIDADES.search(texto)
    if m:
        unidad = m.group(2)
        if unidad == "comp":
            unidad = "comprimidos"
        return m.group(1), unidad

    # Ahumada suele cerrar el nombre con "x 10" sin repetir la unidad:
    # "Dropol Comprimidos Efervescentes Tubo x 10". Sin esta regla se
    # tomaria el "1 g" de la concentracion como tamanio del envase.
    final = re.search(r"\bx\s*-*\s*(\d+)\s*$", texto)
    if final and forma:
        unidad = forma.split()[0]
        if unidad in ("comprimidos", "capsulas", "sobres", "supositorios",
                      "ovulos", "ampollas", "grageas", "parches"):
            return final.group(1), unidad

    limpio = PATRON_RAZON.sub("/ REF", texto)
    coincidencias = PATRON_VOLUMEN.findall(limpio)
    if coincidencias:
        valor, unidad = coincidencias[-1]
        return valor.replace(",", "."), "g" if unidad == "gr" else unidad

    return "", ""


def cargar_vocabulario():
    ruta = SALIDA / "isp_composicion.csv"
    if not ruta.exists():
        return set()
    vocabulario = set()
    with ruta.open(encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            p = sin_tildes(fila["principio_activo"])
            if len(p) > 5:
                vocabulario.add(p)
    return vocabulario


def extraer_principio(nombre, vocabulario):
    texto = sin_tildes(nombre)
    hallados = [
        p for p in vocabulario
        if re.search(r"\b" + re.escape(p) + r"\b", texto)
    ]
    resultado = []
    for p in sorted(hallados, key=len, reverse=True):
        if not any(p in otro for otro in resultado):
            resultado.append(p)
    return sorted(resultado)


def main():
    if len(sys.argv) > 1:
        archivo = ENTRADA / sys.argv[1]
    else:
        candidatos = sorted(ENTRADA.glob("ahumada_catalogo_*.json"))
        if not candidatos:
            print(f"No se encontro ningun catalogo en {ENTRADA}")
            return
        archivo = candidatos[-1]

    print(f"Leyendo {archivo.name}")
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    fecha = datos.get("fecha_muestreo", "")

    vocabulario = cargar_vocabulario()

    productos = []
    precios = []
    con_tarjeta = 0

    for p in datos.get("productos", []):
        ficha = p.get("ficha") or {}
        espec = ficha.get("especificaciones") or {}

        nombre = limpiar(ficha.get("nombre"))
        if not nombre:
            # Sin ficha no hay nombre confiable: se omite
            continue

        registro = limpiar(espec.get("Registro Sanitario"))

        principio = limpiar(espec.get("Principio Activo"))
        principio_origen = "campo" if principio else ""
        if not principio and vocabulario:
            hallados = extraer_principio(nombre, vocabulario)
            if hallados:
                principio = " ".join(hallados).upper()
                principio_origen = "nombre"

        forma, forma_origen = normalizar_forma(
            espec.get("Forma Farmaceutica", ""), nombre
        )

        # La concentracion de la ficha es mas confiable que la del nombre
        valor, uni, ref_valor, ref_unidad = extraer_concentracion(
            espec.get("Concentracion", "")
        )
        if valor is None:
            valor, uni, ref_valor, ref_unidad = extraer_concentracion(nombre)

        cantidad, unidad = extraer_envase(nombre, forma)

        if p.get("precio_tarjeta"):
            con_tarjeta += 1

        productos.append(
            {
                "id_producto": p["pid"],
                "sku": p["pid"],
                "nombre_publicado": nombre,
                "marca": limpiar(ficha.get("marca") or espec.get("Marca")),
                "url_producto": p.get("url", ""),
                "url_imagen": ficha.get("imagen", ""),
                "ean": "",
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
                "clase_producto": "",
                "bioequivalente_declarado": bool(p.get("bioequivalente")),
                "bioequivalente_tipo": "",
                "condicion_venta": "",
            }
        )

        if p.get("precio_oferta") is not None:
            precios.append(
                {
                    "id_producto": p["pid"],
                    "fecha_muestreo": fecha,
                    "precio_normal": p.get("precio_normal") or p["precio_oferta"],
                    "precio_oferta": p["precio_oferta"],
                    "disponible": p.get("disponible", True),
                }
            )

    if not productos:
        print("No se normalizo ningun producto.")
        return

    SALIDA.mkdir(parents=True, exist_ok=True)

    for nombre_archivo, filas in [
        ("ahumada_productos.csv", productos),
        ("ahumada_precios.csv", precios),
    ]:
        with (SALIDA / nombre_archivo).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
            w.writeheader()
            w.writerows(filas)

    total = len(productos)
    con_reg = sum(1 for x in productos if x["registro_raiz"])
    con_pri = sum(1 for x in productos if x["principio_activo"])
    con_forma = sum(1 for x in productos if x["forma_farmaceutica"])
    con_env = sum(1 for x in productos if x["cantidad_envase"])
    con_conc = sum(1 for x in productos if x["concentracion_valor"] != "")

    print(f"\n{total} productos normalizados")
    print(f"  con registro sanitario: {con_reg:4} ({100*con_reg/total:.1f}%)")
    print(f"  principio activo:       {con_pri:4} ({100*con_pri/total:.1f}%)")
    print(f"  forma farmaceutica:     {con_forma:4} ({100*con_forma/total:.1f}%)")
    print(f"  con envase:             {con_env:4} ({100*con_env/total:.1f}%)")
    print(f"  con concentracion:      {con_conc:4} ({100*con_conc/total:.1f}%)")
    print(f"\n  con precio de tarjeta:  {con_tarjeta:4} (descartado en la comparacion)")
    print(f"\n{len(precios)} precios para {fecha}")
    print(f"Guardado en {SALIDA}")


if __name__ == "__main__":
    main()
