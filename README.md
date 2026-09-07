# BioEqui - Plataforma de Homologación de Medicamentos Bioequivalentes

## Descripción
**BioEqui** es un observatorio analítico y motor de homologación clínica.
* **Qué hace:** Permite a los usuarios buscar un medicamento comercial y encontrar sus alternativas bioequivalentes certificadas con exactitud (mismo principio activo, dosis y presentación), mostrando además el historial de precios.
* **A quién va dirigido:** Ciudadanos, pacientes con tratamientos crónicos y adultos mayores en Chile que buscan transparencia en el mercado farmacéutico.
* **Qué problema resuelve:** Disminuye el gasto de bolsillo generado por la asimetría de información, automatizando el cruce de los datos clínicos del Instituto de Salud Pública (ISP) con los valores comerciales de las cadenas de farmacias.

## Arquitectura de la Solución
El sistema se compone de cuatro capas principales:
1. **Capa de Ingesta Oficial:** Pipeline ETL que normaliza el catálogo abierto del ISP.
2. **Capa de Extracción:** Microservicio Python de Web Scraping ético ejecutado asíncronamente para capturar precios públicos.
3. **Capa Backend (API REST):** Motor de validación de 4 filtros para asegurar la equivalencia terapéutica exacta.
4. **Capa Frontend:** Interfaz web responsiva con visualización de histórico de precios.

## Tecnologías Utilizadas

## Metodología de Trabajo

## Instrucciones de Ejecución Local