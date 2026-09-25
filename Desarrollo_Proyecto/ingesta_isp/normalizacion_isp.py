"""
Capa plata (ISP): normaliza el consolidado crudo del Instituto de Salud
Publica y lo deja listo para cruzar con las fuentes comerciales.

Entrada:
    data/bronce/isp_consolidado.csv

Salidas:
    data/plata/isp_medicamentos.csv   un registro sanitario por fila
    data/plata/isp_composicion.csv    un principio activo por fila

Transformaciones aplicadas:
    - Normaliza espacios y caracteres invisibles
    - Deriva el registro sin sufijo de anio, que es el formato que publican
      los sitios comerciales y permite el cruce
    - Traduce el listado de origen a condicion de bioequivalencia
    - Extrae forma farmaceutica y concentracion desde el nombre
    - Separa los principios activos compuestos en filas independientes

Uso:
    python normalizar_isp.py
"""

import csv
import re
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ENTRADA = RAIZ / "data" / "bronce" / "isp_consolidado.csv"
SALIDA = RAIZ / "data" / "plata"

# Que condicion de bioequivalencia implica cada listado.
# Los referentes son los productos contra los cuales se demuestra la
# equivalencia: no tienen certificacion propia.
BIOEQUIVALENCIA = {
    "referente": False,
    "alternativa": True,
    "hibrido": True,
}

# Formas farmaceuticas reconocidas. El orden importa: las variantes mas
# especificas van primero para que no las capture una mas general.
FORMAS = [
    "COMPRIMIDOS RECUBIERTOS DE LIBERACION PROLONGADA",
    "COMPRIMIDOS RECUBIERTOS DE LIBERACION MODIFICADA",
    "COMPRIMIDOS CON RECUBRIMIENTO ENTERICO",
    "COMPRIMIDOS DE LIBERACION PROLONGADA",
    "COMPRIMIDOS DE LIBERACION MODIFICADA",
    "CAPSULAS DE LIBERACION PROLONGADA",
    "COMPRIMIDOS RECUBIERTOS",
    "COMPRIMIDOS DISPERSABLES",
    "COMPRIMIDOS MASTICABLES",
    "COMPRIMIDOS SUBLINGUALES",
    "COMPRIMIDOS EFERVESCENTES",
    "POLVO PARA SOLUCION ORAL",
    "POLVO PARA SUSPENSION ORAL",
    "SOLUCION PARA GOTAS ORALES",
    "SOLUCION PARA INHALACION",
    "SOLUCION PARA NEBULIZACION",
    "LIOFILIZADO PARA SOLUCION INYECTABLE",
    "POLVO PARA SOLUCION INYECTABLE",
    "SOLUCION INYECTABLE",
    "SUSPENSION INYECTABLE",
    "SUSPENSION ORAL",
    "SOLUCION ORAL",
    "SOLUCION OFTALMICA",
    "SOLUCION TOPICA",
    "SOLUCION NASAL",
    "SOLUCION OTICA",
    "CAPSULAS BLANDAS",
    "CAPSULAS",
    "COMPRIMIDOS",
    "SUPOSITORIOS",
    "OVULOS",
    "GRAGEAS",
    "JARABE",
    "CREMA",
    "UNGUENTO",
    "GEL",
    "PARCHES",
    "AEROSOL",
    "POLVO",
    "GOTAS",
    "SOBRES",
]

# Concentracion simple (500 mg) o como razon (160 mg/5 mL)
PATRON_CONCENTRACION = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*"
    r"(mg|g|mcg|µg|UI|%)"
    r"(?:\s*/\s*(\d+(?:[.,]\d+)?)?\s*(mL|ml|g|mg|dosis))?",
    re.IGNORECASE,
)


def limpiar(texto):
    """Normaliza espacios y elimina caracteres invisibles."""
    return re.sub(r"\s+", " ", (texto or "").replace("\xa0", " ")).strip()


def sin_tildes(texto):
    """Version sin acentos, solo para comparar."""
    n = unicodedata.normalize("NFD", texto)
    return "".join(c for c in n if unicodedata.category(c) != "Mn").upper()


def extraer_forma(nombre):
    """Busca la forma farmaceutica dentro del nombre del producto."""
    comparable = sin_tildes(nombre)
    for forma in FORMAS:
        if forma in comparable:
            return forma.lower()
    return ""


def extraer_concentracion(nombre):
    """
    Extrae la concentracion. Devuelve valor, unidad y, cuando la
    concentracion se expresa como razon, la cantidad y unidad de referencia.

    "500 mg"        -> 500, mg, None, None
    "160 mg/5 mL"   -> 160, mg, 5, mL
    "100 mg/mL"     -> 100, mg, 1, mL
    """
    m = PATRON_CONCENTRACION.search(nombre)
    if not m:
        return None, "", None, ""

    valor = float(m.group(1).replace(",", "."))
    unidad = m.group(2).lower()

    ref_valor = None
    ref_unidad = m.group(4) or ""

    if ref_unidad:
        # "100 mg/mL" no lleva numero: se asume 1
        ref_valor = float(m.group(3).replace(",", ".")) if m.group(3) else 1.0

    return valor, unidad, ref_valor, ref_unidad.lower()


def separar_principios(texto):
    """
    Separa los principios activos compuestos. El ISP los une con doble
    barra: DICLOFENACO//TRAMADOL
    """
    partes = [limpiar(p) for p in (texto or "").split("//")]
    return [p for p in partes if p]


def main():
    if not ENTRADA.exists():
        print(f"No existe {ENTRADA}")
        print("Ejecuta primero consolidar_isp.py")
        return

    medicamentos = []
    composicion = []

    with ENTRADA.open(encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            registro = limpiar(fila["registro"])
            if not registro:
                continue

            nombre = limpiar(fila["nombre"])
            origen = limpiar(fila["origen"])

            valor, unidad, ref_valor, ref_unidad = extraer_concentracion(nombre)

            medicamentos.append(
                {
                    "registro_sanitario": registro,
                    "registro_raiz": registro.split("/")[0].strip().upper(),
                    "nombre_comercial": nombre,
                    "laboratorio": limpiar(fila["empresa"]),
                    "forma_farmaceutica": extraer_forma(nombre),
                    "concentracion_valor": valor if valor is not None else "",
                    "concentracion_unidad": unidad,
                    "referencia_valor": ref_valor if ref_valor is not None else "",
                    "referencia_unidad": ref_unidad,
                    "fecha_registro": limpiar(fila["fecha_registro"]),
                    "categoria_isp": origen,
                    "es_bioequivalente": BIOEQUIVALENCIA.get(origen, ""),
                }
            )

            principios = separar_principios(fila["principio_activo"])
            for orden, principio in enumerate(principios, 1):
                composicion.append(
                    {
                        "registro_raiz": registro.split("/")[0].strip().upper(),
                        "orden": orden,
                        "principio_activo": principio,
                        "total_principios": len(principios),
                    }
                )

    SALIDA.mkdir(parents=True, exist_ok=True)

    archivo_med = SALIDA / "isp_medicamentos.csv"
    with archivo_med.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(medicamentos[0].keys()))
        w.writeheader()
        w.writerows(medicamentos)

    archivo_comp = SALIDA / "isp_composicion.csv"
    with archivo_comp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(composicion[0].keys()))
        w.writeheader()
        w.writerows(composicion)

    # Resumen de calidad, util para documentar el proceso
    con_forma = sum(1 for m in medicamentos if m["forma_farmaceutica"])
    con_conc = sum(1 for m in medicamentos if m["concentracion_valor"] != "")
    con_razon = sum(1 for m in medicamentos if m["referencia_unidad"])
    bio = sum(1 for m in medicamentos if m["es_bioequivalente"] is True)
    principios = {c["principio_activo"] for c in composicion}
    multiples = sum(1 for c in composicion if c["total_principios"] > 1)

    total = len(medicamentos)
    print(f"{total} medicamentos normalizados")
    print(f"  bioequivalentes:       {bio}")
    print(f"  referentes:            {total - bio}")
    print(f"  con forma detectada:   {con_forma} ({100*con_forma/total:.1f}%)")
    print(f"  con concentracion:     {con_conc} ({100*con_conc/total:.1f}%)")
    print(f"     de esas, en razon:  {con_razon}")
    print()
    print(f"{len(composicion)} filas de composicion")
    print(f"  principios distintos:  {len(principios)}")
    print(f"  en productos multiples:{multiples}")
    print()
    print(f"Guardado en {SALIDA}")


if __name__ == "__main__":
    main()