"""
API de BioEqui: expone las consultas que necesita la interfaz web.

La busqueda funciona en tres niveles, porque el usuario no busca un
envase especifico sino un medicamento:

    1. Escribe "paracetamol" y ve las PRESENTACIONES disponibles
       (500 mg comprimidos, jarabe 160 mg/5 mL, gotas...)

    2. Elige una presentacion y ve los TAMANIOS de envase
       (12, 16, 20, 24, 48 comprimidos)

    3. Elige un tamanio y ve las FARMACIAS que lo venden,
       ordenadas por precio

Solo el tercer nivel corresponde a una comparacion valida: mismo
principio activo, misma concentracion, misma forma y mismo envase.

Ejecutar:
    uvicorn api.main:app --reload

Documentacion interactiva en http://localhost:8000/docs
"""

import os
from pathlib import Path
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

RAIZ = Path(__file__).resolve().parents[1]
load_dotenv(RAIZ / ".env")

CONEXION = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5433"),
    "dbname": os.getenv("DB_NAME", "bioequi_db"),
    "user": os.getenv("DB_USER", "admin"),
    "password": os.getenv("DB_PASSWORD"),
}

app = FastAPI(
    title="BioEqui",
    description="Comparador de precios de medicamentos bioequivalentes",
    version="0.1",
)

# Durante el desarrollo el frontend corre en otro puerto
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def consultar(sql, parametros=None):
    """Ejecuta una consulta y devuelve las filas como diccionarios."""
    try:
        with psycopg2.connect(**CONEXION) as conexion:
            with conexion.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, parametros or ())
                return cur.fetchall()
    except psycopg2.Error as e:
        raise HTTPException(status_code=503, detail=f"Error de base de datos: {e}")


def partes_clave(clave):
    """
    Separa la clave de equivalencia en sus componentes.

    "paracetamol|500.0mg|solido_oral|16comprimidos"
        -> principio, concentracion, familia, envase
    """
    trozos = (clave or "").split("|")
    while len(trozos) < 4:
        trozos.append("")
    return trozos[0], trozos[1], trozos[2], trozos[3]


def clave_presentacion(clave):
    """La clave sin el envase: identifica una presentacion."""
    principio, conc, familia, _ = partes_clave(clave)
    return f"{principio}|{conc}|{familia}"


@app.get("/")
def raiz():
    return {
        "nombre": "BioEqui",
        "documentacion": "/docs",
        "busqueda": "/buscar?q=paracetamol",
    }


@app.get("/buscar")
def buscar(
    q: str = Query(..., min_length=3, description="Nombre o principio activo"),
    limite: int = Query(30, le=100),
    solo_disponibles: bool = True,
):
    """
    Nivel 1: presentaciones que coinciden con la busqueda.

    Agrupa por principio activo, concentracion y forma, ignorando el
    envase: quien escribe "paracetamol" no busca un tamanio especifico.
    """
    filtro_stock = "AND disponible = TRUE" if solo_disponibles else ""

    filas = consultar(
        f"""
        SELECT
            clave_equivalencia,
            nombre_publicado,
            farmacia,
            precio_oferta,
            cantidad_envase,
            unidad_envase,
            familia,
            via_administracion,
            bioequivalente,
            bioequivalente_fuente,
            url_imagen
        FROM v_productos_vigentes
        WHERE clave_equivalencia IS NOT NULL
          AND (nombre_publicado ILIKE %s OR clave_equivalencia ILIKE %s)
          {filtro_stock}
        ORDER BY precio_oferta
        """,
        (f"%{q}%", f"%{q}%"),
    )

    # Agrupar por presentacion, sin considerar el envase
    presentaciones = {}

    for f in filas:
        clave = clave_presentacion(f["clave_equivalencia"])
        principio, conc, familia, _ = partes_clave(f["clave_equivalencia"])

        if clave not in presentaciones:
            presentaciones[clave] = {
                "clave_presentacion": clave,
                "principio_activo": principio,
                "concentracion": conc,
                "familia": familia,
                "via_administracion": f["via_administracion"],
                "precio_desde": f["precio_oferta"],
                "envases": set(),
                "farmacias": set(),
                "productos": 0,
                "hay_bioequivalente": False,
                "url_imagen": f["url_imagen"] or "",
            }

        p = presentaciones[clave]
        p["productos"] += 1
        p["farmacias"].add(f["farmacia"])

        if f["cantidad_envase"]:
            cantidad = float(f["cantidad_envase"])
            p["envases"].add(int(cantidad) if cantidad.is_integer() else cantidad)

        if f["bioequivalente"]:
            p["hay_bioequivalente"] = True

        # Las filas vienen ordenadas por precio: la primera imagen que
        # exista corresponde a la opcion mas economica
        if not p["url_imagen"] and f["url_imagen"]:
            p["url_imagen"] = f["url_imagen"]

    resultado = []
    for p in presentaciones.values():
        p["envases"] = sorted(p["envases"])
        p["farmacias"] = sorted(p["farmacias"])
        resultado.append(p)

    resultado.sort(key=lambda x: (-x["productos"], x["precio_desde"] or 0))

    return {
        "consulta": q,
        "total": len(resultado),
        "presentaciones": resultado[:limite],
    }


@app.get("/presentacion/{clave:path}")
def presentacion(clave: str, solo_disponibles: bool = True):
    """
    Nivel 2: tamanios de envase disponibles para una presentacion.

    Cada tamanio es un grupo de equivalencia distinto: dos envases del
    mismo medicamento no son comparables entre si.
    """
    filtro_stock = "AND disponible = TRUE" if solo_disponibles else ""

    filas = consultar(
        f"""
        SELECT
            clave_equivalencia,
            MAX(cantidad_envase)           AS cantidad_envase,
            MIN(unidad_envase)             AS unidad_envase,
            COUNT(*)                       AS productos,
            COUNT(DISTINCT farmacia)       AS farmacias,
            MIN(precio_oferta)             AS precio_min,
            MAX(precio_oferta)             AS precio_max,
            BOOL_OR(bioequivalente)        AS hay_bioequivalente
        FROM v_productos_vigentes
        WHERE clave_equivalencia LIKE %s
          {filtro_stock}
        GROUP BY clave_equivalencia
        ORDER BY MAX(cantidad_envase)
        """,
        (f"{clave}|%",),
    )

    if not filas:
        raise HTTPException(status_code=404, detail="Presentacion no encontrada")

    principio, conc, familia, _ = partes_clave(clave + "|")

    tamanios = []
    for f in filas:
        ahorro = None
        if f["precio_max"] and f["precio_max"] > 0 and f["farmacias"] > 1:
            ahorro = round(
                100 * (f["precio_max"] - f["precio_min"]) / f["precio_max"], 1
            )

        tamanios.append(
            {
                "clave_equivalencia": f["clave_equivalencia"],
                "cantidad_envase": float(f["cantidad_envase"]) if f["cantidad_envase"] else None,
                "unidad_envase": f["unidad_envase"],
                "productos": f["productos"],
                "farmacias": f["farmacias"],
                "precio_min": f["precio_min"],
                "precio_max": f["precio_max"],
                "ahorro_pct": ahorro,
                "hay_bioequivalente": f["hay_bioequivalente"],
            }
        )

    return {
        "clave_presentacion": clave,
        "principio_activo": principio,
        "concentracion": conc,
        "familia": familia,
        "tamanios": tamanios,
    }


@app.get("/comparar/{clave:path}")
def comparar(clave: str, solo_disponibles: bool = True):
    """
    Nivel 3: farmacias que venden este producto, ordenadas por precio.

    Esta es la unica comparacion estrictamente valida: todos los
    productos coinciden en principio activo, concentracion, forma y
    tamanio de envase.
    """
    filtro_stock = "AND disponible = TRUE" if solo_disponibles else ""

    filas = consultar(
        f"""
        SELECT
            id,
            nombre_publicado,
            marca,
            farmacia,
            precio_normal,
            precio_oferta,
            precio_unitario,
            cantidad_envase,
            unidad_envase,
            condicion_venta,
            bioequivalente,
            bioequivalente_fuente,
            nombre_oficial,
            laboratorio_oficial,
            estado_vinculacion,
            fecha_muestreo,
            disponible,
            url_producto,
            url_imagen
        FROM v_productos_vigentes
        WHERE clave_equivalencia = %s
          {filtro_stock}
        ORDER BY precio_oferta
        """,
        (clave,),
    )

    if not filas:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    opciones = []
    for f in filas:
        descuento = None
        if f["precio_normal"] and f["precio_oferta"]:
            if f["precio_normal"] > f["precio_oferta"]:
                descuento = round(
                    100 * (f["precio_normal"] - f["precio_oferta"]) / f["precio_normal"]
                )

        opciones.append(
            {
                **f,
                "en_oferta": descuento is not None,
                "descuento_pct": descuento,
            }
        )

    mas_barato = opciones[0]["precio_oferta"]
    mas_caro = opciones[-1]["precio_oferta"]

    ahorro = None
    if mas_caro and mas_caro > 0 and len(opciones) > 1:
        ahorro = {
            "monto": mas_caro - mas_barato,
            "porcentaje": round(100 * (mas_caro - mas_barato) / mas_caro, 1),
        }

    principio, conc, familia, envase = partes_clave(clave)

    return {
        "clave_equivalencia": clave,
        "principio_activo": principio,
        "concentracion": conc,
        "familia": familia,
        "envase": envase,
        "opciones": len(opciones),
        "ahorro": ahorro,
        "productos": opciones,
    }


@app.get("/producto/{id_producto}")
def producto(id_producto: int):
    """Detalle de un producto con su historial de precios."""
    detalle = consultar(
        """
        SELECT * FROM v_productos_vigentes WHERE id = %s
        """,
        (id_producto,),
    )

    if not detalle:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    historial = consultar(
        """
        SELECT fecha_muestreo, precio_normal, precio_oferta,
               precio_unitario, disponible
        FROM historico_precios
        WHERE id_producto = %s
        ORDER BY fecha_muestreo
        """,
        (id_producto,),
    )

    # El precio de lista se mantiene constante mientras varia el de
    # oferta: distinguir ambos permite ver cuando hubo promocion
    serie = []
    for h in historial:
        descuento = None
        if h["precio_normal"] and h["precio_oferta"]:
            if h["precio_normal"] > h["precio_oferta"]:
                descuento = round(
                    100 * (h["precio_normal"] - h["precio_oferta"]) / h["precio_normal"]
                )
        serie.append({**h, "descuento_pct": descuento})

    precios = [h["precio_oferta"] for h in historial if h["precio_oferta"]]

    return {
        "producto": detalle[0],
        "historial": serie,
        "resumen": {
            "observaciones": len(serie),
            "precio_min": min(precios) if precios else None,
            "precio_max": max(precios) if precios else None,
            "dias_en_oferta": sum(1 for h in serie if h["descuento_pct"]),
        },
    }


@app.get("/principio/{nombre}")
def por_principio_activo(nombre: str, limite: int = Query(50, le=200)):
    """
    Productos que contienen un principio activo, incluidas las
    combinaciones. Solo funciona para productos vinculados al catalogo
    del ISP, que es donde esta registrada la composicion.
    """
    filas = consultar(
        """
        SELECT DISTINCT
            v.id,
            v.nombre_publicado,
            v.farmacia,
            v.precio_oferta,
            v.clave_equivalencia,
            v.bioequivalente,
            v.bioequivalente_fuente
        FROM v_productos_vigentes v
        JOIN productos_farmacia pf ON pf.id = v.id
        JOIN composicion c         ON c.id_medicamento = pf.id_medicamento
        JOIN principios_activos p  ON p.id = c.id_principio_activo
        WHERE p.nombre_dci ILIKE %s
        ORDER BY v.precio_oferta
        LIMIT %s
        """,
        (f"%{nombre}%", limite),
    )

    return {"principio_activo": nombre, "total": len(filas), "productos": filas}


@app.get("/farmacias")
def farmacias():
    """Cadenas integradas, con su cobertura y ultima actualizacion."""
    return {
        "farmacias": consultar(
            """
            SELECT
                f.codigo,
                f.nombre,
                f.url_base,
                COUNT(p.id)                         AS productos,
                MAX(h.fecha_muestreo)               AS ultima_actualizacion
            FROM farmacias f
            LEFT JOIN productos_farmacia p ON p.id_farmacia = f.id
            LEFT JOIN historico_precios h  ON h.id_producto = p.id
            WHERE f.activa = TRUE
            GROUP BY f.codigo, f.nombre, f.url_base
            ORDER BY f.nombre
            """
        )
    }


@app.get("/estadisticas")
def estadisticas():
    """Cifras generales del sistema, para mostrar cobertura al usuario."""
    general = consultar(
        """
        SELECT
            (SELECT COUNT(*) FROM medicamentos)         AS medicamentos_isp,
            (SELECT COUNT(*) FROM principios_activos)   AS principios_activos,
            (SELECT COUNT(*) FROM productos_farmacia)   AS productos,
            (SELECT COUNT(DISTINCT clave_equivalencia)
             FROM productos_farmacia
             WHERE clave_equivalencia IS NOT NULL)      AS grupos,
            (SELECT COUNT(DISTINCT fecha_muestreo)
             FROM historico_precios)                    AS fechas_muestreo
        """
    )[0]

    comparables = consultar(
        """
        SELECT COUNT(*) AS grupos_multiples
        FROM (
            SELECT clave_equivalencia
            FROM v_productos_vigentes
            WHERE clave_equivalencia IS NOT NULL
            GROUP BY clave_equivalencia
            HAVING COUNT(DISTINCT farmacia) > 1
        ) t
        """
    )[0]

    return {**general, **comparables}