"""
Capa bronce: descarga el catálogo completo de medicamentos de Farmacias Profar
utilizando Web Scraping (BeautifulSoup) sobre el HTML de Magento.
Incluye navegación a la vista de detalle y Sesión con Reintentos automáticos.
"""

import json
import time
from datetime import date
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

DESTINO = Path(__file__).resolve().parents[2] / "data" / "bronce"

URL_BASE = "https://www.profar.cl/medicamentos.html"
MAX_PAGINAS = 30  
PAUSA_PAGINA = 2
PAUSA_PRODUCTO = 0.5

CABECERAS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-CL,es;q=0.9",
}

# Configuración de Sesión con Reintentos (Tolerancia a microcortes de internet)
session = requests.Session()
retries = Retry(
    total=5,  # Reintentar 5 veces en caso de fallo
    backoff_factor=1,  # Esperar 1s, 2s, 4s, 8s entre reintentos
    status_forcelist=[429, 500, 502, 503, 504], # Reintentar si el servidor se satura
    allowed_methods=["GET"]
)
session.mount('http://', HTTPAdapter(max_retries=retries))
session.mount('https://', HTTPAdapter(max_retries=retries))

def extraer_profar():
    productos_totales = []
    
    print("Iniciando extracción masiva de Profar (HTML/Magento)...")
    print("Protección contra microcortes de red ACTIVADA.")

    for pagina in range(1, MAX_PAGINAS + 1):
        print(f"\nScrapeando página {pagina}...")
        url_paginada = f"{URL_BASE}?p={pagina}"
        
        try:
            # Usamos la sesión blindada
            respuesta = session.get(url_paginada, headers=CABECERAS, timeout=20)
            respuesta.raise_for_status()
            
            soup = BeautifulSoup(respuesta.text, 'html.parser')
            cajas_productos = soup.find_all('div', class_='product-item-info')
            
            if not cajas_productos:
                print(f"No se encontraron más productos en la página {pagina}. Fin del catálogo.")
                break
                
            for caja in cajas_productos:
                try:
                    etiqueta_a = caja.find('a', class_='product-item-link')
                    if not etiqueta_a: continue 
                        
                    nombre = etiqueta_a.text.strip()
                    url_producto = etiqueta_a.get('href', '')

                    precio_oferta = None
                    span_final = caja.find('span', {'data-price-type': 'finalPrice'})
                    if span_final and span_final.has_attr('data-price-amount'):
                        precio_oferta = int(float(span_final['data-price-amount']))

                    precio_normal = None
                    span_old = caja.find('span', {'data-price-type': 'oldPrice'})
                    if span_old and span_old.has_attr('data-price-amount'):
                        precio_normal = int(float(span_old['data-price-amount']))
                    else:
                        precio_normal = precio_oferta

                    img_tag = caja.find('img', class_='product-image-photo')
                    url_imagen = img_tag.get('src', '') if img_tag else ""

                    es_bioequivalente = False
                    div_bio = caja.find('div', class_='bioequivalente')
                    if div_bio and 'not-bioequivalente' not in div_bio.get('class', []):
                        es_bioequivalente = True

                    especificaciones = {}
                    if url_producto:
                        time.sleep(PAUSA_PRODUCTO)
                        try:
                            # Reintento también en el detalle del producto
                            resp_det = session.get(url_producto, headers=CABECERAS, timeout=15)
                            if resp_det.status_code == 200:
                                soup_det = BeautifulSoup(resp_det.text, 'html.parser')
                                for item in soup_det.find_all('div', class_='pf-spec-item'):
                                    lbl = item.find('div', class_='pf-spec-label')
                                    val = item.find('div', class_='pf-spec-value')
                                    if lbl and val:
                                        especificaciones[lbl.text.strip()] = val.text.strip()
                        except Exception as e_det:
                            print(f"    [!] Fallo final de red al leer detalle de {nombre[:30]}... : {e_det}")

                    productos_totales.append({
                        "productName": nombre,
                        "price-sale-cl": precio_oferta,
                        "price-list-cl": precio_normal,
                        "pdpUrl": url_producto,
                        "imageUrl": url_imagen,
                        "isBioequivalent": es_bioequivalente,
                        "especificaciones": especificaciones 
                    })
                    
                    print(f"  ✓ {nombre[:40]}... (ISP: {especificaciones.get('Registro ISP', 'No hallado')})")

                except Exception as e:
                    print(f"    Error parseando un producto: {e}")
                    continue

            time.sleep(PAUSA_PAGINA)
            
        except requests.exceptions.RequestException as e:
            print(f"Error de red crítico en la página {pagina} después de varios reintentos: {e}")
            break

    return productos_totales

def main():
    productos = extraer_profar()
    
    if not productos:
        print("No se encontraron productos.")
        return

    DESTINO.mkdir(parents=True, exist_ok=True)
    archivo = DESTINO / f"profar_catalogo_{date.today().isoformat()}.json"

    archivo.write_text(
        json.dumps(
            {
                "fuente": "profar.cl",
                "categoria_raiz": "medicamentos",
                "fecha_muestreo": date.today().isoformat(),
                "total": len(productos),
                "productos": productos,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\n¡Éxito! {len(productos)} productos guardados en: {archivo}")

if __name__ == "__main__":
    main()