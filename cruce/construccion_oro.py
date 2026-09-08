"""
Capa oro: cruza el catalogo comercial con el catalogo oficial del ISP,
conforma grupos de equivalencia y calcula precio unitario y ahorro.

Entradas (capa plata):
    data/plata/isp_medicamentos.csv
    data/plata/isp_composicion.csv
    data/plata/drsimi_productos.csv
    data/plata/drsimi_precios.csv

Salidas:
    data/oro/productos_enriquecidos.csv   producto con datos oficiales
    data/oro/grupos_equivalencia.csv      resumen por grupo comparable
    data/oro/discrepancias.csv            divergencias entre fuentes
    data/oro/vinculaciones_dudosas.csv    registros que no superan la validacion

Criterio de homologacion adoptado:
    Dos productos son comparables si coinciden en principio activo,
    concentracion normalizada y FAMILIA de forma farmaceutica.

    Se agrupa por familia y no por forma exacta porque variaciones como el
    recubrimiento no alteran la equivalencia. Las formas de liberacion
    modificada se mantienen en familia aparte: ahi el recubrimiento si
    altera la farmacocinetica y no son intercambiables.

Validaciones incorporadas:
    Se detecto que la fuente comercial publica registros sanitarios
    erroneos: un mismo registro aparece en productos que son medicamentos
    distintos, y algunos productos traen valores que no son registros. Por
    eso la vinculacion se valida contrastando el nombre publicado con el
    nombre oficial, y los casos que no superan la validacion se apartan en
    vez de aceptarse.

Uso:
    python construir_oro.py
"""

import csv
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PLATA = RAIZ / "data" / "plata"
ORO = RAIZ / "data" / "oro"

# Formato valido de registro sanitario del ISP
PATRON_REGISTRO = re.compile(r"^[A-Z]{1,3}-\d+$")

# Familia y via por forma farmaceutica.
# Las formas de liberacion modificada tienen familia propia: no son
# intercambiables con las de liberacion inmediata.
FAMILIAS = {
    "comprimidos": ("solido_oral", "oral"),
    "comprimido": ("solido_oral", "oral"),
    "comprimidos recubiertos": ("solido_oral", "oral"),
    "comprimido recubierto": ("solido_oral", "oral"),
    "comprimidos con recubrimiento enterico": ("solido_oral", "oral"),
    "comprimidos dispersables": ("solido_oral", "oral"),
    "comprimidos masticables": ("solido_oral", "oral"),
    "comprimidos efervescentes": ("solido_oral", "oral"),
    "capsulas": ("solido_oral", "oral"),
    "capsulas blandas": ("solido_oral", "oral"),
    "grageas": ("solido_oral", "oral"),
    "obleas": ("solido_oral", "oral"),

    "comprimidos de liberacion prolongada": ("liberacion_modificada", "oral"),
    "comprimidos recubiertos de liberacion prolongada": ("liberacion_modificada", "oral"),
    "comprimidos recubiertos de liberacion modificada": ("liberacion_modificada", "oral"),
    "comprimidos de liberacion modificada": ("liberacion_modificada", "oral"),
    "capsulas de liberacion prolongada": ("liberacion_modificada", "oral"),

    "comprimidos sublinguales": ("sublingual", "sublingual"),

    "jarabe": ("liquido_oral", "oral"),
    "solucion oral": ("liquido_oral", "oral"),
    "suspension oral": ("liquido_oral", "oral"),
    "solucion para gotas orales": ("liquido_oral", "oral"),
    "gotas": ("liquido_oral", "oral"),
    "polvo para solucion oral": ("liquido_oral", "oral"),
    "polvo para suspension oral": ("liquido_oral", "oral"),
    "sobres": ("liquido_oral", "oral"),
    "sobre": ("liquido_oral", "oral"),
    "polvo": ("liquido_oral", "oral"),

    "solucion inyectable": ("inyectable", "parenteral"),
    "suspension inyectable": ("inyectable", "parenteral"),
    "liofilizado para solucion inyectable": ("inyectable", "parenteral"),
    "polvo para solucion inyectable": ("inyectable", "parenteral"),
    "ampollas": ("inyectable", "parenteral"),
    "frasco ampolla": ("inyectable", "parenteral"),

    "crema": ("topico", "topica"),
    "unguento": ("topico", "topica"),
    "gel": ("topico", "topica"),
    "solucion topica": ("topico", "topica"),
    "parches": ("transdermico", "transdermica"),

    "solucion oftalmica": ("oftalmico", "oftalmica"),
    "solucion otica": ("otico", "otica"),
    "solucion nasal": ("nasal", "nasal"),
    "aerosol": ("inhalatorio", "inhalatoria"),
    "solucion para nebulizacion": ("inhalatorio", "inhalatoria"),

    "supositorios": ("rectal", "rectal"),
    "ovulos": ("vaginal", "vaginal"),
}

# Palabras que aparecen en casi todos los nombres y no sirven para validar
VACIAS = {
    "comprimidos", "comprimido", "capsulas", "capsula", "recubiertos",
    "recubierto", "solucion", "suspension", "inyectable", "oral", "jarabe",
    "crema", "gel", "polvo", "gotas", "sobres", "sobre", "para", "con",
    "blandas", "dermica", "topica", "infantil", "adulto", "plus", "forte",
    "mg", "ml", "mcg", "ui",
}


def sin_tildes(texto):
    n = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in n if unicodedata.category(c) != "Mn").strip()


def palabras(texto):
    """Palabras significativas de un nombre, para comparar dos nombres."""
    t = sin_tildes(texto)
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return {p for p in t.split() if len(p) > 3 and p not in VACIAS and not p.isdigit()}


def clasificar(forma):
    if not forma:
        return "", ""
    return FAMILIAS.get(sin_tildes(forma), ("otra", ""))


def concentracion_normalizada(valor, unidad, ref_valor, ref_unidad):
    """
    Lleva la concentracion a una expresion comparable.

    Sin referencia devuelve el valor en la unidad base.
    Con referencia devuelve la razon, para que 160 mg/5 mL y
    320 mg/10 mL resulten equivalentes.
    """
    if not valor:
        return ""

    try:
        v = float(valor)
    except ValueError:
        return ""

    factor = {"g": 1000, "mg": 1, "mcg": 0.001, "µg": 0.001}
    u = (unidad or "").lower()
    if u in factor:
        v = v * factor[u]
        u = "mg"

    if ref_valor and ref_unidad:
        try:
            rv = float(ref_valor)
            if rv:
                return f"{round(v / rv, 4)}{u}/{ref_unidad.lower()}"
        except ValueError:
            pass

    return f"{round(v, 4)}{u}"


def leer(nombre):
    ruta = PLATA / nombre
    if not ruta.exists():
        raise SystemExit(f"Falta {ruta}. Ejecuta primero los scripts de plata.")
    with ruta.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    isp_med = {m["registro_raiz"]: m for m in leer("isp_medicamentos.csv")}

    isp_comp = defaultdict(list)
    for c in leer("isp_composicion.csv"):
        isp_comp[c["registro_raiz"]].append(c["principio_activo"])

    # Vocabulario de principios activos, para detectar combinaciones que la
    # fuente comercial declara de forma incompleta
    vocabulario = set()
    for lista in isp_comp.values():
        for p in lista:
            for token in p.split():
                if len(token) > 5:
                    vocabulario.add(sin_tildes(token))

    productos = leer("drsimi_productos.csv")
    precios = {p["id_producto"]: p for p in leer("drsimi_precios.csv")}

    filas = []
    discrepancias = []
    dudosas = []

    for p in productos:
        raiz = p["registro_raiz"]
        nombre = p["nombre_publicado"]

        # Un registro que no respeta el formato del ISP no es utilizable
        registro_valido = bool(PATRON_REGISTRO.match(raiz))
        oficial = isp_med.get(raiz) if registro_valido else None

        # Validacion: el nombre publicado y el oficial deben compartir al
        # menos una palabra significativa. La fuente comercial publica
        # registros erroneos y sin esto se agrupan medicamentos distintos.
        if oficial:
            comunes = palabras(nombre) & palabras(oficial["nombre_comercial"])
            if not comunes:
                dudosas.append(
                    {
                        "id_producto": p["id_producto"],
                        "registro_raiz": raiz,
                        "nombre_publicado": nombre,
                        "nombre_oficial": oficial["nombre_comercial"],
                        "motivo": "nombres sin coincidencia",
                    }
                )
                oficial = None
                estado = "registro_sospechoso"
            else:
                estado = "vinculado"
        elif not registro_valido and raiz:
            dudosas.append(
                {
                    "id_producto": p["id_producto"],
                    "registro_raiz": raiz,
                    "nombre_publicado": nombre,
                    "nombre_oficial": "",
                    "motivo": "registro con formato invalido",
                }
            )
            estado = "registro_invalido"
        elif raiz:
            estado = "sin_correspondencia"
        else:
            estado = "sin_registro"

        # El principio activo oficial tiene prioridad: viene completo y con
        # nomenclatura normalizada por el regulador
        if oficial and isp_comp.get(raiz):
            principios = isp_comp[raiz]
            principio_origen = "isp"
        elif p["principio_activo"]:
            principios = [p["principio_activo"]]
            principio_origen = "comercial"
        else:
            principios = []
            principio_origen = ""

        # Deteccion de combinaciones: si el nombre menciona un principio
        # activo que no esta en la lista, el producto tiene mas de uno y no
        # puede agruparse con el simple
        declarados = {sin_tildes(x) for pr in principios for x in pr.split()}
        detectados = {t for t in vocabulario if t in sin_tildes(nombre)}
        extra = {t for t in detectados if t not in declarados}
        composicion_incompleta = bool(extra)

        # La forma y la concentracion oficiales tienen prioridad
        forma = (oficial or {}).get("forma_farmaceutica") or p["forma_farmaceutica"]
        familia, via = clasificar(forma)

        if oficial and oficial.get("concentracion_valor"):
            conc = concentracion_normalizada(
                oficial["concentracion_valor"],
                oficial["concentracion_unidad"],
                oficial["referencia_valor"],
                oficial["referencia_unidad"],
            )
        else:
            conc = concentracion_normalizada(
                p["concentracion_valor"],
                p["concentracion_unidad"],
                p["referencia_valor"],
                p["referencia_unidad"],
            )

        bio_comercial = p["bioequivalente_declarado"]
        bio_oficial = (oficial or {}).get("es_bioequivalente", "")

        if (
            oficial
            and bio_comercial in ("True", "False")
            and bio_oficial in ("True", "False")
            and bio_comercial != bio_oficial
        ):
            discrepancias.append(
                {
                    "registro_raiz": raiz,
                    "nombre_publicado": nombre,
                    "nombre_oficial": oficial["nombre_comercial"],
                    "declarado_comercio": bio_comercial,
                    "registrado_isp": bio_oficial,
                    "sentido": "subdeclara" if bio_comercial == "False" else "sobredeclara",
                }
            )

        precio = precios.get(p["id_producto"], {})
        precio_oferta = precio.get("precio_oferta") or ""

        # Precio por unidad: es la unica base valida de comparacion, porque
        # los envases tienen tamanios distintos
        precio_unitario = ""
        if precio_oferta and p["cantidad_envase"]:
            try:
                cant = float(p["cantidad_envase"])
                if cant:
                    precio_unitario = round(float(precio_oferta) / cant, 2)
            except ValueError:
                pass

        # Clave de equivalencia. Los productos con composicion incompleta
        # quedan sin clave: agruparlos seria incorrecto.
        clave = ""
        if principios and conc and familia and not composicion_incompleta:
            clave = "|".join(
                [
                    "+".join(sorted(sin_tildes(x) for x in principios)),
                    conc,
                    familia,
                ]
            )

        filas.append(
            {
                "id_producto": p["id_producto"],
                "nombre_publicado": nombre,
                "marca": p["marca"],
                "registro_raiz": raiz,
                "estado_vinculacion": estado,
                "nombre_oficial": (oficial or {}).get("nombre_comercial", ""),
                "laboratorio_oficial": (oficial or {}).get("laboratorio", ""),
                "principios_activos": "+".join(principios),
                "principio_origen": principio_origen,
                "composicion_incompleta": composicion_incompleta,
                "principios_detectados": "+".join(sorted(extra)) if extra else "",
                "forma_farmaceutica": forma,
                "familia": familia,
                "via_administracion": via,
                "concentracion": conc,
                "cantidad_envase": p["cantidad_envase"],
                "unidad_envase": p["unidad_envase"],
                "condicion_venta": p["condicion_venta"],
                "clase_producto": p["clase_producto"],
                "bioequivalente_comercial": bio_comercial,
                "bioequivalente_isp": bio_oficial,
                "categoria_isp": (oficial or {}).get("categoria_isp", ""),
                "precio_normal": precio.get("precio_normal", ""),
                "precio_oferta": precio_oferta,
                "precio_unitario": precio_unitario,
                "disponible": precio.get("disponible", ""),
                "url_producto": p["url_producto"],
                "url_imagen": p["url_imagen"],
                "clave_equivalencia": clave,
            }
        )

    grupos = defaultdict(list)
    for f in filas:
        if f["clave_equivalencia"] and f["precio_unitario"] != "":
            grupos[f["clave_equivalencia"]].append(f)

    resumen = []
    for clave, miembros in grupos.items():
        if len(miembros) < 2:
            continue

        unitarios = [float(m["precio_unitario"]) for m in miembros]
        barato = min(miembros, key=lambda m: float(m["precio_unitario"]))
        caro = max(miembros, key=lambda m: float(m["precio_unitario"]))

        bioequivalentes = sum(
            1
            for m in miembros
            if m["bioequivalente_isp"] == "True" or m["bioequivalente_comercial"] == "True"
        )

        ahorro = ""
        if float(caro["precio_unitario"]) > 0:
            ahorro = round(
                100
                * (float(caro["precio_unitario"]) - float(barato["precio_unitario"]))
                / float(caro["precio_unitario"]),
                1,
            )

        resumen.append(
            {
                "clave_equivalencia": clave,
                "principios_activos": miembros[0]["principios_activos"],
                "concentracion": miembros[0]["concentracion"],
                "familia": miembros[0]["familia"],
                "via_administracion": miembros[0]["via_administracion"],
                "productos": len(miembros),
                "bioequivalentes": bioequivalentes,
                "precio_unitario_min": min(unitarios),
                "precio_unitario_max": max(unitarios),
                "ahorro_pct": ahorro,
                "mas_barato": barato["nombre_publicado"],
                "mas_caro": caro["nombre_publicado"],
            }
        )

    resumen.sort(key=lambda r: r["ahorro_pct"] if r["ahorro_pct"] != "" else 0, reverse=True)

    ORO.mkdir(parents=True, exist_ok=True)

    for nombre_archivo, datos in [
        ("productos_enriquecidos.csv", filas),
        ("grupos_equivalencia.csv", resumen),
        ("discrepancias.csv", discrepancias),
        ("vinculaciones_dudosas.csv", dudosas),
    ]:
        if not datos:
            continue
        ruta = ORO / nombre_archivo
        with ruta.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(datos[0].keys()))
            w.writeheader()
            w.writerows(datos)

    total = len(filas)
    estados = defaultdict(int)
    for f in filas:
        estados[f["estado_vinculacion"]] += 1

    con_clave = sum(1 for f in filas if f["clave_equivalencia"])
    incompletas = sum(1 for f in filas if f["composicion_incompleta"])

    print(f"{total} productos procesados\n")
    print("Estado de vinculacion:")
    for estado, n in sorted(estados.items(), key=lambda x: -x[1]):
        print(f"  {estado:22} {n:4} ({100*n/total:.1f}%)")

    print(f"\n  composicion incompleta:{incompletas:4} (excluidos de agrupacion)")
    print(f"  con clave equivalencia:{con_clave:4} ({100*con_clave/total:.1f}%)")
    print(f"\n{len(resumen)} grupos con dos o mas productos comparables")
    print(f"{len(dudosas)} vinculaciones apartadas por validacion")
    print(f"{len(discrepancias)} discrepancias entre fuentes")

    if discrepancias:
        sub = sum(1 for d in discrepancias if d["sentido"] == "subdeclara")
        print(f"  el comercio subdeclara:  {sub}")
        print(f"  el comercio sobredeclara:{len(discrepancias) - sub}")

    print(f"\nGuardado en {ORO}")


if __name__ == "__main__":
    main()