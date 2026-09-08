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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
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
    "Cookie": "visid_incap_3139068=oCl8lmZIR+GbyOuLVdTeUcFAn2oAAAAAQUIPAAAAAAA4TMX4NTXmvhAI+01DFLiA; _gcl_au=1.1.1057299671.1788821701; _ga=GA1.1.655145421.1788821701; _fbp=fb.1.1788821701298.1240141483; visid_incap_3140215=heQiUtInSQOY4csNvwAN28RAn2oAAAAAQUIPAAAAAAD5H2AEDr2II3VSlgmHTTnM; _hjSessionUser_1614665=eyJpZCI6ImMyMTRkYmZjLWMyZjItNWJkYi1hMjY1LTg1ODEyYTBjZDEzNSIsImNyZWF0ZWQiOjE3ODg4MjE3MDE0MTUsImV4aXN0aW5nIjp0cnVlfQ==; nlbi_3139068=5TXRIIBDC0yYTiPz2rCdXQAAAACOyfXmJ52yMJ3zaOUC2ofa; incap_ses_765_3139068=TIIXWPAQsygf4GUXDNSdCvQqoGoAAAAADyr89kJkgtLQVHM4nG52ng==; _hjSession_1614665=eyJpZCI6IjUzN2YwZTE2LWUzNmUtNDNjMS1hNzEwLWYyY2RjZjAxYzhhZSIsImMiOjE3ODg4ODE2NTIzMDIsInMiOjAsInIiOjAsInNiIjowLCJzciI6MCwic2UiOjAsImZzIjowLCJzcCI6MH0=; nlbi_3140215=hNUrdmtn6ipCxP8TxkkkqQAAAAB5JmGNUlgIJW2/VPm2IBVf; incap_ses_765_3140215=Ru+6K7TMJSMM0WYXDNSdCvUqoGoAAAAAyGDvR1pcYpfBPexwlJLOmA==; connect.sid=s%3Acruzverde-672b04ab-db6e-4213-91a2-5659059969e8.k2%2FuKz8KtnDMbFWPxaOLvdwfVPtZKvekeHHSS7Re5gU; _ga_CVCL=GS2.1.s1788881652$o3$g1$t1788881990$j59$l0$h1846661923; _ga_GMKXQPNSW5=GS2.1.s1788881652$o2$g1$t1788882067$j59$l0$h2068356593"
}

def extraer_medicamentos():
    productos_totales = []
    offset = 0

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
            "andesUserId": "ablew1xrc2xroRwKpHmqYYkbFJ",
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
            time.sleep(PAUSA)
            
        except requests.exceptions.RequestException as e:
            print(f"Error de conexión en la página {pagina}: {e}")
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