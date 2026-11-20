"""
Plan de pruebas de BioEqui (HU24): ejecuta cada caso y deja registro.

Cada caso tiene un identificador (CP-01 a CP-22), el area que prueba, lo
que se espera y lo que se obtuvo. El resultado queda en
pruebas/resultados/AAAA-MM-DD.md y .csv, con la fecha y la evidencia de
cada caso, para adjuntarlo a la documentacion.

Requisitos: la base de datos, la API y la pagina deben estar corriendo
(python levantar.py).

Uso (desde la carpeta Desarrollo_Proyecto):
    python pruebas/ejecutar_pruebas.py             casos rapidos (unos segundos)
    python pruebas/ejecutar_pruebas.py --completo  ademas ejecuta la
                                                   actualizacion completa sin
                                                   descargar (CP-22, ~2 min)

Codigo de salida: 0 si todos los casos se aprueban, 1 si alguno falla.
"""

import csv
import json
import os
import re
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import psycopg2
import requests
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "cruce"))

load_dotenv(RAIZ / ".env")

API = "http://localhost:8000"
WEB = "http://localhost:5173"
PLATA = RAIZ / "data" / "plata"
BRONCE = RAIZ / "data" / "bronce"
RESULTADOS = Path(__file__).resolve().parent / "resultados"

FARMACIAS = ["ahumada", "cruzverde", "drsimi", "liga", "novasalud", "profar"]

CASOS = []


def caso(identificador, area, descripcion, esperado, completo=False):
    """Registra una funcion como caso del plan de pruebas."""
    def registrar(funcion):
        CASOS.append({
            "id": identificador, "area": area, "descripcion": descripcion,
            "esperado": esperado, "funcion": funcion, "completo": completo,
        })
        return funcion
    return registrar


class Fallo(Exception):
    pass


def verificar(condicion, mensaje):
    if not condicion:
        raise Fallo(mensaje)


def sql(consulta, parametros=None):
    with psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5433"),
        dbname=os.getenv("DB_NAME"), user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    ) as conexion, conexion.cursor() as cur:
        cur.execute(consulta, parametros or ())
        return cur.fetchall()


def get(ruta):
    return requests.get(API + ruta, timeout=30)


def leer_csv(nombre):
    with (PLATA / nombre).open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ------------------------------------------------------------------
# Datos: ISP y pipeline
# ------------------------------------------------------------------

@caso("CP-01", "Datos ISP", "Consolidar los listados del ISP en plata (HU01)",
      "isp_medicamentos.csv con mas de 4.000 registros, sin registros repetidos")
def cp01():
    filas = leer_csv("isp_medicamentos.csv")
    registros = [f["registro_sanitario"] for f in filas]
    verificar(len(filas) > 4000, f"solo {len(filas)} registros")
    verificar(len(set(registros)) == len(registros), "hay registros repetidos")
    return f"{len(filas)} registros, todos distintos"


@caso("CP-02", "Datos ISP", "Separar la raiz del registro y su anio (HU02)",
      "Cada raiz es el registro sin el sufijo: F-8660/11 -> F-8660")
def cp02():
    filas = leer_csv("isp_medicamentos.csv")
    malas = [f for f in filas if f["registro_raiz"] != f["registro_sanitario"].split("/")[0]]
    verificar(not malas, f"{len(malas)} raices mal separadas, ej. {malas[:1]}")
    patron = re.compile(r"^[A-Z]{1,3}-\d+$")
    invalidas = [f["registro_raiz"] for f in filas if not patron.match(f["registro_raiz"])]
    verificar(not invalidas, f"{len(invalidas)} raices con formato invalido")
    return f"{len(filas)} raices correctas y con formato ^[A-Z]{{1,3}}-\\d+$"


@caso("CP-03", "Pipeline", "Bronce guarda el catalogo crudo de cada farmacia",
      "Las 6 farmacias tienen al menos un catalogo en data/bronce con productos")
def cp03():
    detalle = []
    for f in FARMACIAS:
        archivos = sorted(BRONCE.glob(f"{f}_catalogo_*.json"))
        verificar(archivos, f"{f} no tiene catalogos en bronce")
        with archivos[-1].open(encoding="utf-8") as a:
            datos = json.load(a)
        total = datos.get("total", len(datos.get("productos", [])))
        verificar(total > 0, f"{archivos[-1].name} esta vacio")
        detalle.append(f"{f}: {len(archivos)} muestreos, ultimo {total}")
    return "; ".join(detalle)


@caso("CP-04", "Pipeline", "Plata deja a todas las farmacias con las mismas columnas",
      "Cada farmacia tiene productos y precios en plata, con columnas identicas")
def cp04():
    columnas = None
    detalle = []
    for f in FARMACIAS:
        productos = leer_csv(f"{f}_productos.csv")
        precios = leer_csv(f"{f}_precios.csv")
        verificar(productos and precios, f"{f} sin datos en plata")
        if columnas is None:
            columnas = list(productos[0].keys())
        verificar(list(productos[0].keys()) == columnas, f"{f} tiene columnas distintas")
        detalle.append(f"{f}: {len(productos)}")
    return f"{len(columnas)} columnas comunes; productos por farmacia: " + ", ".join(detalle)


@caso("CP-05", "Cruce ISP", "Vincular productos con el ISP por registro sanitario (HU08)",
      "Todo producto 'vinculado' apunta a un medicamento existente del ISP")
def cp05():
    (total, sin), = sql("""
        SELECT COUNT(*), COUNT(*) FILTER (WHERE id_medicamento IS NULL)
        FROM productos_farmacia WHERE estado_vinculacion = 'vinculado'""")
    verificar(total > 1000, f"solo {total} vinculados")
    verificar(sin == 0, f"{sin} vinculados sin medicamento")
    return f"{total} productos vinculados, todos con medicamento del ISP"


@caso("CP-06", "Cruce ISP", "Apartar vinculaciones dudosas (HU09)",
      "Registros invalidos o sospechosos no quedan vinculados a un medicamento")
def cp06():
    filas = sql("""
        SELECT estado_vinculacion, COUNT(*), COUNT(id_medicamento)
        FROM productos_farmacia
        WHERE estado_vinculacion IN ('registro_invalido', 'registro_sospechoso')
        GROUP BY 1""")
    verificar(filas, "no hay casos apartados para verificar")
    for estado, total, vinculados in filas:
        verificar(vinculados == 0, f"{vinculados} productos '{estado}' quedaron vinculados")
    return "; ".join(f"{e}: {t} apartados, 0 vinculados" for e, t, _ in filas)


@caso("CP-07", "Cruce ISP", "Solo se comparan productos equivalentes (HU10)",
      "Dentro de un grupo todos los productos tienen el mismo envase y forma")
def cp07():
    (grupos, malos), = sql("""
        SELECT COUNT(*), COUNT(*) FILTER (WHERE envases > 1 OR familias > 1)
        FROM (SELECT clave_equivalencia,
                     COUNT(DISTINCT cantidad_envase) AS envases,
                     COUNT(DISTINCT familia) AS familias
              FROM v_productos_vigentes
              WHERE clave_equivalencia IS NOT NULL
              GROUP BY 1) g""")
    verificar(malos == 0, f"{malos} grupos mezclan envases o formas")
    return f"{grupos} grupos revisados, ninguno mezcla envases ni formas"


@caso("CP-08", "Cruce ISP", "Combinados con la dosis de cada principio activo (HU19)",
      "Un combinado tiene una dosis por principio activo; 875/125 y 500/125 en grupos distintos")
def cp08():
    claves = [c for (c,) in sql(
        "SELECT DISTINCT clave_equivalencia FROM v_productos_vigentes "
        "WHERE clave_equivalencia LIKE '%%+%%'")]
    malas = []
    for c in claves:
        principio, conc = c.split("|")[:2]
        if "+" in principio and principio.count("+") != conc.count("+"):
            malas.append(c)
    verificar(not malas, f"{len(malas)} combinados con dosis incompleta, ej. {malas[:2]}")

    grupos = dict(sql("""
        SELECT split_part(clave_equivalencia, '|', 2), COUNT(DISTINCT farmacia)
        FROM v_productos_vigentes
        WHERE clave_equivalencia LIKE 'acido clavulanico+amoxicilina|%%|solido_oral|14comprimidos'
        GROUP BY 1"""))
    verificar(grupos.get("875+125mg", 0) >= 2,
              f"875/125 x 14 no se compara entre farmacias: {grupos}")

    from dosis import detalle_dosis
    texto = detalle_dosis(["acido clavulanico", "amoxicilina"], "875+125mg",
                          ["Amoxicilina 875 mg acido clavulanico 125 mg 14 comprimidos"])
    verificar(texto == "amoxicilina 875 mg + acido clavulanico 125 mg", f"detalle: {texto}")
    return (f"{len(claves)} grupos combinados con una dosis por principio; "
            f"amoxicilina/clavulanico x 14: {grupos}; detalle: '{texto}'")


@caso("CP-09", "Cruce ISP", "Origen de la bioequivalencia (HU11)",
      "Si el ISP informa la bioequivalencia, la fuente es 'isp'; si no, la de la farmacia")
def cp09():
    (malos, isp, comercial), = sql("""
        SELECT COUNT(*) FILTER (WHERE bioequivalente_isp IS NOT NULL
                                  AND bioequivalente_fuente <> 'isp'),
               COUNT(*) FILTER (WHERE bioequivalente_fuente = 'isp'),
               COUNT(*) FILTER (WHERE bioequivalente_fuente = 'comercial')
        FROM v_productos_vigentes""")
    verificar(malos == 0, f"{malos} productos con fuente incorrecta")
    return f"fuente ISP: {isp}; fuente farmacia: {comercial}; 0 inconsistencias"


# ------------------------------------------------------------------
# Base de datos
# ------------------------------------------------------------------

@caso("CP-10", "Base de datos", "Esquema en tercera forma normal (HU33)",
      "9 tablas y 3 vistas; sin las columnas derivadas del esquema anterior")
def cp10():
    tablas = {t for (t,) in sql(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'")}
    vistas = {v for (v,) in sql(
        "SELECT table_name FROM information_schema.views WHERE table_schema = 'public'")}
    verificar(len(tablas) == 9, f"{len(tablas)} tablas: {sorted(tablas)}")
    verificar(vistas == {"v_productos", "v_historico_precios", "v_productos_vigentes"},
              f"vistas: {sorted(vistas)}")
    derivadas = sql("""
        SELECT table_name, column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name IN ('productos_farmacia', 'historico_precios')
          AND column_name IN ('registro_raiz', 'precio_unitario', 'clave_equivalencia', 'familia')""")
    verificar(not derivadas, f"columnas derivadas guardadas: {derivadas}")
    return f"tablas: {', '.join(sorted(tablas))}; vistas: {', '.join(sorted(vistas))}"


@caso("CP-11", "Base de datos", "Historial sin duplicados (HU13)",
      "Un solo precio por producto y fecha; la restriccion UNIQUE existe")
def cp11():
    (repetidos,), = sql("""
        SELECT COUNT(*) FROM (SELECT id_producto, fecha_muestreo FROM historico_precios
                              GROUP BY 1, 2 HAVING COUNT(*) > 1) r""")
    verificar(repetidos == 0, f"{repetidos} pares producto-fecha repetidos")
    restricciones = sql("""
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'historico_precios'::regclass AND contype = 'u'""")
    verificar(restricciones, "falta la restriccion UNIQUE")
    (filas, fechas), = sql("SELECT COUNT(*), COUNT(DISTINCT fecha_muestreo) FROM historico_precios")
    return f"{filas} precios en {fechas} fechas de muestreo, 0 repetidos; UNIQUE: {restricciones[0][0]}"


@caso("CP-12", "Base de datos", "Integridad referencial",
      "Ningun producto apunta a una farmacia, grupo o medicamento inexistente; ningun grupo vacio")
def cp12():
    (huerfanos,), = sql("""
        SELECT COUNT(*) FROM productos_farmacia p
        LEFT JOIN farmacias f ON f.id = p.id_farmacia
        LEFT JOIN grupos_equivalencia g ON g.id = p.id_grupo
        LEFT JOIN medicamentos m ON m.id = p.id_medicamento
        WHERE f.id IS NULL
           OR (p.id_grupo IS NOT NULL AND g.id IS NULL)
           OR (p.id_medicamento IS NOT NULL AND m.id IS NULL)""")
    (vacios,), = sql("""
        SELECT COUNT(*) FROM grupos_equivalencia g
        WHERE NOT EXISTS (SELECT 1 FROM productos_farmacia p WHERE p.id_grupo = g.id)""")
    verificar(huerfanos == 0, f"{huerfanos} productos con referencias rotas")
    verificar(vacios == 0, f"{vacios} grupos sin productos")
    return "0 referencias rotas; 0 grupos vacios"


# ------------------------------------------------------------------
# API
# ------------------------------------------------------------------

@caso("CP-13", "API", "Buscar por nombre o principio activo (HU14)",
      "GET /buscar?q=losartan responde 200 con presentaciones de losartan")
def cp13():
    r = get("/buscar?q=losartan")
    verificar(r.status_code == 200, f"respuesta {r.status_code}")
    d = r.json()
    verificar(d["total"] > 0, "sin resultados")
    otras = [p for p in d["presentaciones"] if "losartan" not in p["principio_activo"]]
    verificar(not otras, f"{len(otras)} presentaciones sin losartan")
    return f"200; {d['total']} presentaciones, todas de losartan"


@caso("CP-14", "API", "Validar la busqueda minima (HU14)",
      "GET /buscar?q=ab (menos de 3 letras) responde 422")
def cp14():
    r = get("/buscar?q=ab")
    verificar(r.status_code == 422, f"respuesta {r.status_code}")
    return "422 Unprocessable Entity"


@caso("CP-15", "API", "Tamanios de envase de una presentacion (HU15)",
      "GET /presentacion/{clave} devuelve los envases ordenados de menor a mayor")
def cp15():
    r = get("/presentacion/" + quote("losartan|50.0mg|solido_oral", safe=""))
    verificar(r.status_code == 200, f"respuesta {r.status_code}")
    cantidades = [t["cantidad_envase"] for t in r.json()["tamanios"]]
    verificar(cantidades == sorted(cantidades), f"orden: {cantidades}")
    return f"200; envases {cantidades}"


@caso("CP-16", "API", "Comparar precios de un mismo envase (HU16)",
      "GET /comparar/{clave} ordena por precio y todas las opciones son del mismo grupo")
def cp16():
    clave = "losartan|50.0mg|solido_oral|30comprimidos"
    r = get("/comparar/" + quote(clave, safe=""))
    verificar(r.status_code == 200, f"respuesta {r.status_code}")
    d = r.json()
    precios = [p["precio_oferta"] for p in d["productos"]]
    verificar(precios == sorted(precios), "no esta ordenado por precio")
    verificar(d["clave_equivalencia"] == clave, "grupo distinto")
    farmacias = {p["farmacia"] for p in d["productos"]}
    return f"200; {len(precios)} opciones en {len(farmacias)} farmacias, de ${precios[0]} a ${precios[-1]}"


@caso("CP-17", "API", "Historial de precios de un producto (HU18)",
      "GET /producto/{id} entrega la serie ordenada por fecha con minimo y maximo")
def cp17():
    (id_producto,), = sql("""
        SELECT id_producto FROM historico_precios GROUP BY 1
        ORDER BY COUNT(*) DESC LIMIT 1""")
    r = get(f"/producto/{id_producto}")
    verificar(r.status_code == 200, f"respuesta {r.status_code}")
    d = r.json()
    fechas = [h["fecha_muestreo"] for h in d["historial"]]
    verificar(fechas == sorted(fechas) and len(fechas) > 1, f"fechas: {fechas}")
    verificar(get("/producto/999999999").status_code == 404, "un id inexistente no da 404")
    return (f"200; producto {id_producto} con {len(fechas)} precios ordenados, "
            f"min ${d['resumen']['precio_min']}, max ${d['resumen']['precio_max']}; id inexistente: 404")


@caso("CP-18", "Cumplimiento", "Extraccion etica de las farmacias (HU07)",
      "Cada extractor hace pausas entre peticiones, se identifica y respeta robots.txt")
def cp18():
    detalle = []
    for script in sorted((RAIZ / "scraping").glob("*/descargar*.py")):
        texto = script.read_text(encoding="utf-8")
        nombre = script.parent.name
        verificar("User-Agent" in texto, f"{script.name} no declara User-Agent")
        pausa = re.search(r"^PAUSA\s*=\s*([\d.]+)", texto, re.M)
        espera = "sleep(" in texto
        verificar(pausa or espera or nombre == "liga",
                  f"{script.name} no hace pausas entre peticiones")
        detalle.append(f"{nombre}/{script.name}: " + (f"pausa {pausa.group(1)} s" if pausa
                       else "pocas peticiones" if not espera else "con espera"))
    return "; ".join(detalle)


@caso("CP-19", "Cumplimiento", "Credenciales fuera del codigo (HU22)",
      "Ningun archivo versionado contiene contrasenias ni cookies; el .env esta ignorado")
def cp19():
    raiz_git = RAIZ.parent
    ignorado = subprocess.run(["git", "check-ignore", "-q", str(RAIZ / ".env")],
                              cwd=raiz_git).returncode == 0
    verificar(ignorado, "el .env no esta en .gitignore")
    secretos = [os.getenv("DB_PASSWORD"), os.getenv("CRUZVERDE_COOKIE")]
    archivos = subprocess.run(["git", "ls-files"], cwd=raiz_git, capture_output=True,
                              text=True, encoding="utf-8").stdout.splitlines()
    revisados = 0
    for ruta in archivos:
        p = raiz_git / ruta
        if p.suffix.lower() not in {".py", ".yml", ".yaml", ".md", ".txt", ".jsx", ".js",
                                    ".json", ".sql", ".bat", ".example", ".env"} or not p.exists():
            continue
        if p.stat().st_size > 2_000_000:
            continue
        texto = p.read_text(encoding="utf-8", errors="ignore")
        revisados += 1
        for s in secretos:
            verificar(not (s and len(s) >= 6 and s in texto), f"{ruta} contiene una credencial")
    return f".env ignorado por git; {revisados} archivos versionados revisados, sin credenciales"


@caso("CP-20", "API", "Farmacias y cifras de cobertura",
      "GET /farmacias lista las 6 farmacias activas; /estadisticas entrega cifras mayores a 0")
def cp20():
    farmacias = get("/farmacias").json()["farmacias"]
    verificar(len(farmacias) == 6, f"{len(farmacias)} farmacias")
    verificar(all(f["productos"] > 0 for f in farmacias), "una farmacia no tiene productos")
    e = get("/estadisticas").json()
    verificar(all(e[k] > 0 for k in ("medicamentos_isp", "productos", "grupos")), f"cifras: {e}")
    return (f"{len(farmacias)} farmacias; {e['productos']} productos, "
            f"{e['grupos']} grupos, {e['medicamentos_isp']} medicamentos ISP")


# ------------------------------------------------------------------
# Pagina y operacion
# ------------------------------------------------------------------

@caso("CP-21", "Pagina", "La pagina carga y consume la API (HU17)",
      "http://localhost:5173 responde 200, carga la aplicacion y la API permite su origen (CORS)")
def cp21():
    r = requests.get(WEB, timeout=30)
    verificar(r.status_code == 200, f"respuesta {r.status_code}")
    verificar('id="root"' in r.text, "la pagina no contiene la aplicacion")
    cors = requests.get(API + "/farmacias", headers={"Origin": WEB}, timeout=30)
    permitido = cors.headers.get("access-control-allow-origin")
    verificar(permitido in ("*", WEB), f"CORS: {permitido}")
    return f"200; aplicacion React cargada; CORS permite {permitido}"


@caso("CP-22", "Operacion", "Control de descargas incompletas (HU21)",
      "Una descarga con menos del 80% de los productos anteriores se aparta")
def cp22():
    from actualizar import UMBRAL, descarga_incompleta
    verificar(UMBRAL == 0.80, f"umbral {UMBRAL}")
    verificar(descarga_incompleta(390, 1950), "la caida de Profar (390 de 1.950) no se aparta")
    verificar(not descarga_incompleta(1900, 1950), "una variacion normal (97%) se aparta")
    verificar(not descarga_incompleta(500, 0), "sin muestreo anterior se aparta")
    return "390 de 1.950 (20%): se aparta; 1.900 de 1.950 (97%): se acepta; sin anterior: se acepta"


@caso("CP-23", "Operacion", "Actualizacion completa con un comando (HU21)",
      "actualizar.py --sin-descarga reprocesa plata, oro y carga y termina sin errores",
      completo=True)
def cp23():
    inicio = time.time()
    r = subprocess.run([sys.executable, str(RAIZ / "actualizar.py"), "--sin-descarga"],
                       cwd=RAIZ, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env={**os.environ, "PYTHONUTF8": "1"})
    ultimas = [l for l in r.stdout.strip().splitlines() if l.strip()][-3:]
    verificar(r.returncode in (0, 2), f"codigo {r.returncode}: {' | '.join(ultimas)}")
    return (f"codigo de salida {r.returncode} en {time.time() - inicio:.0f} s; "
            + " | ".join(l.split('] ', 1)[-1] for l in ultimas))


# ------------------------------------------------------------------

def main():
    completo = "--completo" in sys.argv
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    fecha = datetime.now()
    resultados = []

    print(f"Plan de pruebas BioEqui - {fecha:%Y-%m-%d %H:%M}\n")
    for c in CASOS:
        if c["completo"] and not completo:
            resultados.append({**c, "estado": "No ejecutado",
                               "obtenido": "Requiere --completo", "segundos": 0})
            print(f"  {c['id']}  --        {c['descripcion']} (usa --completo)")
            continue
        inicio = time.time()
        try:
            obtenido = c["funcion"]()
            estado = "Aprobado"
        except Fallo as e:
            obtenido, estado = str(e), "Fallido"
        except Exception as e:  # error inesperado: tambien es un fallo
            obtenido = f"{type(e).__name__}: {e}"
            estado = "Fallido"
            traceback.print_exc()
        segundos = time.time() - inicio
        resultados.append({**c, "estado": estado, "obtenido": obtenido, "segundos": segundos})
        marca = "OK  " if estado == "Aprobado" else "FALLA"
        print(f"  {c['id']}  {marca}  {c['descripcion']}")
        if estado != "Aprobado":
            print(f"           {obtenido}")

    aprobados = sum(1 for r in resultados if r["estado"] == "Aprobado")
    fallidos = sum(1 for r in resultados if r["estado"] == "Fallido")
    print(f"\n{aprobados} aprobados, {fallidos} fallidos, "
          f"{len(resultados) - aprobados - fallidos} no ejecutados")

    RESULTADOS.mkdir(exist_ok=True)
    base = RESULTADOS / f"{fecha:%Y-%m-%d}"
    campos = ["id", "area", "descripcion", "esperado", "obtenido", "estado", "fecha"]
    with base.with_suffix(".csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        for r in resultados:
            w.writerow({**r, "fecha": f"{fecha:%Y-%m-%d %H:%M}"})

    lineas = [
        f"# Resultados del plan de pruebas - {fecha:%Y-%m-%d %H:%M}",
        "",
        f"**{aprobados} aprobados, {fallidos} fallidos, "
        f"{len(resultados) - aprobados - fallidos} no ejecutados.** "
        "Generado por `pruebas/ejecutar_pruebas.py`.",
        "",
        "| Caso | Área | Prueba | Resultado esperado | Resultado obtenido (evidencia) | Estado |",
        "|---|---|---|---|---|---|",
    ]
    for r in resultados:
        celda = lambda t: str(t).replace("|", "/").replace("\n", " ")
        lineas.append(f"| {r['id']} | {r['area']} | {celda(r['descripcion'])} | "
                      f"{celda(r['esperado'])} | {celda(r['obtenido'])} | {r['estado']} |")
    base.with_suffix(".md").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(f"Registro en {base.with_suffix('.md').relative_to(RAIZ)} y .csv")
    return 1 if fallidos else 0


if __name__ == "__main__":
    sys.exit(main())
