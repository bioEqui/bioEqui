# Esquema propuesto (v2)

Ampliación del esquema inicial con los campos que el análisis de datos reales
mostró necesarios. El esquema original reflejaba el diagrama de dbdiagram y era
correcto con la información disponible en ese momento; estos cambios responden a
hallazgos posteriores.

Cada cambio está justificado por un dato concreto de la extracción.

---

## Cambios en `medicamentos`

| Campo | Motivo |
|---|---|
| `registro_raiz` | El ISP publica `F-8660/11` y las farmacias solo `F-8660`. Sin esta columna el cruce entre fuentes no es posible. Lleva índice porque es la llave de todas las consultas de vinculación. |
| `familia` | Se agrupa por familia y no por forma exacta: exigir coincidencia textual impediría agrupar *comprimidos* con *comprimidos recubiertos*. Las formas de liberación modificada quedan en familia aparte porque ahí sí cambia la farmacocinética. |
| `via_administracion` | Permite filtrar sin volver a procesar. La vía se deriva de la familia, pero no al revés. |
| `fecha_registro` | Viene en los listados del ISP y se estaba descartando. Indica qué tan reciente es la certificación. |
| `categoria_isp` | Distingue referente, alternativa e híbrido. El booleano solo no captura esa diferencia: un referente no es lo mismo que un producto sin certificación. |

### `registro_sanitario` deja de ser UNIQUE

El ISP asigna un mismo registro a varias concentraciones del mismo producto. En
los datos, las levotiroxinas de 50, 75 y 100 mcg comparten registro sanitario.
Mantener la restricción haría fallar la carga.

Cada fila representa entonces una **presentación autorizada**, no un registro. La
clave es el `id` autoincremental. El control de duplicados se hace en el
cargador.

---

## Cambios en `composicion`

| Campo | Motivo |
|---|---|
| `referencia_valor` y `referencia_unidad` | Las concentraciones pueden expresarse como razón: `160 mg / 5 mL`. Dos campos no alcanzan. Se detectaron 477 casos en el catálogo del ISP. |
| `orden` | Los productos con varios principios activos los tienen en un orden que la fuente respeta. |
| `id` propio | Antes la clave era `(id_medicamento, id_principio_activo)`. Se mantiene como restricción única, pero un `id` simplifica las referencias. |

### Interpretación de la concentración

| En el nombre | valor | unidad | referencia_valor | referencia_unidad |
|---|---|---|---|---|
| 500 mg | 500 | mg | — | — |
| 160 mg/5 mL | 160 | mg | 5 | mL |
| 100 mg/mL | 100 | mg | 1 | mL |

El último caso no lleva número en el denominador; se asume 1.

---

## Cambios en `productos_farmacia`

| Campo | Motivo |
|---|---|
| `estado_vinculacion` | La fuente comercial publica registros sanitarios erróneos. Se detectó un producto con clopidogrel agrupado con uno de clorfenamina por compartir el registro F-3901, y nueve productos con valores que ni siquiera tienen formato de registro. Los estados son: `vinculado`, `sin_correspondencia`, `sin_registro`, `registro_invalido`, `registro_sospechoso`. |
| `registro_declarado` y `registro_raiz` | Se conserva lo que publica la farmacia además de la raíz derivada, para poder auditar. |
| `sku`, `ean` | Identificadores de la fuente, útiles para seguimiento entre ejecuciones. |
| `cantidad_envase`, `unidad_envase` | Sin el tamaño del envase no se puede calcular precio unitario, y sin precio unitario el ahorro es ficticio: comparar una caja de 16 comprimidos con una de 30 no significa nada. |
| Los cuatro campos de concentración | Mismo motivo que en `composicion`. |
| `familia`, `via_administracion` | Mismo motivo que en `medicamentos`. |
| `clase_producto` | El campo de tipo de la fuente combina dos dimensiones: clase (genérico, marca, combinación) y bioequivalencia. Se separan. |
| `bioequivalente_comercial` | Se conserva aparte del dato oficial. Se detectaron 20 discrepancias entre ambas fuentes, 19 en la misma dirección. El origen del dato debe ser trazable. |
| `composicion_incompleta` | 96 productos declaran menos principios activos de los que su nombre indica. Un producto con rosuvastatina y ezetimiba quedaba agrupado con rosuvastatina simple. Marcarlos permite excluirlos de la agrupación. |
| `clave_equivalencia` | Los productos que comparten esta clave son intercambiables. Lleva índice porque es la consulta principal del buscador. |
| `UNIQUE (id_farmacia, id_externo)` | Evita duplicar el mismo producto al reejecutar el extractor. |

---

## Cambios en `historico_precios`

| Cambio | Motivo |
|---|---|
| `UNIQUE (id_producto, fecha_muestreo)` | Evita que una reejecución del extractor duplique la serie. |
| `precio_unitario` | Se guarda calculado para no recalcularlo en cada consulta. |
| `disponible` | La disponibilidad varía en el tiempo y es parte de la observación. |
| Índice compuesto | La consulta habitual es la serie de un producto ordenada por fecha. |

---

## Cambios en `farmacias`

Se agrega `codigo` como identificador estable (`drsimi`, `cruzverde`). El nombre
puede cambiar; el código no.

---

## Vista `v_productos_vigentes`

Reúne producto, farmacia, datos oficiales y precio más reciente en una sola
consulta. Es lo que necesita el buscador para mostrar resultados sin armar el
join cada vez.

---

## Cómo aplicarlo

Todas las sentencias usan `IF NOT EXISTS`, así que se puede aplicar sobre la base
actual sin romper nada:

```
docker exec -i bioequi_postgres psql -U admin -d bioequi_db < db/propuesta/init_v2.sql
```

Si se reemplaza el `init.sql` del docker-compose, hay que recrear el volumen,
porque ese archivo solo se ejecuta cuando la base está vacía:

```
docker compose down -v
docker compose up -d
```

Esto borra todos los datos. Se pueden recargar ejecutando los scripts del
pipeline.

---

## Pendiente de conversar

- Dónde vive el cargador a PostgreSQL. Hoy `ingesta_isp.py` está en la raíz y
  además existe una carpeta `ingesta_isp/`, lo que confunde. Propuesta: moverlo a
  `db/cargar_isp.py`.
- El cargador actual lee los `.xls` directamente y descarta el principio activo,
  por lo que `principios_activos` y `composicion` quedarían vacías. Leyendo desde
  `data/plata/isp_medicamentos.csv` y `isp_composicion.csv` se llenan las tres
  tablas sin cambiar la lógica de inserción.
- La contraseña está en el `docker-compose.yml`, que se versiona. Para desarrollo
  local está bien; antes de desplegar debe moverse al `.env`.
