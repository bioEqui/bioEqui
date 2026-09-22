import pandas as pd
from sqlalchemy import create_engine
import os

def unificar_e_insertar_isp():
    print("Conectando a la base de datos PostgreSQL local...")
    engine = create_engine('postgresql://admin:password123@localhost:5432/bioequi_db')

    # Función adaptada para leer tablas HTML 
    def cargar_html_gubernamental(nombre_base):
        ruta = f"data/{nombre_base}.xls"
        if os.path.exists(ruta):
            # read_html devuelve una lista de tablas
            return pd.read_html(ruta)[0]
        else:
            raise FileNotFoundError(f"No se encontró el archivo {ruta}")

    try:
        print("Cargando y decodificando archivos del ISP...")
        df_ref = cargar_html_gubernamental('Referentes')
        df_eq = cargar_html_gubernamental('Alternativas')
        df_hib = cargar_html_gubernamental('Hibridos')
    except Exception as e:
        print(f"Error de lectura: {e}")
        return

    # 1. Asignar el valor booleano
    df_ref['es_bioequivalente'] = False
    df_eq['es_bioequivalente'] = True
    df_hib['es_bioequivalente'] = True

    # 2. Unificar los tres dataframes
    df_master = pd.concat([df_ref, df_eq, df_hib], ignore_index=True)
    
    # 3. Inyectar el estado "Vigente"
    df_master['Estado'] = 'Vigente'
    
    # 4. Mapear las columnas hacia SQL
    df_clean = df_master[['Registro', 'Nombre', 'Empresa', 'Estado', 'es_bioequivalente']].copy()
    df_clean.rename(columns={
        'Registro': 'registro_sanitario',
        'Nombre': 'nombre_comercial',
        'Empresa': 'laboratorio',
        'Estado': 'estado_registro'
    }, inplace=True)

    # 5. Eliminar duplicados
    df_clean.drop_duplicates(subset=['registro_sanitario'], inplace=True)

    print(f"Total de medicamentos procesados: {len(df_clean)}")

    # 6. Inyección a PostgreSQL
    try:
        df_clean.to_sql('medicamentos', con=engine, if_exists='append', index=False)
        print("¡Inserción exitosa! Base de datos poblada.")
    except Exception as e:
        print(f"Fallo en la base de datos: {e}")

if __name__ == "__main__":
    unificar_e_insertar_isp()