"""
Dosis de los productos combinados (dos o mas principios activos).

El ISP no publica la dosis de cada principio activo de un combinado, y las
farmacias declaran solo una ("Amoxicilina/Ac. clavulanico 125 mg"). Con una
sola dosis, un 875/125 y un 500/125 quedaban en el mismo grupo, y el mismo
875/125 quedaba repartido en grupos distintos segun la farmacia.

La dosis completa si aparece en el nombre publicado, escrita de muchas
formas: "875/125", "875-125 MG", "875 mg/125 mg", "875 MG + 125 MG",
"Amoxicilina 875 mg acido clavulanico 125 mg", "250 mg/62,5 mg/5 ml".
Este modulo la lee y la lleva a una forma comparable.

Lo usan la capa oro (para agrupar) y la API (para mostrar cada dosis).
"""

import re
import unicodedata

FACTOR = {"g": 1000, "mg": 1, "mcg": 0.001, "ug": 0.001}
NUMERO = r"(\d+(?:\.\d+)?)"
UNIDAD = r"(mg|mcg|ug|g)"

# Una cadena de dosis separadas por / - +: "875/125", "40 mg/12.5 mg"
CADENA = re.compile(
    NUMERO + r"\s*" + UNIDAD + r"?\b((?:\s*[/+-]\s*\d+(?:\.\d+)?\s*(?:mg|mcg|ug|g)?\b)+)"
)
TROZO = re.compile(NUMERO + r"\s*" + UNIDAD + r"?\b")
SUELTA = re.compile(NUMERO + r"\s*" + UNIDAD + r"\b")
VOLUMEN = re.compile(r"(?:/|por|en|cada)\s*" + NUMERO + r"\s*ml\b")

# Palabras que no identifican a un principio activo dentro de un nombre
GENERICAS = {"acido", "sodio", "sodico", "potasio", "calcio", "clorhidrato",
             "maleato", "besilato", "monohidrato", "dihidrato", "vitamina"}


def sin_tildes(texto):
    n = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in n if unicodedata.category(c) != "Mn")


def _formato(valor):
    return f"{round(valor, 4):g}"


def dosis_en_nombre(nombre):
    """
    Dosis que menciona un nombre, en mg y en el orden en que aparecen.

    Devuelve (dosis, volumen): volumen son los ml de referencia de un
    liquido ("250 mg/5 ml" -> 5), o None si el nombre no los indica.
    """
    t = sin_tildes(nombre)
    t = re.sub(r"(\d),(\d)", r"\1.\2", t)

    volumen = None
    m = VOLUMEN.search(t)
    if m:
        volumen = float(m.group(1))
        t = t[: m.start()] + " " * (m.end() - m.start()) + t[m.end():]

    encontradas = []  # (posicion, mg)
    ocupado = []

    for m in CADENA.finditer(t):
        trozos = list(TROZO.finditer(m.group(0)))
        unidades = [x.group(2) for x in trozos if x.group(2)]
        if not unidades and re.match(r"\s*ml\b", t[m.end():]):
            continue
        # "875/125" sin unidad se entiende en mg; "40 mg/12.5" toma la ultima
        comun = unidades[-1] if unidades else "mg"
        for x in trozos:
            encontradas.append((m.start() + x.start(), float(x.group(1)) * FACTOR[x.group(2) or comun]))
        ocupado.append((m.start(), m.end()))

    for m in SUELTA.finditer(t):
        if not any(a <= m.start() < b for a, b in ocupado):
            encontradas.append((m.start(), float(m.group(1)) * FACTOR[m.group(2)]))

    encontradas.sort()
    return [mg for _, mg in encontradas], volumen


def contar_principios(principios, origen):
    """Cantidad de principios activos de un producto."""
    if origen == "isp":
        return len(principios)
    texto = sin_tildes(" ".join(principios))
    texto = re.sub(r"\d+(?:[.,]\d+)?\s*(mg|mcg|ug|g|ui|%)?", " ", texto)
    return len([p for p in re.split(r"\+|/|,|\by\b|-", texto) if p.strip()])


def concentracion_combinada(nombre, cantidad, familia):
    """
    Concentracion comparable de un combinado, o "" si el nombre no trae
    una dosis por cada principio activo.

    Las dosis se ordenan de mayor a menor para que "875/125" y "125/875"
    den lo mismo: "875+125mg". En liquidos se expresan por ml.
    """
    dosis, volumen = dosis_en_nombre(nombre)
    if len(dosis) != cantidad or any(d <= 0 for d in dosis):
        return ""

    dosis = sorted(dosis, reverse=True)
    if familia == "solido_oral":
        return "+".join(_formato(d) for d in dosis) + "mg"
    if volumen:
        return "+".join(_formato(d / volumen) for d in dosis) + "mg/ml"
    return ""


def _palabra_clave(principio):
    """La palabra que identifica a un principio activo en un nombre."""
    candidatas = [p for p in re.findall(r"[a-z]+", sin_tildes(principio))
                  if len(p) > 3 and p not in GENERICAS]
    return max(candidatas, key=len) if candidatas else None


def detalle_dosis(principios, concentracion, nombres):
    """
    "Amoxicilina 875 mg + acido clavulanico 125 mg" para un combinado.

    La concentracion del grupo no dice que dosis corresponde a cada
    principio activo; eso se obtiene del nombre de algun producto que
    nombre ambos principios junto a su dosis. Si ninguno lo hace,
    devuelve None y la pagina muestra solo las dosis.
    """
    m = re.fullmatch(r"([\d.+]+)mg(/ml)?", concentracion or "")
    if len(principios) < 2 or not m:
        return None

    del_grupo = sorted(float(x) for x in m.group(1).split("+"))
    por_ml = bool(m.group(2))
    claves = [_palabra_clave(p) for p in principios]
    if None in claves:
        return None

    for nombre in nombres:
        texto = sin_tildes(nombre)
        posiciones = [re.search(r"\b" + c + r"\b", texto) for c in claves]
        if None in posiciones:
            continue

        dosis, volumen = dosis_en_nombre(nombre)
        if por_ml:
            if not volumen:
                continue
            dosis = [d / volumen for d in dosis]
        if len(dosis) != len(principios):
            continue
        if sorted(round(d, 4) for d in dosis) != [round(d, 4) for d in del_grupo]:
            continue

        # El principio que aparece primero lleva la primera dosis
        orden = sorted(range(len(principios)), key=lambda i: posiciones[i].start())
        partes = [f"{principios[i]} {_formato(d)} mg" for i, d in zip(orden, dosis)]
        texto = " + ".join(partes)
        return texto + (" por ml" if por_ml else "")

    return None
