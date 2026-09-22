import json
import glob
import re
from pathlib import Path
from datetime import date
import pandas as pd
from sqlalchemy import create_engine, text

def extraer_mg(texto):
    """Extrae el primer valor numérico seguido de mg o g que encuentre en el texto y lo estandariza a mg."""
    match = re.search(r'(\d+)\s*(mg|g)', texto, re.IGNORECASE)
    if match:
        val, unidad = match.groups()
        return int(val) * 1000 if unidad.lower() == 'g' else int(val)
    return None

def procesar_json_simi():
    print("Conectando a la base de datos PostgreSQL...")
    engine = create_engine('postgresql://admin:password123@localhost:5432/bioequi_db')

    # 1. Buscar el archivo JSON más reciente en data/bronce/
    ruta_bronce = Path(__file__).resolve().parent / "data" / "bronce"
    archivos_json = glob.glob(str(ruta_bronce / "drsimi_catalogo_*.json"))
    
    if not archivos_json:
        print(f"Error: No se encontró ningún archivo JSON de catálogo en {ruta_bronce}")
        return

    archivo_reciente = max(archivos_json, key=lambda p: Path(p).stat().st_mtime)
    print(f"Leyendo archivo: {archivo_reciente}")

    with open(archivo_reciente, 'r', encoding='utf-8') as f:
        datos = json.load(f)

    productos_raw = datos.get("productos", [])
    print(f"Total de productos en el JSON: {len(productos_raw)}")

    # 2. Cargar los medicamentos de la base de datos
    print("Cargando catálogo interno de la BD...")
    df_meds = pd.read_sql_table('medicamentos', con=engine)
    df_meds['nombre_clean'] = df_meds['nombre_comercial'].str.upper().str.strip()
    
    match_data = []

    for p in productos_raw:
        nombre_simi = p.get("productName", "").strip().upper()
        mg_simi = extraer_mg(nombre_simi)
        
        try:
            items = p.get("items", [])
            if not items:
                continue
            seller = items[0].get("sellers", [])[0]
            comm_offer = seller.get("commertialOffer", {})
            
            precio_oferta = comm_offer.get("Price", 0)
            precio_normal = comm_offer.get("ListPrice", precio_oferta)
            url_producto = p.get("link", "")
            sku = items[0].get("itemId", "")
            
            if precio_oferta == 0:
                continue
        except (IndexError, TypeError):
            continue

        palabras_clave = [palabra for palabra in nombre_simi.split() if len(palabra) > 3]
        if not palabras_clave:
            continue
        
        palabra_principal = palabras_clave[0]
        
        # Filtrar candidatos por palabra clave principal
        candidatos = df_meds[df_meds['nombre_clean'].str.contains(palabra_principal, regex=False, na=False)]
        
        if not candidatos.empty:
            # Si el producto de la farmacia tiene concentración en mg, exigimos que el ISP también la tenga
            if mg_simi:
                coincidencia = candidatos[candidatos['nombre_clean'].str.contains(str(mg_simi), regex=False, na=False)]
            else:
                coincidencia = candidatos

            if not coincidencia.empty:
                med_id = int(coincidencia.iloc[0]['id'])
                match_data.append({
                    'id_medicamento': med_id,
                    'id_farmacia': 1,  # ID 1 = Dr. Simi
                    'sku_farmacia': str(sku),
                    'nombre_publicado': str(p.get("productName", "")),
                    'url_producto': url_producto,
                    'precio_normal': float(precio_normal),
                    'precio_oferta': float(precio_oferta),
                    'fecha_muestreo': date.today().isoformat(),
                    'disponible': True
                })

    df_matches = pd.DataFrame(match_data)
    if not df_matches.empty:
        df_matches.drop_duplicates(subset=['sku_farmacia'], inplace=True)

    print(f"Total de coincidencias estrictas (por nombre y concentración) encontradas: {len(df_matches)}")

    if len(df_matches) == 0:
        print("Aviso: No se encontraron coincidencias bajo los nuevos filtros.")
        return

    # 3. Inserción limpia en PostgreSQL (limpiando tablas previas opcionalmente o haciendo upsert)
    print("Insertando registros en PostgreSQL...")
    with engine.begin() as connection:
        # Opcional: limpiar tablas para evitar duplicados de pruebas anteriores
        connection.execute(text("TRUNCATE TABLE historico_precios, productos_farmacia RESTART IDENTITY CASCADE;"))

        for _, row in df_matches.iterrows():
            query_prod = text("""
                INSERT INTO productos_farmacia (id_medicamento, id_farmacia, nombre_publicado, url_producto, disponible)
                VALUES (:med_id, :farm_id, :nombre_pub, :url, :disp)
                RETURNING id;
            """)
            result = connection.execute(query_prod, {
                "med_id": row['id_medicamento'],
                "farm_id": row['id_farmacia'],
                "nombre_pub": row['nombre_publicado'],
                "url": row['url_producto'],
                "disp": row['disponible']
            }).fetchone()
            
            prod_farmacia_id = result[0]

            query_precio = text("""
                INSERT INTO historico_precios (id_producto, precio_normal, precio_oferta, fecha_muestreo)
                VALUES (:prod_id, :p_norm, :p_of, :f_muestreo);
            """)
            connection.execute(query_precio, {
                "prod_id": prod_farmacia_id,
                "p_norm": row['precio_normal'],
                "p_of": row['precio_oferta'],
                "f_muestreo": row['fecha_muestreo']
            })

    print("¡Proceso ETL estricto completado con éxito! Revisa DBeaver.")

if __name__ == "__main__":
    procesar_json_simi()