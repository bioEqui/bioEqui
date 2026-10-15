# BioEqui - Plataforma de Homologación de Medicamentos Bioequivalentes

## Descripción
**BioEqui** es un observatorio analítico y motor de homologación clínica.
- **Qué hace:** Permite a los usuarios buscar un medicamento comercial y encontrar sus alternativas bioequivalentes certificadas con exactitud (mismo principio activo, dosis y presentación), mostrando además el historial de precios.
- **A quién va dirigido:** Ciudadanos, pacientes con tratamientos crónicos y adultos mayores en Chile que buscan transparencia en el mercado farmacéutico.
- **Qué problema resuelve:** Disminuye el gasto de bolsillo generado por la asimetría de información, automatizando el cruce de los datos clínicos del Instituto de Salud Pública (ISP) con los valores comerciales de las cadenas de farmacias.

## Arquitectura de la Solución
El sistema se compone de cuatro capas principales:
1. **Capa de Ingesta Oficial:** Pipeline ETL que normaliza el catálogo abierto del ISP.
2. **Capa de Extracción:** Microservicio Python de Web Scraping ético ejecutado asíncronamente para capturar precios públicos.
3. **Capa Backend (API REST):** Motor de validación de 4 filtros para asegurar la equivalencia terapéutica exacta.
4. **Capa Frontend:** Interfaz web responsiva con visualización de histórico de precios.

## Tecnologías Utilizadas
- **Backend & API:** Python 3.10+, FastAPI, Uvicorn, psycopg[binary].
- **Base de Datos:** PostgreSQL orquestado mediante contenedores Docker.
- **Frontend:** React, Vite, JavaScript, HTML/CSS.
- **Ingeniería de Datos (Scraping & ETL):** Pandas, BeautifulSoup, Requests (con inyección dinámica de cabeceras).
- **Control de Versiones:** Git y GitHub.

## Metodología de Trabajo
- **Arquitectura de Datos:** Enfoque Medallón (Capas Bronce, Plata, Oro) para aislar la extracción de catálogos crudos, su normalización por farmacia, y el cruce definitivo con los registros del ISP.
- **Desarrollo Ágil:** Iteraciones cortas adaptando principios de CRISP-DM para proyectos de datos.
- **Control de Versiones:** Flujo de ramas estructurado (`main`, `develop`). Para garantizar despliegues limpios y evitar conflictos de configuración, todo el código fuente del sistema (API, BD, Frontend y Scraping) se encuentra centralizado de forma estricta en la carpeta `Desarrollo_Proyecto`.

## Instrucciones de Ejecución Local

### 1. Clonar el Repositorio y Configurar Entorno
El proyecto utiliza un entorno virtual en la raíz para aislar las librerías de Python.

```bash
git clone <url-del-repositorio>
cd bioEqui

# Crear entorno virtual (si no existe)
python -m venv venv

# Activar entorno (Windows)
.\venv\Scripts\Activate
# Activar entorno (Mac/Linux)
source venv/bin/activate

# Instalar dependencias requeridas
pip install -r Desarrollo_Proyecto/requirements.txt
```

### 2. Variables de Entorno (.env)
Debe contener la URL de conexión a la base de datos apuntando al puerto `5433`:

```env
DATABASE_URL=postgresql://usuario:contraseña@localhost:5433/bioequi
```

### 3. Levantar la Base de Datos (Docker)
Inicia el contenedor de PostgreSQL utilizando el archivo compose de la nueva estructura.

```bash
docker compose -f Desarrollo_Proyecto\db\propuesta\docker-compose.yml up -d
```
*(Verifica en Docker Desktop o con `docker ps` que el contenedor `bioequi_postgres_v2` esté corriendo en el puerto 5433).*

### 4. Levantar la API REST (Backend)
Con el entorno virtual activado, entra a la carpeta de desarrollo y ejecuta Uvicorn utilizando el módulo de Python para evitar directivas de bloqueo de PowerShell en Windows.

```bash
cd Desarrollo_Proyecto
python -m uvicorn api.main:app --reload
```
*La API quedará escuchando y documentada en `http://localhost:8000/docs`.*

### 5. Levantar el Frontend (React)
Abre una nueva terminal, navega a la carpeta del frontend, instala los paquetes de Node e inicia el servidor de Vite.

```bash
cd Desarrollo_Proyecto/frontend
npm install
npm run dev
```
*La plataforma web estará disponible en `http://localhost:5173`.*

### 6. Notas de Operación y Solución de Problemas
- **Bloqueos de Web Scraping (Error HTTP 401):** El extractor de Cruz Verde (`descargar_catalogo_cruzverde.py`) está diseñado para inyectar cookies y *headers* dinámicos imitando a un navegador Chrome real, evadiendo así las protecciones anti-bot del servidor.
- **Problemas de dependencias (psycopg):** Si la API falla al inicio indicando errores de conexión PostgreSQL, reconstruye las librerías del entorno asegurando que se instale `psycopg[binary]`, tal como está fijado en el `requirements.txt`.