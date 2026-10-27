# Cotizador de turismo — Servinorte SRL

Aplicación web para cotizar los servicios de transporte de turismo de Servinorte SRL (Salta). Reemplaza la
planilla "COTIZACIONES 2026.xlsx" (hoja "Estruc. Costos" + una hoja COT por cotización) y emite el Word de
cotización con el modelo de la empresa. Usuaria: Tatiana (español rioplatense, no técnica: responder claro y sin jerga).

## Stack
Django 6 server-rendered + Bootstrap 5 vendorizado en `static/vendor/` (sin Node, sin build). SQLite en local;
PostgreSQL (Supabase) en línea vía `DATABASE_URL`. WhiteNoise sirve los estáticos. openpyxl para el Excel. Sin librerías de Word: el
.docx se arma reemplazando marcas en el XML de la plantilla.

## Partes
- `cotizador/models.py`: `Parametros` (una sola fila, todos los valores que componen el precio), `TipoVehiculo`,
  `Cliente`, `Cotizacion` (guarda en `detalle` el cálculo y los parámetros usados al guardar; estado
  pendiente/aceptada/rechazada), `LineaVehiculo` (uno o varios tipos de vehículo por cotización, con cantidad y
  choferes), `Movimiento` (cuenta corriente de cada venta: cargos y pagos; los pagos llevan `numero_recibo`
  correlativo), `Lugar` (caché del mapa).
- `cotizador/calculo.py`: costo del viaje igual que la planilla (testeado contra la hoja COT302). Ítems por
  vehículo × cantidad de vehículos; filas de margen mínimo/intermedio/mercado/óptimo y referencia por km.
- `cotizador/rutas.py`: km por ruta con Nominatim (buscar lugar) + OSRM (distancia manejando). Servicios
  gratuitos de OpenStreetMap, sin clave; requieren User-Agent (`MAPAS_USER_AGENT`).
- `cotizador/recibo.py` + `letras.py`: recibo de pago en Word (mismo membrete que la cotización, importe en letras).
- `cotizador/estadisticas.py`: aceptación, motivos de rechazo, destinos, clientes y vehículos (barras en HTML/CSS).
- `cotizador/diagrama.py` + `drive.py`: diagrama de unidades (Excel "PL - DIAGRAMA DE VEHICULOS" en Drive, de
  Sergio García). Lee disponibilidad de las unidades de turismo (Parámetros) y anota ventas aceptadas.
  Escribe editando solo el XML de la hoja (openpyxl al guardar pierde comentarios). Cuenta de servicio de Google
  en `GOOGLE_SERVICE_ACCOUNT_JSON`; para probar local, `DIAGRAMA_LOCAL=<copia.xlsx>`. Ver `docs/conectar-diagrama.md`.
- `cotizador/excel.py`: cuentas corrientes en Excel (resumen por cliente, ventas, movimientos con saldo), openpyxl.
- `static/css/tema.css`: diseño (paleta de azules del logo #1F3B7A); el logo está en `static/img/logo.png`.
- `cotizador/word.py` + `cotizador/plantilla/cotizacion.docx`: el Word. La plantilla se generó con
  `scripts/preparar_plantilla.py` desde un Word real (COT 299); las marcas son `{{FECHA}}`, `{{NUMERO}}`, etc.
  Los párrafos `{{INCLUYE}}` y `{{NO_INCLUYE}}` se repiten uno por renglón.

## Decisiones
- Cambiar parámetros no toca las cotizaciones guardadas; al editar y guardar una, se recalcula con los de hoy.
- Cada ítem del costo se calcula por vehículo (choferes y rendimiento de cada línea) y se suma; "Otros gastos"
  es un total del viaje. Hotel y peajes son por vehículo.
- Km totales = km en servicio + km vacíos. El mapa carga los km en servicio; se pueden corregir a mano.
- "usar" en el resumen redondea la tarifa a $10.000.
- Impuestos sobre la venta (TISSH 0,6% + AMT 2% + IIBB 3,6%, editables) sobre el precio sin IVA: cada precio de
  margen = costo operativo × (1 + margen) ÷ (1 − tasa), así el margen queda limpio después de impuestos; la
  fila "Costo" es el precio de equilibrio. La ganancia descuenta impuestos. La planilla original no los tenía.
- Seguro = póliza mensual de la flota ÷ vehículos de la flota ÷ 30 × días del viaje.
- Cada ítem del detalle del costo se puede destildar para sacarlo de la suma (`Cotizacion.items_excluidos`,
  nombres separados por |); se sigue mostrando tachado.
- Viajes a futuro: si la salida es más de `proyectar_desde_dias` (30) después de la fecha de la cotización, se
  agrega el ítem "Ajuste por inflación" = costo de hoy × ((1 + inflación mensual)^(días/30) − 1). Los márgenes se
  calculan sobre el costo proyectado. La inflación se puede cambiar en cada cotización (por defecto, la de Parámetros).
- Aceptar una cotización la convierte en venta: crea un cargo automático por el total con IVA, que se
  actualiza solo si cambia el precio. Con pagos o cargos manuales no se puede rechazar ni eliminar.
- TAN (Tren a las Nubes): un día que solo dice "TAN" cuenta como disponible, con aviso. Al anotar la reserva,
  se borra el TAN de esos días (celdas y combinaciones dentro del bloque) y la reserva queda con el estilo blanco
  de la fila. La grilla de Unidades copia el color de fondo de cada celda de la planilla.
- Unidades: solo se asignan en ventas aceptadas, preguntando antes (se puede elegir "Todavía no"); nunca pisa
  celdas ocupadas; la app no borra del diagrama (al des-aceptar avisa que hay que borrarlo a mano).
- Cuenta corriente del cliente = movimientos de todas sus cotizaciones aceptadas (no hay tabla aparte).
- En la cotización se elige un cliente o se escribe uno nuevo (se crea la ficha; si el nombre ya existe, se reutiliza).
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
Publicación: Render (Blueprint con `render.yaml`) + Supabase (cuenta propia, distinta de la de repuestos).
En línea: https://servinorte-turismo.onrender.com. Cada push a `main` se publica solo. Ver `docs/publicar-en-internet.md`.
Nunca subir `.env`, `.secret_key`, `.credenciales_prueba_local` ni bases de datos.
