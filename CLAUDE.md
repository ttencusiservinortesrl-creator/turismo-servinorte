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

## Marco Antonio Tours (app `marcoantonio`)
Empresa relacionada a la que Servinorte presta servicios de transporte e insumos (colaciones, limpieza). Reemplaza la
planilla "PL - MARCO ANTONIO TOURS NACIONAL 2026". Liquidación mensual = servicios (tarifa vendida) + agua + insumos;
se discrimina en **parte facturada** (neto × % facturado + IVA) y **parte en efectivo sin factura** (el resto, sin IVA).
Lo decidió la contadora (Tatiana): la app identifica cada parte; no avisa sobre el efectivo. Pagos y comprobantes se
imputan a liquidación + parte. Controles: comprobantes anticipados (antes del mes o del cierre), transferencias sin
factura vinculada, pagos/comprobantes sin imputar, parte facturada sin comprobante, saldos. La cuenta corriente solo
cuenta liquidaciones cerradas. "Importar planilla" (superusuario) carga la planilla y reemplaza todo lo de MAT; un mes
sin importe en LIQUIDACIONES queda abierto. Verificado contra la hoja RESUMEN (saldo −4.814.354,18 a favor de MAT).
- Cada salida (`ServicioMAT`) muestra su estado de pago: pagos imputados a la salida + pagos "a cuenta del mes"
  repartidos de la salida más vieja a la más nueva (`Liquidacion.reparto_pagos`). Menos de $1 de diferencia = pagada.
- Cotización aceptada → botón "Pasar a Marco Antonio" (`marcoantonio/desde_cotizacion.py`): crea la salida en su mes
  con fecha, recorrido, vehículo y tarifa vendida (mínima/intermedia/óptima de los márgenes del cálculo, o a mano;
  viene con el precio de la cotización, sin IVA). Si cambia el precio de la cotización, la salida lo sigue solo si
  estaba vendida a ese mismo precio. Al anular o volver atrás la cotización se borra la salida si no tiene insumos
  ni pagos. Las colaciones de la cotización ya están en el precio: van solo como nota, no como insumo.
- Pantalla principal = salidas agrupadas por mes (`/marco-antonio/`); el tablero pasó a "Resumen y controles".
  Ficha de la salida en 4 partes: precio, cómo se cobra (facturada/efectivo + facturas del mes), colaciones e
  insumos (un insumo que no está en la lista se da de alta en el catálogo al cargarlo) y pagos recibidos
  (`Liquidacion.aplicaciones_pagos`: qué pago cubre cada salida). Pagos y comprobantes son MENSUALES (decisión de
  la usuaria): se imputan a mes + parte; el campo `servicio` de las imputaciones queda solo por compatibilidad.

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
- Anulaciones (nada se borra): cotización → estado ANULADA con motivo/fecha/usuario (`estado_antes_de_anular`).
  Venta anulada: sus cargos quedan `anulado=True`; lo pagado se retiene (cargo "Seña retenida") o se devuelve
  (movimiento DEVOLUCION, suma como un cargo); el saldo queda en 0. Pagos anulados conservan el N° de recibo y el
  recibo sale con "ANULADO". `Cotizacion.CON_CUENTA` = aceptadas + anuladas (para historial y Excel).
  "Quitar del diagrama" borra la reserva solo si cada día sigue empezando con el nombre del cliente.
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
