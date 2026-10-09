"""
Capa bronce: descarga el catálogo completo de medicamentos de Cruz Verde
utilizando su API interna descubierta mediante ingeniería inversa.
"""

import json
import time
from datetime import date
from pathlib import Path
import requests

URL_API = "https://api.cruzverde.cl/product-service/products/search"
DESTINO = Path(__file__).resolve().parents[2] / "data" / "bronce"

POR_PAGINA = 50  # Ampliamos el límite por petición para ser más rápidos
PAUSA = 2
MAX_PAGINAS = 100  # Tope de seguridad (5000 productos)

CABECERAS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-CL,es-419;q=0.9,es;q=0.8,en;q=0.7",
    "Origin": "https://www.cruzverde.cl",
    "Referer": "https://www.cruzverde.cl/",
    "sec-ch-ua": '"Chromium";v="154", "Google Chrome";v="154", "Not A(Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "Cookie": "visid_incap_3139068=oCl8lmZIR+GbyOuLVdTeUcFAn2oAAAAAQUIPAAAAAAA4TMX4NTXmvhAI+01DFLiA; _gcl_au=1.1.1057299671.1788821701; _ga=GA1.1.655145421.1788821701; _fbp=fb.1.1788821701298.1240141483; visid_incap_3140215=heQiUtInSQOY4csNvwAN28RAn2oAAAAAQUIPAAAAAAD5H2AEDr2II3VSlgmHTTnM; _hjSessionUser_1614665=eyJpZCI6ImMyMTRkYmZjLWMyZjItNWJkYi1hMjY1LTg1ODEyYTBjZDEzNSIsImNyZWF0ZWQiOjE3ODg4MjE3MDE0MTUsImV4aXN0aW5nIjp0cnVlfQ==; _ga_GMKXQPNSW5=GS2.1.s1788881652$o2$g1$t1788883731$j60$l0$h2068356593; _tt_enable_cookie=1; _ttp=01M3WC285HX9Q24YNRHJ7KJFT2_.tt.1.1790879801521; byyd_au=1.1.810003273.1790879803; byyd_ga=GA1.1.655145421.1788821701; nlbi_3139068=Az7vMRbxcXmeuUmH2rCdXQAAAACRpQE0x6XmpymB8XmWHm+9; incap_ses_623_3139068=ciCTKPhuAgKuEbalPlelCEYJxGoAAAAAiMHsMAhLhCWOdoDcqKzxjg==; _ga_CVCL=GS2.1.s1791232326$o7$g0$t1791232326$j60$l0$h478384714; nlbi_3140215=bNnPEE42ez8IDDwHxkkkqQAAAABp7I4rp6EYPFyB/ske3Upc; incap_ses_623_3140215=Z06wGNgCuWNqFbalPlelCEYJxGoAAAAAcWZJVfNLD3yWOIT8DGJ4SQ==; connect.sid=s%3Acruzverde-d0c334db-e188-4a80-9a83-87005484c8b7.cO%2FIk66Ih%2BNJpGqJdbgTSPFSbIB0HD%2BTFjSZQR2mhkg; _hjSession_1614665=eyJpZCI6IjVmZjVjZmQ0LWY0OGQtNGRjMy1iMTljLWZkOTY3M2I5NmE1YSIsImMiOjE3OTEyMzIzMjgzMDMsInMiOjAsInIiOjAsInNiIjowLCJzciI6MCwic2UiOjAsImZzIjowLCJzcCI6MH0=; ttcsid_D0EEUDRC77UCMMV6IDS0=1791232328409::-aPv8jrYRSnKF_6oRJdD.2.1791232341152.1; byyd_ga_GMKXQPNSW5=GS2.1.s1791232327$o3$g1$t1791232355$j32$l0$h929414941; ttcsid=1791232328409::BYSBVtY8tdoMPCztbDDG.2.1791232341152.0::1.10540.0::32032.4.226.10603::29517.33.10401"
}

def extraer_medicamentos():
    productos_totales = []
    offset = 0
    intentos = 0             

    print("Iniciando extracción masiva del catálogo de Cruz Verde...")

    for pagina in range(MAX_PAGINAS):
        print(f"  Pidiendo productos desde {offset} a {offset + POR_PAGINA - 1}...")
        
        parametros = {
            "limit": POR_PAGINA,
            "offset": offset,
            "sort": "",
            "q": "",
            "refine[]": "cgid=ver-todo-medicamentos",
            "isAndes": "true",
            "requestPage": "CLP",
            "andesUserId": "abl0kZlupGwrgRl0s2xaYYxbkZ",
            "inventoryId": "Zonapañales1119",
            "inventoryZone": "Zonapañales1119"
        }

        try:
            respuesta = requests.get(URL_API, params=parametros, headers=CABECERAS, timeout=20)
            respuesta.raise_for_status()
            
            datos = respuesta.json()
            
            # Ajusta la clave según cómo venga el JSON. Usualmente viene en una lista 'hits' o 'products'
            items = datos.get("hits", datos.get("products", []))
            
            if not items:
                print("Se alcanzó el final del catálogo.")
                break
                
            productos_totales.extend(items)
            offset += POR_PAGINA
            intentos = 0
            time.sleep(PAUSA)
            
        except requests.exceptions.RequestException as e:
            # Un 503 suele ser transitorio: conviene reintentar antes de
            # abandonar, porque cortar deja el catalogo incompleto y eso
            # falsea la comparacion entre fechas
            codigo = getattr(e.response, "status_code", None)

            if codigo in (429, 500, 502, 503, 504) and intentos < 3:
                intentos += 1
                espera = PAUSA * 5 * intentos
                print(f"    {codigo} en offset {offset}, reintento "
                      f"{intentos}/3 en {espera}s")
                time.sleep(espera)
                continue

            print(f"Error de conexion en la pagina {pagina}: {e}")
            print(f"ATENCION: descarga incompleta, {len(productos_totales)} productos")
            break

    return productos_totales

def main():
    productos = extraer_medicamentos()
    
    if not productos:
        print("No se encontraron productos. Revisa la estructura de la respuesta JSON.")
        return

    DESTINO.mkdir(parents=True, exist_ok=True)
    archivo = DESTINO / f"cruzverde_catalogo_{date.today().isoformat()}.json"

    archivo.write_text(
        json.dumps(
            {
                "fuente": "cruzverde.cl",
                "categoria_raiz": "ver-todo-medicamentos",
                "fecha_muestreo": date.today().isoformat(),
                "total": len(productos),
                "productos": productos,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\n¡Éxito! {len(productos)} productos únicos guardados en:\n  {archivo}")

if __name__ == "__main__":
    main()