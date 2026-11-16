-- ============================================================
-- BioEqui - Esquema v3 (tercera forma normal)
--
-- Respecto de v2 se eliminan las dependencias transitivas:
--
--   forma farmaceutica -> familia, via   tabla formas_farmaceuticas
--   categoria del ISP  -> bioequivalente  tabla categorias_isp
--   clave de equivalencia (se armaba     tabla grupos_equivalencia
--     con otras columnas del producto)
--   registro sanitario -> registro raiz  se calcula, no se guarda
--   precio / envase    -> precio unitario se calcula en las vistas
--
-- Ningun dato se guarda dos veces: lo derivado se obtiene en las
-- vistas, que son lo que consulta la API. Ver NOTAS.md.
-- ============================================================


-- ------------------------------------------------------------
-- 1. Principios activos
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS principios_activos (
    id              SERIAL PRIMARY KEY,
    nombre_dci      VARCHAR(255) UNIQUE NOT NULL
);


-- ------------------------------------------------------------
-- 2. Formas farmaceuticas
--
-- La familia y la via dependen de la forma, no del producto:
-- "comprimidos recubiertos" siempre es solido oral. Guardarlas
-- aqui evita repetirlas en cada medicamento y producto.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS formas_farmaceuticas (
    id                   SERIAL PRIMARY KEY,
    nombre               VARCHAR(100) UNIQUE NOT NULL,
    familia              VARCHAR(50),
    via_administracion   VARCHAR(30)
);


-- ------------------------------------------------------------
-- 3. Categorias del ISP
--
-- Cada listado del ISP implica una condicion de bioequivalencia:
-- las alternativas e hibridos estan certificados; el referente
-- es el producto original contra el que se comparan.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS categorias_isp (
    codigo              VARCHAR(20) PRIMARY KEY,
    es_bioequivalente   BOOLEAN NOT NULL
);


-- ------------------------------------------------------------
-- 4. Medicamentos (catalogo oficial del ISP)
--
-- La raiz del registro (F-1234 para F-1234/20) no se guarda:
-- se obtiene con split_part(registro_sanitario, '/', 1).
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS medicamentos (
    id                   SERIAL PRIMARY KEY,
    registro_sanitario   VARCHAR(50) NOT NULL UNIQUE,
    nombre_comercial     VARCHAR(255) NOT NULL,
    laboratorio          VARCHAR(150),
    id_forma             INTEGER REFERENCES formas_farmaceuticas(id),
    fecha_registro       DATE,
    categoria_isp        VARCHAR(20) REFERENCES categorias_isp(codigo),
    estado_registro      VARCHAR(50) DEFAULT 'Vigente'
);


-- ------------------------------------------------------------
-- 5. Composicion (relacion N:M medicamento - principio activo)
--
-- La concentracion vive en la relacion: es la cantidad de ese
-- principio activo dentro de ese medicamento.
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
-- 6. Farmacias
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
-- 7. Grupos de equivalencia
--
-- Dos productos son comparables si coinciden en principio activo,
-- concentracion normalizada, familia de forma y envase. Cada
-- combinacion es un grupo; los productos lo referencian. La clave
-- de texto (losartan|50.0mg|solido_oral|30comprimidos) ya no se
-- guarda: la arman las vistas a partir de estas columnas.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS grupos_equivalencia (
    id                 SERIAL PRIMARY KEY,
    principio_activo   VARCHAR(255) NOT NULL,
    concentracion      VARCHAR(60)  NOT NULL,
    familia            VARCHAR(50)  NOT NULL,
    envase             VARCHAR(60)  NOT NULL,
    UNIQUE (principio_activo, concentracion, familia, envase)
);


-- ------------------------------------------------------------
-- 8. Productos de farmacia
--
-- id_forma es la forma que declara la farmacia. Solo se guarda
-- cuando no hay una oficial: si el producto esta vinculado a un
-- medicamento que la tiene, se usa esa y no se repite aqui.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS productos_farmacia (
    id                        SERIAL PRIMARY KEY,
    id_farmacia               INTEGER NOT NULL
                              REFERENCES farmacias(id) ON DELETE CASCADE,
    id_medicamento            INTEGER
                              REFERENCES medicamentos(id) ON DELETE SET NULL,
    id_grupo                  INTEGER
                              REFERENCES grupos_equivalencia(id) ON DELETE SET NULL,
    id_forma                  INTEGER
                              REFERENCES formas_farmaceuticas(id),
    id_externo                VARCHAR(50) NOT NULL,
    sku                       VARCHAR(50),
    ean                       VARCHAR(60),
    nombre_publicado          VARCHAR(300) NOT NULL,
    marca                     VARCHAR(150),
    url_producto              VARCHAR(500),
    url_imagen                VARCHAR(500),
    registro_declarado        VARCHAR(50),
    estado_vinculacion        VARCHAR(30) DEFAULT 'pendiente',
    cantidad_envase           NUMERIC(10,2),
    unidad_envase             VARCHAR(50),
    condicion_venta           VARCHAR(50),
    clase_producto            VARCHAR(30),
    bioequivalente_comercial  BOOLEAN,
    composicion_incompleta    BOOLEAN DEFAULT FALSE,
    UNIQUE (id_farmacia, id_externo)
);

CREATE INDEX IF NOT EXISTS idx_productos_grupo
    ON productos_farmacia (id_grupo);
CREATE INDEX IF NOT EXISTS idx_productos_medicamento
    ON productos_farmacia (id_medicamento);


-- ------------------------------------------------------------
-- 9. Historico de precios
--
-- El precio unitario no se guarda: depende del precio y del
-- envase del producto, y se calcula en las vistas.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS historico_precios (
    id                SERIAL PRIMARY KEY,
    id_producto       INTEGER NOT NULL
                      REFERENCES productos_farmacia(id) ON DELETE CASCADE,
    fecha_muestreo    DATE NOT NULL,
    precio_normal     INTEGER,
    precio_oferta     INTEGER,
    disponible        BOOLEAN,
    UNIQUE (id_producto, fecha_muestreo)
);

CREATE INDEX IF NOT EXISTS idx_precios_producto_fecha
    ON historico_precios (id_producto, fecha_muestreo DESC);


-- VISTAS ------------------------------------------------------
-- Todo lo derivado se calcula aqui. La API consulta las vistas,
-- asi que ve las mismas columnas que con el esquema anterior.
-- -------------------------------------------------------------

-- Producto con sus datos derivados: forma, familia, via, clave de
-- equivalencia y bioequivalencia oficial
CREATE OR REPLACE VIEW v_productos AS
SELECT
    p.id,
    p.id_farmacia,
    p.id_medicamento,
    p.id_grupo,
    p.nombre_publicado,
    p.marca,
    f.nombre                AS farmacia,
    p.registro_declarado,
    p.estado_vinculacion,
    fo.nombre               AS forma_farmaceutica,
    fo.familia,
    fo.via_administracion,
    g.principio_activo || '|' || g.concentracion || '|'
        || g.familia || '|' || g.envase
                            AS clave_equivalencia,
    p.cantidad_envase,
    p.unidad_envase,
    p.condicion_venta,
    p.clase_producto,
    p.bioequivalente_comercial,
    p.composicion_incompleta,
    p.url_producto,
    p.url_imagen,
    m.registro_sanitario,
    m.nombre_comercial      AS nombre_oficial,
    m.laboratorio           AS laboratorio_oficial,
    c.es_bioequivalente     AS bioequivalente_isp
FROM productos_farmacia p
JOIN farmacias f                     ON f.id = p.id_farmacia
LEFT JOIN medicamentos m             ON m.id = p.id_medicamento
LEFT JOIN categorias_isp c           ON c.codigo = m.categoria_isp
LEFT JOIN formas_farmaceuticas fo    ON fo.id = COALESCE(m.id_forma, p.id_forma)
LEFT JOIN grupos_equivalencia g      ON g.id = p.id_grupo;


-- Historial con el precio unitario calculado
CREATE OR REPLACE VIEW v_historico_precios AS
SELECT
    h.id,
    h.id_producto,
    h.fecha_muestreo,
    h.precio_normal,
    h.precio_oferta,
    CASE WHEN h.precio_oferta > 0 AND p.cantidad_envase > 0
         THEN ROUND(h.precio_oferta / p.cantidad_envase, 2)
    END                     AS precio_unitario,
    h.disponible
FROM historico_precios h
JOIN productos_farmacia p ON p.id = h.id_producto;


-- Cada producto con su precio mas reciente (lo que consulta la API)
CREATE OR REPLACE VIEW v_productos_vigentes AS
SELECT
    p.id,
    p.nombre_publicado,
    p.marca,
    p.farmacia,
    p.clave_equivalencia,
    p.familia,
    p.via_administracion,
    p.cantidad_envase,
    p.unidad_envase,
    p.condicion_venta,
    p.estado_vinculacion,
    p.nombre_oficial,
    p.laboratorio_oficial,
    p.bioequivalente_isp,
    p.bioequivalente_comercial,
    COALESCE(p.bioequivalente_isp, p.bioequivalente_comercial)
                            AS bioequivalente,
    CASE
        WHEN p.bioequivalente_isp IS NOT NULL THEN 'isp'
        WHEN p.bioequivalente_comercial IS NOT NULL THEN 'comercial'
        ELSE 'sin_dato'
    END                     AS bioequivalente_fuente,
    h.fecha_muestreo,
    h.precio_normal,
    h.precio_oferta,
    CASE WHEN h.precio_oferta > 0 AND p.cantidad_envase > 0
         THEN ROUND(h.precio_oferta / p.cantidad_envase, 2)
    END                     AS precio_unitario,
    h.disponible,
    p.url_producto,
    p.url_imagen
FROM v_productos p
LEFT JOIN LATERAL (
    SELECT *
    FROM historico_precios hp
    WHERE hp.id_producto = p.id
    ORDER BY hp.fecha_muestreo DESC
    LIMIT 1
) h ON TRUE;
