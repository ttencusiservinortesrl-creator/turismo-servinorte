# Cotizador de turismo — Servinorte SRL

Aplicación web para cotizar los servicios de transporte de turismo de Servinorte SRL (Salta). Reemplaza la
planilla "COTIZACIONES 2026.xlsx" (hoja "Estruc. Costos" + una hoja COT por cotización) y emite el Word de
cotización con el modelo de la empresa. Usuaria: Tatiana (español rioplatense, no técnica: responder claro y sin jerga).

## Stack
Django 6 server-rendered + Bootstrap 5 vendorizado en `static/vendor/` (sin Node, sin build). SQLite en local;
PostgreSQL (Supabase) en línea vía `DATABASE_URL`. WhiteNoise sirve los estáticos. Sin librerías de Word: el
.docx se arma reemplazando marcas en el XML de la plantilla.

## Partes
- `cotizador/models.py`: `Parametros` (una sola fila, todos los valores que componen el precio), `TipoVehiculo`,
  `Cotizacion` (guarda en `detalle` el cálculo y los parámetros usados al guardar), `Lugar` (caché del mapa).
- `cotizador/calculo.py`: costo del viaje igual que la planilla (testeado contra la hoja COT302). Ítems por
  vehículo × cantidad de vehículos; filas de margen mínimo/intermedio/mercado/óptimo y referencia por km.
- `cotizador/rutas.py`: km por ruta con Nominatim (buscar lugar) + OSRM (distancia manejando). Servicios
  gratuitos de OpenStreetMap, sin clave; requieren User-Agent (`MAPAS_USER_AGENT`).
- `cotizador/word.py` + `cotizador/plantilla/cotizacion.docx`: el Word. La plantilla se generó con
  `scripts/preparar_plantilla.py` desde un Word real (COT 299); las marcas son `{{FECHA}}`, `{{NUMERO}}`, etc.
  Los párrafos `{{INCLUYE}}` y `{{NO_INCLUYE}}` se repiten uno por renglón.

## Decisiones
- Cambiar parámetros no toca las cotizaciones guardadas; al editar y guardar una, se recalcula con los de hoy.
- Km totales = km en servicio + km vacíos. El mapa carga los km en servicio; se pueden corregir a mano.
- "usar" en el resumen redondea la tarifa a $10.000.
- Parámetros y vehículos requieren permiso (`change_parametros`, `change_tipovehiculo`); el resto, login.

## Cómo correrlo
```
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python manage.py migrate
venv\Scripts\python manage.py createsuperuser
venv\Scripts\python servir.py      (waitress, http://127.0.0.1:8050)
venv\Scripts\python manage.py test cotizador
```
Publicación: Render (Blueprint con `render.yaml`) + Supabase. Ver `docs/publicar-en-internet.md`.
Nunca subir `.env`, `.secret_key`, `.credenciales_prueba_local` ni bases de datos.
