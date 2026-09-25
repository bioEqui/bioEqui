"""
Carga a PostgreSQL: lleva los datos del pipeline a la base relacional.

Reparto de fuentes:
    Desde plata  ->  medicamentos, principios_activos, composicion
                     (el catalogo oficial completo del ISP)
    Desde oro    ->  farmacias, productos_farmacia, historico_precios
                     (lo comercial, ya cruzado y validado)

Se carga el catalogo del ISP completo y no solo los productos que la
farmacia vende: la base debe conocer todos los medicamentos autorizados,
no unicamente los que estan a la venta en una cadena.

La carga es idempotente. Medicamentos y productos se actualizan si ya
existen; los precios se acumulan, porque conforman la serie temporal.

Requiere un archivo .env en la raiz con:
    DB_HOST=localhost
    DB_PORT=5433
    DB_NAME=bioequi_db
    DB_USER=admin
    DB_PASSWORD=...

Uso:
    python db/cargar.py
"""

import csv
import os
import sys
from pathlib import Path
from datetime import datetime

import psycopg2
from psycopg2.extras import execute_batch
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]
PLATA = RAIZ / "data" / "plata"
ORO = RAIZ / "data" / "oro"

load_dotenv(RAIZ / ".env")

CONEXION = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5433"),
    "dbname": os.getenv("DB_NAME", "bioequi_db"),
    "user": os.getenv("DB_USER", "admin"),
    "password": os.getenv("DB_PASSWORD"),
}

# Datos de la farmacia. Al sumar cadenas se agrega una entrada aca.
FARMACIAS = {
    "drsimi": {
        "nombre": "Farmacias del Dr. Simi",
        "tipo": "cadena",
        "url_base": "https://www.drsimi.cl",
    },
    "cruzverde": {
        "nombre": "Farmacias Cruz Verde",
        "tipo": "cadena",
        "url_base": "https://www.cruzverde.cl",
    },
    "ahumada": {
        "nombre": "Farmacias Ahumada",
        "tipo": "cadena",
        "url_base": "https://www.farmaciasahumada.cl",
    },
    "profar": {
        "nombre": "Profar",
        "tipo": "cadena",
        "url_base": "https://www.profar.cl", 
    },
}


def leer(ruta):
    if not ruta.exists():
        raise SystemExit(f"Falta {ruta}. Ejecuta primero los scripts del pipeline.")
    with ruta.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(valor):
    """Convierte a numero, o None si viene vacio o no es valido."""
    if valor is None or str(valor).strip() == "":
        return None
    try:
        return float(valor)
    except ValueError:
        return None


def entero(valor):
    v = num(valor)
    return int(v) if v is not None else None


def booleano(valor):
    v = str(valor).strip().lower()
    if v in ("true", "1", "si", "sí"):
        return True
    if v in ("false", "0", "no"):
        return False
    return None


def texto(valor):
    v = (valor or "").strip()
    return v or None

def fecha(valor):
    """
    El ISP mezcla dos formatos de fecha en sus listados: la mayoria
    viene como 2004-08-23 y algunas como 17-02-2026.
    """
    v = (valor or "").strip()
    if not v:
        return None

    for formato in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(v, formato).date()
        except ValueError:
            continue
    return None


def cargar_medicamentos(cur):
    """Catalogo oficial del ISP, con su composicion."""
    medicamentos = leer(PLATA / "isp_medicamentos.csv")
    composicion = leer(PLATA / "isp_composicion.csv")

    # Los principios activos primero: son referenciados por composicion
    principios = sorted({c["principio_activo"] for c in composicion if c["principio_activo"]})

    execute_batch(
        cur,
        """
        INSERT INTO principios_activos (nombre_dci)
        VALUES (%s)
        ON CONFLICT (nombre_dci) DO NOTHING
        """,
        [(p,) for p in principios],
        page_size=500,
    )

    cur.execute("SELECT id, nombre_dci FROM principios_activos")
    id_principio = {nombre: pid for pid, nombre in cur.fetchall()}

    # Medicamentos. El registro sanitario es unico en el catalogo del ISP,
    # asi que sirve como clave para actualizar sin borrar. Esto es lo que
    # permite conservar el historial de precios entre ejecuciones.
    id_medicamento = {}

    for m in medicamentos:
        cur.execute(
            """
            INSERT INTO medicamentos (
                registro_sanitario, registro_raiz, nombre_comercial,
                laboratorio, forma_farmaceutica, fecha_registro,
                categoria_isp, es_bioequivalente
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (registro_sanitario) DO UPDATE SET
                nombre_comercial = EXCLUDED.nombre_comercial,
                laboratorio = EXCLUDED.laboratorio,
                es_bioequivalente = EXCLUDED.es_bioequivalente
            RETURNING id
            """,
            (
                m["registro_sanitario"],
                m["registro_raiz"],
                m["nombre_comercial"],
                texto(m["laboratorio"]),
                texto(m["forma_farmaceutica"]),
                fecha(m["fecha_registro"]),
                texto(m["categoria_isp"]),
                booleano(m["es_bioequivalente"]),
            ),
        )
        # Se indexa por raiz para poder vincular la composicion
        id_medicamento.setdefault(m["registro_raiz"], cur.fetchone()[0])

    # Composicion: una fila por principio activo del medicamento
    filas = []
    for c in composicion:
        mid = id_medicamento.get(c["registro_raiz"])
        pid = id_principio.get(c["principio_activo"])
        if not mid or not pid:
            continue

        # La concentracion vive en la relacion, no en el medicamento
        med = next(
            (m for m in medicamentos if m["registro_raiz"] == c["registro_raiz"]),
            {},
        )
        filas.append(
            (
                mid,
                pid,
                entero(c["orden"]) or 1,
                num(med.get("concentracion_valor")),
                texto(med.get("concentracion_unidad")),
                num(med.get("referencia_valor")),
                texto(med.get("referencia_unidad")),
            )
        )

    execute_batch(
        cur,
        """
        INSERT INTO composicion (
            id_medicamento, id_principio_activo, orden,
            concentracion_valor, concentracion_unidad,
            referencia_valor, referencia_unidad
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id_medicamento, id_principio_activo) DO NOTHING
        """,
        filas,
        page_size=500,
    )

    return len(medicamentos), len(principios), len(filas)


def cargar_farmacias(cur):
    for codigo, datos in FARMACIAS.items():
        cur.execute(
            """
            INSERT INTO farmacias (codigo, nombre, tipo, url_base, activa)
            VALUES (%s, %s, %s, %s, TRUE)
            ON CONFLICT (codigo) DO UPDATE
                SET nombre = EXCLUDED.nombre,
                    url_base = EXCLUDED.url_base
            """,
            (codigo, datos["nombre"], datos["tipo"], datos["url_base"]),
        )

    cur.execute("SELECT codigo, id FROM farmacias")
    return dict(cur.fetchall())


def cargar_productos(cur, farmacias):
    """Productos comerciales ya cruzados y validados."""
    productos = leer(ORO / "productos_enriquecidos.csv")

    # Mapa de raiz a id de medicamento, para resolver la vinculacion
    cur.execute("SELECT registro_raiz, MIN(id) FROM medicamentos GROUP BY registro_raiz")
    id_medicamento = dict(cur.fetchall())

    insertados = 0
    vinculados = 0
    ids = {}

    for p in productos:
        id_farmacia = farmacias.get(p.get("farmacia", "drsimi"))
        if not id_farmacia:
            continue

        # Solo se vincula lo que la capa oro dio por valido: los estados
        # sospechoso e invalido no deben propagarse a la base
        mid = None
        if p["estado_vinculacion"] == "vinculado":
            mid = id_medicamento.get(p["registro_raiz"])
            if mid:
                vinculados += 1

        cur.execute(
            """
            INSERT INTO productos_farmacia (
                id_farmacia, id_medicamento, id_externo, nombre_publicado,
                marca, url_producto, url_imagen, registro_declarado,
                registro_raiz, estado_vinculacion, forma_farmaceutica,
                familia, via_administracion, cantidad_envase, unidad_envase,
                condicion_venta, clase_producto, bioequivalente_comercial,
                composicion_incompleta, clave_equivalencia
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id_farmacia, id_externo) DO UPDATE SET
                id_medicamento = EXCLUDED.id_medicamento,
                nombre_publicado = EXCLUDED.nombre_publicado,
                estado_vinculacion = EXCLUDED.estado_vinculacion,
                clave_equivalencia = EXCLUDED.clave_equivalencia
            RETURNING id
            """,
            (
                id_farmacia,
                mid,
                p.get("id_global") or p["id_producto"],
                p["nombre_publicado"],
                texto(p["marca"]),
                texto(p["url_producto"]),
                texto(p["url_imagen"]),
                texto(p["registro_raiz"]),
                texto(p["registro_raiz"]),
                p["estado_vinculacion"],
                texto(p["forma_farmaceutica"]),
                texto(p["familia"]),
                texto(p["via_administracion"]),
                num(p["cantidad_envase"]),
                texto(p["unidad_envase"]),
                texto(p["condicion_venta"]),
                texto(p["clase_producto"]),
                booleano(p["bioequivalente_comercial"]),
                booleano(p["composicion_incompleta"]) or False,
                texto(p["clave_equivalencia"]),
            ),
        )
        ids[p.get("id_global") or p["id_producto"]] = cur.fetchone()[0]
        insertados += 1

    return insertados, vinculados, ids


def cargar_precios(cur, ids, productos):
    """
    Los precios se acumulan: cada ejecucion agrega la observacion del dia
    sin borrar las anteriores. Es lo que conforma la serie temporal.
    """
    filas = []
    for p in productos:
        pid = ids.get(p.get("id_global") or p["id_producto"])
        if not pid or not p["precio_oferta"]:
            continue

        filas.append(
            (
                pid,
                p.get("fecha_muestreo") or None,
                entero(p["precio_normal"]),
                entero(p["precio_oferta"]),
                num(p["precio_unitario"]),
                booleano(p["disponible"]),
            )
        )

    execute_batch(
        cur,
        """
        INSERT INTO historico_precios (
            id_producto, fecha_muestreo, precio_normal,
            precio_oferta, precio_unitario, disponible
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (id_producto, fecha_muestreo) DO UPDATE SET
            precio_normal = EXCLUDED.precio_normal,
            precio_oferta = EXCLUDED.precio_oferta,
            precio_unitario = EXCLUDED.precio_unitario,
            disponible = EXCLUDED.disponible
        """,
        filas,
        page_size=500,
    )

    return len(filas)


def main():
    if not CONEXION["password"]:
        print("Falta DB_PASSWORD. Crea un archivo .env en la raiz del proyecto.")
        sys.exit(1)

    # La fecha de muestreo viene de los precios de plata. Se leen los de
    # todas las farmacias, porque cada una se actualiza en su propia
    # fecha y el historico debe registrar cuando se observo cada precio.
    precios_plata = {}
    for ruta in sorted(PLATA.glob("*_precios.csv")):
        farmacia = ruta.stem.replace("_precios", "")
        for p in leer(ruta):
            precios_plata[f"{farmacia}:{p['id_producto']}"] = p

    productos_oro = leer(ORO / "productos_enriquecidos.csv")
    for p in productos_oro:
        clave = p.get("id_global") or p["id_producto"]
        origen = precios_plata.get(clave, {})
        p["fecha_muestreo"] = origen.get("fecha_muestreo")

    try:
        conexion = psycopg2.connect(**CONEXION)
    except psycopg2.OperationalError as e:
        print(f"No se pudo conectar a la base:\n  {e}")
        sys.exit(1)

    try:
        with conexion:
            with conexion.cursor() as cur:
                # Se recarga el catalogo completo en cada ejecucion. Los
                # precios no se tocan: solo se acumulan.

                print("Cargando catalogo del ISP...")
                n_med, n_pri, n_com = cargar_medicamentos(cur)
                print(f"  {n_med} medicamentos")
                print(f"  {n_pri} principios activos")
                print(f"  {n_com} filas de composicion")

                print("\nCargando farmacias...")
                farmacias = cargar_farmacias(cur)

                print("Cargando productos...")
                n_prod, n_vinc, ids = cargar_productos(cur, farmacias)
                print(f"  {n_prod} productos")
                print(f"  {n_vinc} vinculados al catalogo oficial")

                print("Cargando precios...")
                n_pre = cargar_precios(cur, ids, productos_oro)
                print(f"  {n_pre} observaciones de precio")

        print("\nCarga completa.")

    finally:
        conexion.close()


if __name__ == "__main__":
    main()