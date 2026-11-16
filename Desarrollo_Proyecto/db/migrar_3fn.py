"""
Migracion del esquema v2 al v3 (tercera forma normal), sobre la base
existente y sin perder el historial de precios.

No se puede recrear la base desde cero: el historial acumula muestreos
de varias fechas y la capa oro solo guarda el ultimo. Por eso la
migracion transforma las tablas en su lugar:

    1. Crea formas_farmaceuticas, categorias_isp y grupos_equivalencia
       a partir de los datos que hoy estan repetidos
    2. Reemplaza esas columnas por claves foraneas
    3. Elimina las columnas derivadas y recrea las vistas
    4. Verifica que las vistas entreguen lo mismo que antes

Todo ocurre en una sola transaccion: si una verificacion falla, la base
queda exactamente como estaba.

Uso (respaldar antes):
    docker exec bioequi_postgres_v2 pg_dump -U admin -d bioequi_db -Fc > respaldo.dump
    python db/migrar_3fn.py
"""

import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "cruce"))
from construccion_oro import clasificar  # noqa: E402  misma regla que la capa oro

ESQUEMA = RAIZ / "db" / "propuesta" / "init_v3.sql"

load_dotenv(RAIZ / ".env")
CONEXION = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5433"),
    "dbname": os.getenv("DB_NAME", "bioequi_db"),
    "user": os.getenv("DB_USER", "admin"),
    "password": os.getenv("DB_PASSWORD"),
}

# Lo que entregan las vistas y no debe cambiar con la migracion
CONTROL = """
    SELECT md5(string_agg(fila, '' ORDER BY fila)), COUNT(*) FROM (
        SELECT concat_ws('#', id, nombre_publicado, farmacia,
                         clave_equivalencia, familia, via_administracion,
                         cantidad_envase, unidad_envase, estado_vinculacion,
                         nombre_oficial, laboratorio_oficial,
                         bioequivalente_isp, bioequivalente_comercial,
                         fecha_muestreo, precio_normal, precio_oferta,
                         disponible) AS fila
        FROM v_productos_vigentes
    ) t
"""


def ya_migrada(cur):
    cur.execute("SELECT to_regclass('grupos_equivalencia') IS NOT NULL")
    return cur.fetchone()[0]


def main():
    conexion = psycopg2.connect(**CONEXION)
    try:
        with conexion:
            with conexion.cursor() as cur:
                if ya_migrada(cur):
                    print("La base ya esta en el esquema v3. No hay nada que hacer.")
                    return

                cur.execute(CONTROL)
                control_antes = cur.fetchone()
                cur.execute("SELECT COUNT(*) FROM historico_precios")
                precios_antes = cur.fetchone()[0]
                print(f"Antes: {control_antes[1]} productos, {precios_antes} precios")

                # Las vistas dependen de las columnas que se eliminan
                cur.execute("DROP VIEW IF EXISTS v_productos_vigentes")

                # 1. Categorias del ISP
                cur.execute("""
                    CREATE TABLE categorias_isp (
                        codigo VARCHAR(20) PRIMARY KEY,
                        es_bioequivalente BOOLEAN NOT NULL)
                """)
                cur.execute("""
                    INSERT INTO categorias_isp
                    SELECT DISTINCT categoria_isp, es_bioequivalente
                    FROM medicamentos WHERE categoria_isp IS NOT NULL
                """)
                print(f"  categorias_isp: {cur.rowcount}")

                # 2. Formas farmaceuticas: las de productos y medicamentos,
                # con la familia y via que define la capa oro
                cur.execute("""
                    CREATE TABLE formas_farmaceuticas (
                        id SERIAL PRIMARY KEY,
                        nombre VARCHAR(100) UNIQUE NOT NULL,
                        familia VARCHAR(50),
                        via_administracion VARCHAR(30))
                """)
                cur.execute("""
                    SELECT forma_farmaceutica FROM productos_farmacia
                    UNION SELECT forma_farmaceutica FROM medicamentos
                """)
                formas = sorted(f for (f,) in cur.fetchall() if f)
                for forma in formas:
                    familia, via = clasificar(forma)
                    cur.execute(
                        "INSERT INTO formas_farmaceuticas (nombre, familia, via_administracion) "
                        "VALUES (%s, %s, %s)",
                        (forma, familia or None, via or None),
                    )
                print(f"  formas_farmaceuticas: {len(formas)}")

                # 3. Medicamentos
                cur.execute("""
                    ALTER TABLE medicamentos
                        ADD COLUMN id_forma INTEGER REFERENCES formas_farmaceuticas(id);
                    UPDATE medicamentos m SET id_forma = f.id
                    FROM formas_farmaceuticas f WHERE f.nombre = m.forma_farmaceutica;
                    ALTER TABLE medicamentos
                        ADD CONSTRAINT medicamentos_categoria_fk
                        FOREIGN KEY (categoria_isp) REFERENCES categorias_isp(codigo),
                        DROP COLUMN forma_farmaceutica,
                        DROP COLUMN familia,
                        DROP COLUMN via_administracion,
                        DROP COLUMN registro_raiz,
                        DROP COLUMN es_bioequivalente;
                """)

                # 4. Grupos de equivalencia, desde la clave de texto
                cur.execute("""
                    CREATE TABLE grupos_equivalencia (
                        id SERIAL PRIMARY KEY,
                        principio_activo VARCHAR(255) NOT NULL,
                        concentracion VARCHAR(60) NOT NULL,
                        familia VARCHAR(50) NOT NULL,
                        envase VARCHAR(60) NOT NULL,
                        UNIQUE (principio_activo, concentracion, familia, envase));
                    INSERT INTO grupos_equivalencia (principio_activo, concentracion, familia, envase)
                    SELECT DISTINCT split_part(clave_equivalencia, '|', 1),
                                    split_part(clave_equivalencia, '|', 2),
                                    split_part(clave_equivalencia, '|', 3),
                                    split_part(clave_equivalencia, '|', 4)
                    FROM productos_farmacia WHERE clave_equivalencia IS NOT NULL
                    ORDER BY 1, 2, 3, 4;
                """)
                print(f"  grupos_equivalencia: {cur.rowcount}")

                # 5. Productos: claves foraneas en lugar de datos repetidos.
                # La forma propia solo se guarda si no hay una oficial.
                cur.execute("""
                    ALTER TABLE productos_farmacia
                        ADD COLUMN id_grupo INTEGER REFERENCES grupos_equivalencia(id) ON DELETE SET NULL,
                        ADD COLUMN id_forma INTEGER REFERENCES formas_farmaceuticas(id);
                    UPDATE productos_farmacia p SET id_grupo = g.id
                    FROM grupos_equivalencia g
                    WHERE p.clave_equivalencia = g.principio_activo || '|' || g.concentracion
                                                 || '|' || g.familia || '|' || g.envase;
                    UPDATE productos_farmacia p SET id_forma = f.id
                    FROM formas_farmaceuticas f
                    WHERE f.nombre = p.forma_farmaceutica
                      AND NOT EXISTS (SELECT 1 FROM medicamentos m
                                      WHERE m.id = p.id_medicamento AND m.id_forma IS NOT NULL);
                    ALTER TABLE productos_farmacia
                        DROP COLUMN registro_raiz,
                        DROP COLUMN forma_farmaceutica,
                        DROP COLUMN familia,
                        DROP COLUMN via_administracion,
                        DROP COLUMN concentracion_valor,
                        DROP COLUMN concentracion_unidad,
                        DROP COLUMN referencia_valor,
                        DROP COLUMN referencia_unidad,
                        DROP COLUMN clave_equivalencia;
                    CREATE INDEX idx_productos_grupo ON productos_farmacia (id_grupo);
                """)

                # 6. Precio unitario: se calcula en las vistas
                cur.execute("ALTER TABLE historico_precios DROP COLUMN precio_unitario")

                # 7. Vistas del esquema v3
                sql = ESQUEMA.read_text(encoding="utf-8")
                cur.execute(sql[sql.index("-- VISTAS"):])

                # Verificacion: las vistas deben entregar lo mismo
                cur.execute(CONTROL)
                control_despues = cur.fetchone()
                cur.execute("SELECT COUNT(*) FROM historico_precios")
                precios_despues = cur.fetchone()[0]
                print(f"Despues: {control_despues[1]} productos, {precios_despues} precios")

                if control_antes != control_despues or precios_antes != precios_despues:
                    raise SystemExit(
                        "La verificacion fallo: las vistas no entregan lo mismo. "
                        "Se deshace la migracion."
                    )

        print("\nMigracion completa y verificada.")
    finally:
        conexion.close()


if __name__ == "__main__":
    main()
