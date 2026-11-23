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

El esquema esta en tercera forma normal (db/propuesta/init_v3.sql): la
forma farmaceutica, la categoria del ISP y el grupo de equivalencia se
guardan una vez en su tabla y se referencian por id. Lo derivado (familia,
via, clave de equivalencia, precio unitario) no se guarda: lo calculan
las vistas.

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

# La familia y la via de cada forma se definen con la misma regla que usa
# la capa oro, para que no puedan diferir
sys.path.insert(0, str(RAIZ / "cruce"))
from construccion_oro import clasificar  # noqa: E402

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
    "liga": {
        "nombre": "Farmacia Liga Chilena contra la Epilepsia",
        "tipo": "fundacion",
        "url_base": "https://ligafarmacia.cl",
    },
    "novasalud": {
        "nombre": "Farmacias Novasalud",
        "tipo": "cadena",
        "url_base": "https://www.novasalud.cl",
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


class Formas:
    """
    Id de cada forma farmaceutica. Crea la forma la primera vez que
    aparece, con su familia y via.
    """

    def __init__(self, cur):
        self.cur = cur
        cur.execute("SELECT nombre, id FROM formas_farmaceuticas")
        self.ids = dict(cur.fetchall())

    def id(self, nombre):
        nombre = texto(nombre)
        if not nombre:
            return None
        if nombre not in self.ids:
            familia, via = clasificar(nombre)
            self.cur.execute(
                """
                INSERT INTO formas_farmaceuticas (nombre, familia, via_administracion)
                VALUES (%s, %s, %s)
                ON CONFLICT (nombre) DO UPDATE SET nombre = EXCLUDED.nombre
                RETURNING id
                """,
                (nombre, familia or None, via or None),
            )
            self.ids[nombre] = self.cur.fetchone()[0]
        return self.ids[nombre]


def cargar_categorias(cur, medicamentos):
    """Cada listado del ISP con la condicion de bioequivalencia que implica."""
    categorias = {}
    for m in medicamentos:
        bio = booleano(m["es_bioequivalente"])
        if texto(m["categoria_isp"]) and bio is not None:
            categorias[m["categoria_isp"].strip()] = bio

    for codigo, bio in categorias.items():
        cur.execute(
            """
            INSERT INTO categorias_isp (codigo, es_bioequivalente)
            VALUES (%s, %s)
            ON CONFLICT (codigo) DO UPDATE SET es_bioequivalente = EXCLUDED.es_bioequivalente
            """,
            (codigo, bio),
        )


def cargar_medicamentos(cur, formas):
    """Catalogo oficial del ISP, con su composicion."""
    medicamentos = leer(PLATA / "isp_medicamentos.csv")
    composicion = leer(PLATA / "isp_composicion.csv")

    cargar_categorias(cur, medicamentos)

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
                registro_sanitario, nombre_comercial, laboratorio,
                id_forma, fecha_registro, categoria_isp
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (registro_sanitario) DO UPDATE SET
                nombre_comercial = EXCLUDED.nombre_comercial,
                laboratorio = EXCLUDED.laboratorio,
                id_forma = EXCLUDED.id_forma,
                categoria_isp = EXCLUDED.categoria_isp
            RETURNING id
            """,
            (
                m["registro_sanitario"],
                m["nombre_comercial"],
                texto(m["laboratorio"]),
                formas.id(m["forma_farmaceutica"]),
                fecha(m["fecha_registro"]),
                texto(m["categoria_isp"]),
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


def id_grupo(cur, grupos, clave):
    """
    Id del grupo de equivalencia de una clave de texto
    (principio|concentracion|familia|envase); lo crea si no existe.
    """
    clave = texto(clave)
    if not clave:
        return None
    if clave not in grupos:
        partes = clave.split("|")
        cur.execute(
            """
            INSERT INTO grupos_equivalencia (principio_activo, concentracion, familia, envase)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (principio_activo, concentracion, familia, envase)
                DO UPDATE SET envase = EXCLUDED.envase
            RETURNING id
            """,
            partes,
        )
        grupos[clave] = cur.fetchone()[0]
    return grupos[clave]


def cargar_productos(cur, farmacias, formas):
    """Productos comerciales ya cruzados y validados."""
    productos = leer(ORO / "productos_enriquecidos.csv")

    # Mapa de raiz a id de medicamento, para resolver la vinculacion. La
    # raiz no se guarda: es el registro sin el sufijo del anio
    cur.execute(
        "SELECT split_part(registro_sanitario, '/', 1), MIN(id) "
        "FROM medicamentos GROUP BY 1"
    )
    id_medicamento = dict(cur.fetchall())

    # Medicamentos que ya tienen forma oficial: sus productos no la repiten
    cur.execute("SELECT id FROM medicamentos WHERE id_forma IS NOT NULL")
    con_forma = {mid for (mid,) in cur.fetchall()}

    cur.execute(
        "SELECT principio_activo || '|' || concentracion || '|' || familia "
        "|| '|' || envase, id FROM grupos_equivalencia"
    )
    grupos = dict(cur.fetchall())

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

        # La forma de la farmacia solo se guarda si no hay una oficial
        id_forma = None if mid in con_forma else formas.id(p["forma_farmaceutica"])

        cur.execute(
            """
            INSERT INTO productos_farmacia (
                id_farmacia, id_medicamento, id_grupo, id_forma, id_externo,
                nombre_publicado, marca, url_producto, url_imagen,
                registro_declarado, estado_vinculacion, cantidad_envase,
                unidad_envase, condicion_venta, clase_producto,
                bioequivalente_comercial, composicion_incompleta
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id_farmacia, id_externo) DO UPDATE SET
                id_medicamento = EXCLUDED.id_medicamento,
                id_grupo = EXCLUDED.id_grupo,
                id_forma = EXCLUDED.id_forma,
                nombre_publicado = EXCLUDED.nombre_publicado,
                -- Se actualiza todo lo que sale de plata y oro: si un
                -- normalizador mejora, el cambio tiene que llegar a la base.
                -- La foto y el enlace no se borran si la fuente deja de
                -- traerlos un dia
                marca = EXCLUDED.marca,
                url_producto = COALESCE(EXCLUDED.url_producto, productos_farmacia.url_producto),
                url_imagen = COALESCE(EXCLUDED.url_imagen, productos_farmacia.url_imagen),
                registro_declarado = EXCLUDED.registro_declarado,
                estado_vinculacion = EXCLUDED.estado_vinculacion,
                cantidad_envase = EXCLUDED.cantidad_envase,
                unidad_envase = EXCLUDED.unidad_envase,
                condicion_venta = EXCLUDED.condicion_venta,
                clase_producto = EXCLUDED.clase_producto,
                bioequivalente_comercial = EXCLUDED.bioequivalente_comercial,
                composicion_incompleta = EXCLUDED.composicion_incompleta
            RETURNING id
            """,
            (
                id_farmacia,
                mid,
                id_grupo(cur, grupos, p["clave_equivalencia"]),
                id_forma,
                p.get("id_global") or p["id_producto"],
                p["nombre_publicado"],
                texto(p["marca"]),
                texto(p["url_producto"]),
                texto(p["url_imagen"]),
                texto(p["registro_raiz"]),
                p["estado_vinculacion"],
                num(p["cantidad_envase"]),
                texto(p["unidad_envase"]),
                texto(p["condicion_venta"]),
                texto(p["clase_producto"]),
                booleano(p["bioequivalente_comercial"]),
                booleano(p["composicion_incompleta"]) or False,
            ),
        )
        ids[p.get("id_global") or p["id_producto"]] = cur.fetchone()[0]
        insertados += 1

    # Un producto que ya no esta en el ultimo catalogo de su farmacia deja
    # de compararse: conserva su historial, pero su ultimo precio es
    # antiguo y su grupo se calculo con reglas que pudieron cambiar. Solo
    # se aplica a farmacias presentes en esta carga (plata guarda el
    # ultimo catalogo bueno de cada una, asi que una descarga fallida no
    # deja a una farmacia fuera).
    cargadas = sorted({farmacias[p["farmacia"]] for p in productos
                       if farmacias.get(p.get("farmacia"))})
    cur.execute(
        """
        UPDATE productos_farmacia SET id_grupo = NULL
        WHERE id_grupo IS NOT NULL
          AND id_farmacia = ANY(%s)
          AND NOT (id = ANY(%s))
        """,
        (cargadas, list(ids.values())),
    )
    retirados = cur.rowcount
    if retirados:
        print(f"  {retirados} productos fuera del catalogo actual dejan de compararse")

    # Un grupo queda sin productos cuando cambia el criterio de agrupacion
    # (por ejemplo, la dosis de los combinados); no tiene sentido guardarlo
    cur.execute(
        """
        DELETE FROM grupos_equivalencia g
        WHERE NOT EXISTS (SELECT 1 FROM productos_farmacia p WHERE p.id_grupo = g.id)
        """
    )

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
                booleano(p["disponible"]),
            )
        )

    # El precio unitario no se guarda: lo calculan las vistas a partir
    # del precio y del envase del producto
    execute_batch(
        cur,
        """
        INSERT INTO historico_precios (
            id_producto, fecha_muestreo, precio_normal,
            precio_oferta, disponible
        )
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (id_producto, fecha_muestreo) DO UPDATE SET
            precio_normal = EXCLUDED.precio_normal,
            precio_oferta = EXCLUDED.precio_oferta,
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

                formas = Formas(cur)

                print("Cargando catalogo del ISP...")
                n_med, n_pri, n_com = cargar_medicamentos(cur, formas)
                print(f"  {n_med} medicamentos")
                print(f"  {n_pri} principios activos")
                print(f"  {n_com} filas de composicion")

                print("\nCargando farmacias...")
                farmacias = cargar_farmacias(cur)

                print("Cargando productos...")
                n_prod, n_vinc, ids = cargar_productos(cur, farmacias, formas)
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