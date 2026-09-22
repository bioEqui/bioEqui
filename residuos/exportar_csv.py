import pandas as pd
from sqlalchemy import create_engine

def generar_csv():
    print("Conectando a PostgreSQL...")
    engine = create_engine('postgresql://admin:password123@localhost:5432/bioequi_db')

    print("Extrayendo tabla 'medicamentos'...")
    # Leemos la tabla directamente desde la base de datos
    df_medicamentos = pd.read_sql_table('medicamentos', con=engine)

    # Definimos la ruta de salida
    ruta_salida = 'data/catalogo_medicamentos.csv'
    
    # Exportamos a CSV. 
    # Usamos utf-8-sig para que Excel en Windows lea bien los tildes (á, é, í, ó, ú).
    df_medicamentos.to_csv(ruta_salida, index=False, encoding='utf-8-sig')

    print(f"¡Listo! Se generó el archivo CSV con {len(df_medicamentos)} registros en: {ruta_salida}")

if __name__ == "__main__":
    generar_csv()