"""
Capa plata (Profar): normaliza el catálogo extraído cruzando directamente 
contra la base de datos PostgreSQL (tabla medicamentos) para máxima precisión.
"""

import csv
import json
import re
import unicodedata
from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine

RAIZ = Path(__file__).resolve().parents[2]
ENTRADA = RAIZ / "data" / "bronce"
SALIDA = RAIZ / "data" / "plata"

FORMAS = [
    "comprimidos recubiertos de liberacion prolongada", "comprimidos con recubrimiento enterico",
    "comprimidos de liberacion prolongada", "capsulas de liberacion prolongada",
    "comprimidos recubiertos", "comprimidos dispersables", "comprimidos masticables",
    "comprimidos sublinguales", "comprimidos efervescentes", "polvo para suspension oral",
    "polvo para solucion oral", "solucion para gotas orales", "solucion para nebulizacion",
    "suspension inyectable", "solucion inyectable", "suspension oral", "solucion oral",
    "solucion oftalmica", "solucion nasal", "solucion otica", "solucion topica",
    "capsulas blandas", "frasco ampolla", "comprimidos", "capsulas", "supositorios",
    "ampollas", "ovulos", "grageas", "jarabe", "unguento", "crema", "parches",
    "aerosol", "sobres", "gotas", "polvo", "gel",
]

PATRON_CONCENTRACION = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(mg|g|mcg|µg|UI|%)(?:\s*/\s*(\d+(?:[.,]\d+)?)?\s*(mL|ml|g|mg|dosis))?",
    re.IGNORECASE,
)

ENVASE_CONTABLE = r"(comprimidos|comprimido|comp|capsulas|capsula|sobres|sobre|supositorios|ovulos|ampollas|grageas|parches|tabletas)"
PATRON_UNIDADES = re.compile(r"\bx?\s*(\d+)\s+" + ENVASE_CONTABLE)

def sin_tildes(texto):
    n = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in n if unicodedata.category(c) != "Mn").strip()

def limpiar(texto):
    return re.sub(r"\s+", " ", (texto or "").replace("\xa0", " ")).strip()

def extraer_forma(texto):
    comparable = sin_tildes(texto)
    for forma in FORMAS:
        if forma in comparable:
            return forma
    return ""

def extraer_concentracion(texto):
    m = PATRON_CONCENTRACION.search(texto or "")
    if not m: return None, "", None, ""
    valor = float(m.group(1).replace(",", "."))
    unidad = m.group(2).lower()
    ref_valor = None
    ref_unidad = m.group(4) or ""
    if ref_unidad: ref_valor = float(m.group(3).replace(",", ".")) if m.group(3) else 1.0
    return valor, unidad, ref_valor, ref_unidad.lower()

def extraer_envase(nombre):
    texto = sin_tildes(nombre)
    m = PATRON_UNIDADES.search(texto)
    if m: return m.group(1), "comprimidos" if m.group(2) == "comp" else m.group(2)
    return "", ""

def cargar_datos_desde_bd(engine):
    """Carga el catálogo oficial completo desde PostgreSQL"""
    df = pd.read_sql_table('medicamentos', con=engine)
    mapa_isp = {}
    
    for _, row in df.iterrows():
        # Usamos registro_raiz según la estructura de tu BD
        reg = str(row['registro_raiz']).strip().upper()
        # Mapeamos temporalmente el nombre comercial en lugar del principio activo
        pa = str(row['nombre_comercial']).strip().upper()
        
        # Capturar el registro raíz de la BD (F-1234, B-1234, etc.)
        m = re.search(r'([A-Z]-\d+)', reg)
        if m and pa and pa.lower() != 'nan':
            mapa_isp[m.group(1)] = pa
            
    df['nombre_clean'] = df['nombre_comercial'].astype(str).str.upper().str.strip()
    return mapa_isp, df

def main():
    candidatos = sorted(ENTRADA.glob("profar_catalogo_*.json"))
    if not candidatos:
        print(f"No se encontró ningún catálogo en {ENTRADA}")
        return
    archivo = candidatos[-1]

    print(f"Leyendo {archivo.name}")
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    fecha = datos.get("fecha_muestreo", "")

    # CONEXIÓN A POSTGRESQL (Actualizado al puerto 5433)
    print("Conectando a PostgreSQL (puerto 5433) para cargar diccionario clínico...")
    engine = create_engine('postgresql://admin:password123@localhost:5433/bioequi_db')
    mapa_isp, df_meds = cargar_datos_desde_bd(engine)

    productos = []
    precios = []

    for p in datos.get("productos", []):
        nombre = limpiar(p.get("productName"))
        if not nombre: continue

        url_producto = p.get("pdpUrl", "")
        sku = url_producto.split('/')[-1].replace('.html', '') if url_producto else str(hash(nombre))

        principio = ""
        principio_origen = ""
        registro_raiz = ""
        registro_declarado = p.get("especificaciones", {}).get("Registro ISP", "")

        # Limpiar registro (Captura F-, B-, E-)
        if registro_declarado:
            match_limpio = re.search(r'([A-Z]-\d+)', registro_declarado, re.IGNORECASE)
            if match_limpio:
                registro_raiz = match_limpio.group(1).upper()
        else:
            match_reg = re.search(r'([A-Z]-\d{4,6})', json.dumps(p), re.IGNORECASE)
            if match_reg:
                registro_raiz = match_reg.group(1).upper()
                registro_declarado = registro_raiz

        # ESTRATEGIA 1: Cruce exacto por Registro ISP contra la BD
        if registro_raiz and registro_raiz in mapa_isp:
            principio = mapa_isp[registro_raiz]
            principio_origen = "registro_isp"

        # ESTRATEGIA 2: Especificaciones explícitas
        if not principio:
            pa_declarado = p.get("especificaciones", {}).get("Principio Activo", "")
            if pa_declarado:
                principio = pa_declarado.upper()
                principio_origen = "ficha_tecnica"

        # ESTRATEGIA 3: Cruce inteligente por Nombre Comercial
        if not principio:
            # Quitamos los símbolos extraños como (REF), *, -, etc.
            palabras_limpias = [re.sub(r'[^A-Z0-9]', '', w) for w in nombre.upper().split()]
            palabras_clave = [w for w in palabras_limpias if len(w) > 3]
            
            for palabra in palabras_clave:
                # Evitamos palabras genéricas que causen falsos positivos
                if palabra in ['PARA', 'COMO', 'FORMA', 'SOBRE', 'MGML']: continue
                
                candidatos_bd = df_meds[df_meds['nombre_clean'].str.contains(palabra, regex=False, na=False)]
                
                if not candidatos_bd.empty:
                    # Traemos el NOMBRE COMERCIAL del ISP
                    pa_encontrado = str(candidatos_bd.iloc[0]['nombre_comercial']).upper()
                    if pa_encontrado and pa_encontrado.lower() != 'nan':
                        principio = pa_encontrado
                        principio_origen = "nombre_comercial_bd"
                        break # Si encontró un match, dejamos de buscar palabras

        forma = extraer_forma(nombre)
        forma_origen = "nombre" if forma else ""
        valor, uni, ref_valor, ref_unidad = extraer_concentracion(nombre)
        cantidad, unidad = extraer_envase(nombre)

        productos.append({
            "id_producto": sku, "sku": sku, "nombre_publicado": nombre, "marca": "", 
            "url_producto": url_producto, "url_imagen": p.get("imageUrl", ""), "ean": "",
            "registro_declarado": registro_declarado, "registro_raiz": registro_raiz,
            "principio_activo": principio, "principio_origen": principio_origen,
            "forma_farmaceutica": forma, "forma_origen": forma_origen,
            "concentracion_valor": valor if valor is not None else "", "concentracion_unidad": uni,
            "referencia_valor": ref_valor if ref_valor is not None else "", "referencia_unidad": ref_unidad,
            "cantidad_envase": cantidad, "unidad_envase": unidad, "clase_producto": "",
            "bioequivalente_declarado": bool(p.get("isBioequivalent")), "bioequivalente_tipo": "", "condicion_venta": "",
        })

        precio_oferta = p.get("price-sale-cl")
        if precio_oferta is not None and precio_oferta > 0:
            precios.append({
                "id_producto": sku, "fecha_muestreo": fecha,
                "precio_normal": p.get("price-list-cl") or precio_oferta,
                "precio_oferta": precio_oferta, "disponible": True, 
            })

    SALIDA.mkdir(parents=True, exist_ok=True)
    for nombre_archivo, filas in [("profar_productos.csv", productos), ("profar_precios.csv", precios)]:
        with (SALIDA / nombre_archivo).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
            w.writeheader()
            w.writerows(filas)

    total = len(productos)
    con_reg = sum(1 for x in productos if x["registro_raiz"])
    con_pri = sum(1 for x in productos if x["principio_activo"])
    origen_isp = sum(1 for x in productos if x["principio_origen"] == "registro_isp")
    origen_bd = sum(1 for x in productos if x["principio_origen"] == "nombre_comercial_bd")

    print(f"\n{total} productos normalizados")
    print(f"  con registro ISP detectado:  {con_reg:4} ({100*con_reg/total if total else 0:.1f}%)")
    print(f"  vinculados exitosamente:     {con_pri:4} ({100*con_pri/total if total else 0:.1f}%)")
    print(f"  -> cruzados por código ISP:  {origen_isp:4} ({100*origen_isp/total if total else 0:.1f}%)")
    print(f"  -> cruzados por nombre BD:   {origen_bd:4} ({100*origen_bd/total if total else 0:.1f}%)")
    print(f"\n¡Archivos CSV generados en data/plata listos para subir a la BD!")

if __name__ == "__main__":
    main()