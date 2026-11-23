# BioEqui - Plataforma de Homologación de Medicamentos Bioequivalentes

## Descripción
**BioEqui** compara el precio de un mismo medicamento entre farmacias de Chile e indica qué alternativas son bioequivalentes, verificándolo contra el registro oficial del Instituto de Salud Pública (ISP).
- **Qué hace:** el usuario busca un medicamento por nombre o principio activo y ve sus alternativas comparables (mismo principio activo, dosis, forma y tamaño de envase), ordenadas por precio y con su historial.
- **A quién va dirigido:** personas con tratamientos crónicos, adultos mayores y cualquier persona que quiera ahorrar en medicamentos.
- **Qué problema resuelve:** el mismo medicamento cuesta muy distinto según la farmacia y es difícil saber qué marca más barata se puede usar sin riesgo.

Farmacias integradas: Dr. Simi, Cruz Verde, Ahumada, Profar, Farmacia Liga Chilena contra la Epilepsia y Novasalud.

## Arquitectura
- **Datos (arquitectura medallón):** bronce guarda el catálogo crudo de cada farmacia y del ISP; plata lo normaliza a un formato común; oro lo cruza con el ISP por registro sanitario y arma los grupos de productos comparables.
- **Aplicación (tres capas):** PostgreSQL 15 en Docker (esquema en tercera forma normal, 9 tablas y 3 vistas), API REST en FastAPI y página en React con Vite.

## Tecnologías
- **Datos:** Python, Requests, BeautifulSoup, pandas.
- **Base de datos:** PostgreSQL 15 en Docker (puerto 5433).
- **API:** FastAPI y Uvicorn (puerto 8000), psycopg2.
- **Página:** React y Vite (puerto 5173).

## Metodología
Scrum en cuatro sprints de tres semanas. Ramas `main` (entregas) y `develop` (integración), con una rama por funcionalidad y pull request revisado por el otro integrante. Todo el código está en `Desarrollo_Proyecto/`.

## Extracción ética
Cada extractor respeta el `robots.txt` de la farmacia, hace pausas de 2 segundos entre peticiones, se identifica y solo toma información pública de productos, nunca datos personales. Cruz Verde exige una sesión de navegador para mostrar precios: se usa una sesión normal, sin forzar el acceso, y si caduca esa farmacia simplemente no se actualiza.

## Ejecución local

### 1. Instalar (una sola vez)
```bash
git clone https://github.com/bioEqui/bioEqui.git
cd bioEqui
python -m venv venv
venv\Scripts\activate            # Windows  (Mac/Linux: source venv/bin/activate)
pip install -r Desarrollo_Proyecto/requirements.txt
```

Copia `Desarrollo_Proyecto/.env.example` como `Desarrollo_Proyecto/.env` y completa `DB_PASSWORD` (y `CRUZVERDE_COOKIE` si vas a actualizar Cruz Verde). El `.env` no se sube al repositorio.

### 2. Levantar todo
Doble clic en `Desarrollo_Proyecto/levantar.bat`, o:
```bash
cd Desarrollo_Proyecto
python levantar.py
```
Abre Docker Desktop si hace falta, enciende la base, inicia la API y la página, y abre `http://localhost:5173`. La documentación de la API queda en `http://localhost:8000/docs`.

### 3. Actualizar los precios
```bash
python actualizar.py                    # flujo completo: bronce, plata, oro y carga
python actualizar.py --sin-cruzverde    # sin Cruz Verde (sin cookie vigente)
python actualizar.py --sin-descarga     # solo reprocesa
```
Si una farmacia trae menos del 80% de los productos de su muestreo anterior, la descarga se aparta en `data/bronce/rechazados/` y no se procesa.

### 4. Ejecutar las pruebas
```bash
python pruebas/ejecutar_pruebas.py      # 23 casos; resultado en pruebas/resultados/
```

El detalle de instalación, respaldo, migración y solución de problemas está en el Manual de administrador (`FASE 2/Evidencias Proyecto/Evidencia de documentacio/27_Manual_de_Administrador.docx`).
