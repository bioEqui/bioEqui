"""
Capa bronce: descarga el catalogo de medicamentos de la farmacia de la
Liga Chilena contra la Epilepsia (ligafarmacia.cl).

El sitio es una aplicacion React que no trae los productos en el HTML:
los lee desde Firestore (Firebase), en un documento por sucursal. Se
consulta ese mismo documento por la API REST publica de Firestore, igual
que lo hace el navegador al abrir /medicamentos.

    publico_test/<presku>             catalogo completo de la sucursal
    publico/fotos_medicamentos_new    imagenes de todos los productos

Cada sucursal tiene su propio catalogo, precio y stock. Se usa Erasmo
Escala (Santiago), que es la sucursal por defecto del sitio.

Salida:
    data/bronce/liga_catalogo_AAAA-MM-DD.json

Uso:
    python descargar_catalogo_liga.py
"""

import json
from datetime import date
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DESTINO = Path(__file__).resolve().parents[2] / "data" / "bronce"

# Clave publica de Firebase: viene en el codigo del sitio y es la que usa
# cualquier navegador que lo visita. No da acceso a nada que no sea publico.
API_KEY = "AIzaSyAfbpNYcGMtQQ8mPROKzNYXBafkO-lnfEI"
URL_FIRESTORE = (
    "https://firestore.googleapis.com/v1/projects/farmstore-744f9"
    "/databases/(default)/documents"
)

SUCURSAL = "Erasmo Escala (Santiago)"
PRESKU = "new_presku02"

URL_SITIO = "https://ligafarmacia.cl"

CABECERAS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": URL_SITIO + "/",
    "Origin": URL_SITIO,
}

session = requests.Session()
retries = Retry(
    total=5,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
)
session.mount("https://", HTTPAdapter(max_retries=retries))


def valor(campo):
    """
    Firestore envuelve cada valor en su tipo: {"stringValue": "..."},
    {"integerValue": "64"}, {"mapValue": {"fields": ...}}. Se desenvuelve
    a un valor Python normal.
    """
    tipo, v = next(iter(campo.items()))
    if tipo == "mapValue":
        return {k: valor(x) for k, x in v.get("fields", {}).items()}
    if tipo == "arrayValue":
        return [valor(x) for x in v.get("values", [])]
    if tipo == "integerValue":
        return int(v)
    if tipo == "nullValue":
        return None
    return v


def leer_documento(ruta):
    respuesta = session.get(
        f"{URL_FIRESTORE}/{ruta}",
        params={"key": API_KEY},
        headers=CABECERAS,
        timeout=60,
    )
    respuesta.raise_for_status()
    return {k: valor(v) for k, v in respuesta.json().get("fields", {}).items()}


def asignar_imagenes(productos, fotos):
    """
    Las imagenes se guardan aparte. El sitio las cruza por kinf y los
    ultimos cuatro digitos de kinf2 (el tamanio del envase), y se replica
    esa misma regla.
    """
    por_clave = {(f.get("kinf"), f.get("kinf2", "")[-4:]): f for f in fotos}
    for p in productos:
        foto = por_clave.get((p.get("kinf"), p.get("kinf2", "")[-4:]))
        p["imagenes"] = [URL_SITIO + i for i in (foto or {}).get("image", [])]


def main():
    print(f"Descargando catalogo de Liga, sucursal {SUCURSAL}...")
    catalogo = leer_documento(f"publico_test/{PRESKU}")
    productos = catalogo.get("sku", [])
    print(f"  {len(productos)} productos")

    print("Descargando imagenes...")
    fotos = leer_documento("publico/fotos_medicamentos_new").get("images_med", [])
    asignar_imagenes(productos, fotos)
    con_imagen = sum(1 for p in productos if p["imagenes"])
    print(f"  {con_imagen} productos con imagen")

    if not productos:
        print("No se encontraron productos.")
        return

    DESTINO.mkdir(parents=True, exist_ok=True)
    archivo = DESTINO / f"liga_catalogo_{date.today().isoformat()}.json"

    archivo.write_text(
        json.dumps(
            {
                "fuente": "ligafarmacia.cl",
                "sucursal": SUCURSAL,
                "presku": PRESKU,
                "fecha_muestreo": date.today().isoformat(),
                "fecha_actualiza_fuente": catalogo.get("fecha_actualiza", ""),
                "total": len(productos),
                "productos": productos,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\n{len(productos)} productos guardados en: {archivo}")


if __name__ == "__main__":
    main()
