import pandas as pd
from sqlalchemy import create_engine

def poblar_base_relacional():
    print("Conectando a PostgreSQL...")
    engine = create_engine('postgresql://admin:password123@localhost:5432/bioequi_db')

    print("Leyendo archivos normalizados del ISP...")
    df_meds = pd.read_csv("data/isp_medicamentos.csv", sep=None, engine='python', encoding='utf-8')
    df_comp = pd.read_csv("data/isp_composicion.csv", sep=None, engine='python', encoding='utf-8')

    with engine.begin() as conn:
        # 1. Poblar tabla 'medicamentos'
        print(f"Insertando {len(df_meds)} registros en 'medicamentos'...")
        df_m_to_sql = df_meds[['registro_sanitario', 'nombre_comercial', 'laboratorio', 'forma_farmaceutica', 'es_bioequivalente', 'categoria_isp']].copy()
        df_m_to_sql.rename(columns={'categoria_isp': 'estado_registro'}, inplace=True)
        df_m_to_sql.to_sql('medicamentos', conn, if_exists='append', index=False)

        # 2. Poblar tabla 'principios_activos' (valores únicos DCI)
        print("Insertando principios activos únicos...")
        principios_unicos = df_comp['principio_activo'].dropna().str.upper().str.strip().unique()
        df_pa = pd.DataFrame({'nombre_dci': principios_unicos})
        df_pa.to_sql('principios_activos', conn, if_exists='append', index=False)

        # Recuperar IDs generados automáticamente por la base de datos
        meds_db = pd.read_sql("SELECT id as id_medicamento, registro_sanitario FROM medicamentos", conn)
        pa_db = pd.read_sql("SELECT id as id_principio_activo, nombre_dci FROM principios_activos", conn)

        # Normalizar texto para el cruce
        df_comp['principio_activo_clean'] = df_comp['principio_activo'].str.upper().str.strip()
        pa_db['nombre_dci_clean'] = pa_db['nombre_dci'].str.upper().str.strip()

        # 3. Cruzar para poblar la tabla intermedia 'composicion'
        print("Construyendo relaciones en la tabla 'composicion'...")
        df_merge = df_comp.merge(df_meds, on='registro_raiz', how='inner')
        df_merge = df_merge.merge(meds_db, on='registro_sanitario', how='inner')
        df_merge = df_merge.merge(pa_db, left_on='principio_activo_clean', right_on='nombre_dci_clean', how='inner')

        df_composicion = df_merge[['id_medicamento', 'id_principio_activo', 'concentracion_valor', 'concentracion_unidad']].copy()
        df_composicion.rename(columns={'concentracion_unidad': 'unidad_medida'}, inplace=True)
        
        # Eliminar posibles duplicados de composición
        df_composicion.drop_duplicates(subset=['id_medicamento', 'id_principio_activo'], inplace=True)
        
        df_composicion.to_sql('composicion', conn, if_exists='append', index=False)

    print("¡Modelo relacional del ISP cargado y enlazado correctamente!")

if __name__ == "__main__":
    poblar_base_relacional()