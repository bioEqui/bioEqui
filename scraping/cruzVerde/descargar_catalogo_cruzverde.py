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
    "User-Agent": "bioEqui-academico/0.1 (proyecto universitario)",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-CL,es-419;q=0.9,es;q=0.8,en;q=0.7",
    "Origin": "https://www.cruzverde.cl",
    "Referer": "https://www.cruzverde.cl/",
    "sec-ch-ua": '"Chromium";v="152", "Not?A_Brand";v="24", "Google Chrome";v="152"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "Cookie": "_ga=GA1.1.26501606.1771881384; visid_incap_3139068=hS8LO6kJRoipTnwtFk+hgRragGoAAAAAQUIPAAAAAABCF9LM+cKL0UYa/Q27tpmU; _fbp=fb.1.1786829337059.4200813829; _gcl_au=1.1.34965926.1786829337; visid_incap_3140215=uxxo6B6HQ2CsDGfoCKVxQhvagGoAAAAAQUIPAAAAAAC+JeOlyqoUrwHJ4GjWFy+L; _tt_enable_cookie=1; _ttp=01M03N7ZHFKTVHEZRM2FS7MRSB_.tt.1; _hjMinimizedPolls=1860980; _hjDonePolls=1860980; _hjSessionUser_1614665=eyJpZCI6IjcyMTBjNTljLTUyNjItNWNmYy1iMzBiLWMzMjJiNGI3ZjMyMiIsImNyZWF0ZWQiOjE3ODY4MjkzMzk5MzcsImV4aXN0aW5nIjp0cnVlfQ==; ttcsid_D0EEUDRC77UCMMV6IDS0=1786829340244::GWfRKXEjA0gL7Y2fFFut.1.1786829499541.1; ttcsid=1786829340245::9ZAHI-tRfHB1RKrd7kC2.1.1786829496491.0::1.153128.154870::99509.20.1149.11176::174091.87.2200; nlbi_3139068=Oc4uebDNd2Dq7nYG2rCdXQAAAAA6guwmvy4loDLUrqCaEwoj; nlbi_3140215=C1JffE7L8h3kqscqxkkkqQAAAABO1OTNQvQkXqP5T175uybf; connect.sid=s%3Acruzverde-65616d67-ff87-44fa-a2c7-e41b22c35cb6.Rsbn46BCGm3OdGNi5wVJrfON3zf8NfE6WTNUqjT7lhc; incap_ses_529_3140215=JrHvMi5xYBVPUWuCuWJXB2KasGoAAAAAoVa4bf2I09NOQ7t+qHTf5w==; incap_ses_529_3139068=CNwCYVCxpymsWWuCuWJXB2iasGoAAAAA4grb2/hWtn+JM7Tf7KXJ2g==; _hjSession_1614665=eyJpZCI6Ijg5YzE0ODhlLTc0ZmMtNGFlNS1iYTEzLWRlNjg4N2Q3Y2FlZSIsImMiOjE3ODk5NTg3NjM4ODMsInMiOjAsInIiOjAsInNiIjowLCJzciI6MCwic2UiOjAsImZzIjowLCJzcCI6MX0=; _ga_GMKXQPNSW5=GS2.1.s1789955741$o7$g1$t1789958830$j58$l0$h440315095; _ga_CVCL=GS2.1.s1789958763$o14$g1$t1789958830$j58$l0$h1795386338"
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