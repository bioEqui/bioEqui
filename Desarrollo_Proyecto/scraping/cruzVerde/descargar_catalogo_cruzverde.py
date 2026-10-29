"""
Capa bronce: descarga el catálogo completo de medicamentos de Cruz Verde
utilizando su API interna descubierta mediante ingeniería inversa.
"""

import json
import os
import sys
import time
from datetime import date
from pathlib import Path
import requests
from dotenv import load_dotenv

URL_API = "https://api.cruzverde.cl/product-service/products/search"
RAIZ = Path(__file__).resolve().parents[2]
DESTINO = RAIZ / "data" / "bronce"

# La cookie es de una sesion de navegador: es personal, caduca y no se
# versiona. Se lee desde el .env (variable CRUZVERDE_COOKIE).
load_dotenv(RAIZ / ".env")
COOKIE = os.getenv("CRUZVERDE_COOKIE", "")
if not COOKIE:
    sys.exit(
        "Falta CRUZVERDE_COOKIE en el .env. Copiala desde DevTools > Network "
        "en cualquier peticion a api.cruzverde.cl."
    )

POR_PAGINA = 50  # Límite de petición
PAUSA = 2  # Pausa entre peticiones para no saturar el servidor
MAX_PAGINAS = 100  # Tope de seguridad 

CABECERAS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-CL,es-419;q=0.9,es;q=0.8,en;q=0.7",
    "Origin": "https://www.cruzverde.cl",
    "Referer": "https://www.cruzverde.cl/",
    "sec-ch-ua": '"Google Chrome";v="155", "Chromium";v="155", "Not(A:Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "Cookie": COOKIE,
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