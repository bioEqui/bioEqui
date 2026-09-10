-- ============================================================
-- BioEqui - Esquema propuesto (v2)
--
-- Amplia el esquema inicial con los campos que el analisis de
-- datos reales revelo necesarios. Ver NOTAS.md para el detalle
-- de cada cambio y su justificacion.
-- ============================================================


-- ------------------------------------------------------------
-- 1. Principios activos
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS principios_activos (
    id              SERIAL PRIMARY KEY,
    nombre_dci      VARCHAR(255) UNIQUE NOT NULL
);


-- ------------------------------------------------------------
-- 2. Medicamentos (catalogo oficial del ISP)
--
-- Cada fila representa una PRESENTACION autorizada, no un
-- registro sanitario. El ISP asigna un mismo registro a varias
-- concentraciones del mismo producto: las levotiroxinas de 50,
-- 75 y 100 mcg comparten registro. Por eso registro_sanitario
-- no es unico y la clave es el id.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS medicamentos (
    id                   SERIAL PRIMARY KEY,
    registro_sanitario   VARCHAR(50) NOT NULL UNIQUE,
    registro_raiz        VARCHAR(30) NOT NULL,
    nombre_comercial     VARCHAR(255) NOT NULL,
    laboratorio          VARCHAR(150),
    forma_farmaceutica   VARCHAR(100),
    familia              VARCHAR(50),
    via_administracion   VARCHAR(30),
    fecha_registro       DATE,
    categoria_isp        VARCHAR(20),
    es_bioequivalente    BOOLEAN DEFAULT FALSE,
    estado_registro      VARCHAR(50) DEFAULT 'Vigente'
);

-- El cruce con las fuentes comerciales se hace por la raiz del
-- registro, sin el sufijo de anio
CREATE INDEX IF NOT EXISTS idx_medicamentos_raiz
    ON medicamentos (registro_raiz);


-- ------------------------------------------------------------
-- 3. Composicion
--
-- Relacion muchos a muchos entre medicamentos y principios
-- activos. La concentracion vive aca porque es un atributo de
-- la relacion: "500 mg" no significa nada asociado al
-- paracetamol en abstracto.
--
-- La concentracion se descompone en cuatro campos porque puede
-- expresarse como valor simple (500 mg) o como razon
-- (160 mg / 5 mL), y un solo campo numerico no admite el
-- segundo caso.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS composicion (
    id                    SERIAL PRIMARY KEY,
    id_medicamento        INTEGER NOT NULL
                          REFERENCES medicamentos(id) ON DELETE CASCADE,
    id_principio_activo   INTEGER NOT NULL
                          REFERENCES principios_activos(id) ON DELETE CASCADE,
    orden                 SMALLINT DEFAULT 1,
    concentracion_valor   NUMERIC(12,4),
    concentracion_unidad  VARCHAR(20),
    referencia_valor      NUMERIC(12,4),
    referencia_unidad     VARCHAR(20),

    UNIQUE (id_medicamento, id_principio_activo)
);

CREATE INDEX IF NOT EXISTS idx_composicion_principio
    ON composicion (id_principio_activo);


-- ------------------------------------------------------------
-- 4. Farmacias
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS farmacias (
    id         SERIAL PRIMARY KEY,
    codigo     VARCHAR(30) UNIQUE NOT NULL,
    nombre     VARCHAR(100) NOT NULL,
    tipo       VARCHAR(50),
    url_base   VARCHAR(255),
    activa     BOOLEAN DEFAULT TRUE
);


-- ------------------------------------------------------------
-- 5. Productos publicados por cada farmacia
--
-- id_medicamento admite NULL a proposito: un producto existe
-- aunque todavia no se haya podido vincular con el catalogo
-- oficial. En la extraccion inicial, el 46% de los productos no
-- logro vinculacion.
--
-- estado_vinculacion registra por que. Se detecto que la fuente
-- comercial publica registros sanitarios erroneos: un mismo
-- registro asociado a medicamentos distintos, y valores que no
-- tienen formato de registro. Aceptarlos sin validar agrupaba
-- medicamentos sin relacion entre si.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS productos_farmacia (
    id                      SERIAL PRIMARY KEY,
    id_farmacia             INTEGER NOT NULL
                            REFERENCES farmacias(id) ON DELETE CASCADE,
    id_medicamento          INTEGER
                            REFERENCES medicamentos(id) ON DELETE SET NULL,

    id_externo              VARCHAR(50) NOT NULL,
    sku                     VARCHAR(50),
    ean                     VARCHAR(60),

    nombre_publicado        VARCHAR(300) NOT NULL,
    marca                   VARCHAR(150),
    url_producto            VARCHAR(500),
    url_imagen              VARCHAR(500),

    registro_declarado      VARCHAR(50),
    registro_raiz           VARCHAR(30),
    estado_vinculacion      VARCHAR(30) DEFAULT 'pendiente',

    forma_farmaceutica      VARCHAR(100),
    familia                 VARCHAR(50),
    via_administracion      VARCHAR(30),

    concentracion_valor     NUMERIC(12,4),
    concentracion_unidad    VARCHAR(20),
    referencia_valor        NUMERIC(12,4),
    referencia_unidad       VARCHAR(20),

    cantidad_envase         NUMERIC(10,2),
    unidad_envase           VARCHAR(50),

    condicion_venta         VARCHAR(50),
    clase_producto          VARCHAR(30),

    -- Se conservan las dos fuentes por separado: se detectaron
    -- discrepancias entre lo que declara el comercio y lo que
    -- registra el ISP, y el origen del dato debe ser trazable
    bioequivalente_comercial  BOOLEAN,
    composicion_incompleta    BOOLEAN DEFAULT FALSE,
    clave_equivalencia        VARCHAR(300),

    UNIQUE (id_farmacia, id_externo)
);

CREATE INDEX IF NOT EXISTS idx_productos_clave
    ON productos_farmacia (clave_equivalencia);

CREATE INDEX IF NOT EXISTS idx_productos_medicamento
    ON productos_farmacia (id_medicamento);

CREATE INDEX IF NOT EXISTS idx_productos_raiz
    ON productos_farmacia (registro_raiz);


-- ------------------------------------------------------------
-- 6. Historico de precios
--
-- La restriccion de unicidad evita que una reejecucion del
-- extractor duplique la serie. El indice compuesto sostiene la
-- consulta habitual: la serie de un producto en el tiempo.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS historico_precios (
    id                SERIAL PRIMARY KEY,
    id_producto       INTEGER NOT NULL
                      REFERENCES productos_farmacia(id) ON DELETE CASCADE,
    fecha_muestreo    DATE NOT NULL,
    precio_normal     INTEGER,
    precio_oferta     INTEGER,
    precio_unitario   NUMERIC(12,2),
    disponible        BOOLEAN,

    UNIQUE (id_producto, fecha_muestreo)
);

CREATE INDEX IF NOT EXISTS idx_precios_producto_fecha
    ON historico_precios (id_producto, fecha_muestreo DESC);


-- ------------------------------------------------------------
-- 7. Vista de productos comparables
--
-- Reune lo necesario para el buscador: un producto con su
-- precio mas reciente y su clave de equivalencia. Los productos
-- que comparten clave son intercambiables entre si.
-- ------------------------------------------------------------
CREATE OR REPLACE VIEW v_productos_vigentes AS
SELECT
    p.id,
    p.nombre_publicado,
    p.marca,
    f.nombre                AS farmacia,
    p.clave_equivalencia,
    p.familia,
    p.via_administracion,
    p.cantidad_envase,
    p.unidad_envase,
    p.condicion_venta,
    p.estado_vinculacion,
    m.nombre_comercial      AS nombre_oficial,
    m.laboratorio           AS laboratorio_oficial,
    m.es_bioequivalente     AS bioequivalente_isp,
    p.bioequivalente_comercial,

    -- Valor a mostrar: el del regulador tiene prioridad, y si no hay
    -- vinculacion se usa lo que declara el comercio
    COALESCE(m.es_bioequivalente, p.bioequivalente_comercial)
                            AS bioequivalente,

    -- De donde viene ese valor. La distincion importa: una certificacion
    -- del ISP no equivale a una declaracion comercial, y el usuario debe
    -- poder saber cual esta viendo
    CASE
        WHEN m.es_bioequivalente IS NOT NULL THEN 'isp'
        WHEN p.bioequivalente_comercial IS NOT NULL THEN 'comercial'
        ELSE 'sin_dato'
    END                     AS bioequivalente_fuente,

    h.fecha_muestreo,
    h.precio_normal,
    h.precio_oferta,
    h.precio_unitario,
    h.disponible,
    p.url_producto,
    p.url_imagen
FROM productos_farmacia p
JOIN farmacias f ON f.id = p.id_farmacia
LEFT JOIN medicamentos m ON m.id = p.id_medicamento
LEFT JOIN LATERAL (
    SELECT *
    FROM historico_precios hp
    WHERE hp.id_producto = p.id
    ORDER BY hp.fecha_muestreo DESC
    LIMIT 1
) h ON TRUE;