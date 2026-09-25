-- 1. Tabla de Principios Activos (DCI)
CREATE TABLE IF NOT EXISTS principios_activos (
    id SERIAL PRIMARY KEY,
    nombre_dci VARCHAR(255) UNIQUE NOT NULL
);

-- 2. Tabla Maestra de Medicamentos (Catálogo ISP)
CREATE TABLE IF NOT EXISTS medicamentos (
    id SERIAL PRIMARY KEY,
    registro_sanitario VARCHAR(50) UNIQUE NOT NULL,
    nombre_comercial VARCHAR(255) NOT NULL,
    laboratorio VARCHAR(150),
    forma_farmaceutica VARCHAR(100),
    es_bioequivalente BOOLEAN DEFAULT FALSE,
    estado_registro VARCHAR(50)
);

-- 3. Tabla Intermedia (Filtro de Concentración Exacta)
CREATE TABLE IF NOT EXISTS composicion (
    id_medicamento INTEGER REFERENCES medicamentos(id) ON DELETE CASCADE,
    id_principio_activo INTEGER REFERENCES principios_activos(id) ON DELETE CASCADE,
    concentracion_valor NUMERIC(10,2),
    unidad_medida VARCHAR(20),
    PRIMARY KEY (id_medicamento, id_principio_activo)
);

-- 4. Tabla de Cadenas de Farmacias
CREATE TABLE IF NOT EXISTS farmacias (
    id SERIAL PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    tipo VARCHAR(50),
    url_base VARCHAR(255),
    activa BOOLEAN DEFAULT TRUE
);

-- 5. Tabla de Productos Específicos por Farmacia
CREATE TABLE IF NOT EXISTS productos_farmacia (
    id SERIAL PRIMARY KEY,
    id_farmacia INTEGER REFERENCES farmacias(id) ON DELETE CASCADE,
    id_medicamento INTEGER REFERENCES medicamentos(id) ON DELETE SET NULL,
    nombre_publicado VARCHAR(255) NOT NULL,
    url_producto VARCHAR(500),
    disponible BOOLEAN DEFAULT TRUE
);

-- 6. Tabla de Histórico de Precios
CREATE TABLE IF NOT EXISTS historico_precios (
    id SERIAL PRIMARY KEY,
    id_producto INTEGER REFERENCES productos_farmacia(id) ON DELETE CASCADE,
    precio_normal NUMERIC(10,2),
    precio_oferta NUMERIC(10,2),
    fecha_muestreo TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);