"""Importa la planilla "PL - MARCO ANTONIO TOURS NACIONAL 2026" (Excel) a la app.

- LIQUIDACIONES: un registro por mes, con el total neto y el % facturado tal como figuran en la planilla.
- Hojas de cada mes ("06-2026"): servicios (tarifas, agua) e insumos entregados por día.
- PAGOS, FACTURAS e IMPUTACION PAGOS / FACTURAS: pagos, comprobantes y a qué liquidación y parte se aplican.

Reemplaza todo lo que haya de Marco Antonio en la app (es para la carga inicial).
"""
import io
import re
import warnings
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import openpyxl
from django.db import transaction

from .models import (EFECTIVO, FACTURADA, Articulo, forzar_efectivo, pesos_texto, Comprobante, EntregaInsumo, ImputacionComprobante, ImputacionPago,
                     Liquidacion, Pago, ServicioMAT, redondear)

PARTES = {'EFECTIVO NETO': EFECTIVO, 'TRANSFERENCIA C/IVA': FACTURADA, 'TRANSFERENCIA': FACTURADA, 'FACTURADA': FACTURADA}
MOTIVOS = {'PAGO': 'a_cuenta', 'CIERRE': 'cierre', 'AJUSTE / COMPENSACIÓN': 'ajuste', 'PRUEBA': 'prueba'}
MEDIOS = {'EFECTIVO': 'efectivo', 'TRANSFERENCIA': 'transferencia', 'CHEQUE': 'cheque'}


class ErrorImportacion(Exception):
    pass


def _dec(valor, defecto=None):
    if valor in (None, ''):
        return defecto
    try:
        return Decimal(str(valor))
    except InvalidOperation:
        return defecto


def _fecha(valor):
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return None


def _texto(valor):
    return '' if valor is None else str(valor).strip()


def _filas(ws, desde, columnas):
    for fila in range(desde, ws.max_row + 1):
        yield fila, [ws.cell(fila, c).value for c in range(1, columnas + 1)]


# ---------- Hojas de cada mes ----------

def _buscar(ws, texto, hasta_fila=None):
    """Primera celda cuyo texto empieza con `texto` (sin distinguir mayúsculas)."""
    for fila in ws.iter_rows(max_row=hasta_fila or ws.max_row):
        for celda in fila:
            if isinstance(celda.value, str) and celda.value.strip().upper().startswith(texto.upper()):
                return celda
    return None


def _columnas_encabezado(ws, fila):
    return {c: _texto(ws.cell(fila, c).value).upper() for c in range(1, ws.max_column + 1) if ws.cell(fila, c).value}


def _col(encabezados, *palabras):
    for c, texto in encabezados.items():
        if all(p in texto for p in palabras):
            return c
    return None


def _importar_mes(ws, liquidacion, avisos):
    """Servicios e insumos de una hoja de mes. Devuelve (servicios, entregas) creados."""
    # Precio del agua
    celda = _buscar(ws, 'VALOR AGUA')
    if celda:
        for c in range(celda.column + 1, celda.column + 4):
            precio = _dec(ws.cell(celda.row, c).value)
            if precio:
                liquidacion.precio_agua = precio
                liquidacion.save(update_fields=['precio_agua'])
                break

    servicios = 0
    encabezado = None
    for fila in range(1, 15):
        textos = [_texto(ws.cell(fila, c).value).upper() for c in range(1, 5)]
        if textos[:3] == ['FECHA', 'UNIDAD', 'SERVICIO']:
            encabezado = fila
            break
    if encabezado:
        cols = _columnas_encabezado(ws, encabezado)
        c_min, c_int = _col(cols, 'MIN'), _col(cols, 'INTERMED')
        c_opt = _col(cols, 'PTIM')  # ÓPTIMA / OPTIMO
        c_vend, c_sel = _col(cols, 'VENDIDA'), _col(cols, 'SEL')
        c_agua = _col(cols, 'UNID') if _col(cols, 'UNID') != 2 else None
        for c, t in cols.items():
            if c > 3 and t.startswith('UNID'):
                c_agua = c
        c_obs = _col(cols, 'OBSERV')
        for fila in range(encabezado + 1, ws.max_row + 1):
            primera = ws.cell(fila, 1).value
            if isinstance(primera, str) and primera.strip().upper().startswith('TOTAL'):
                break
            fecha = _fecha(primera)
            if not fecha:
                continue
            valores = {k: _dec(ws.cell(fila, c).value, Decimal(0)) if c else Decimal(0)
                       for k, c in (('minima', c_min), ('intermedia', c_int), ('optima', c_opt))}
            seleccionada = _dec(ws.cell(fila, c_sel).value) if c_sel else None
            vendida = _texto(ws.cell(fila, c_vend).value).upper() if c_vend else ''
            elegida, otra = '', None
            if vendida.startswith('M'):
                elegida = 'minima'
            elif vendida.startswith('I'):
                elegida = 'intermedia'
            elif vendida.startswith('Ó') or vendida.startswith('O'):
                elegida = 'optima'
            elif seleccionada:
                elegida = next((k for k, v in valores.items() if v and abs(v - seleccionada) < Decimal('0.01')), 'otra')
                if elegida == 'otra':
                    otra = seleccionada
            ServicioMAT.objects.create(
                liquidacion=liquidacion, fecha=fecha, unidad=_texto(ws.cell(fila, 2).value)[:60],
                servicio=_texto(ws.cell(fila, 3).value)[:200], tarifa_minima=valores['minima'],
                tarifa_intermedia=valores['intermedia'], tarifa_optima=valores['optima'], tarifa_elegida=elegida,
                tarifa_otra=otra, unidades_agua=int(_dec(ws.cell(fila, c_agua).value, Decimal(0))) if c_agua else 0,
                observaciones=_texto(ws.cell(fila, c_obs).value)[:200] if c_obs else '')
            servicios += 1

    # Insumos: cada bloque empieza con un encabezado "CÓDIGO | ARTÍCULO | CANTIDAD ..." y debajo las fechas.
    entregas = 0
    for fila in range(1, ws.max_row + 1):
        if _texto(ws.cell(fila, 1).value).upper() not in ('CÓDIGO', 'CODIGO'):
            continue
        anterior = (_texto(ws.cell(fila - 1, 1).value) + ' ' + _texto(ws.cell(fila - 1, 2).value)).upper()
        categoria = 'limpieza' if 'LIMPIEZA' in anterior else 'colacion'
        cols = _columnas_encabezado(ws, fila)
        c_total = next((c for c, t in cols.items() if t == 'TOTAL'), None)
        c_precio = next((c for c, t in cols.items() if t == 'PRECIO'), None)
        if not c_total or not c_precio:
            avisos.append(f'{ws.title}: no entendí un bloque de insumos (fila {fila}).')
            continue
        fechas = {c: _fecha(ws.cell(fila + 1, c).value) for c in range(3, c_total)}
        fechas = {c: f for c, f in fechas.items() if f}
        for f in range(fila + 2, ws.max_row + 1):
            codigo = ws.cell(f, 1).value
            if isinstance(codigo, str) and codigo.strip().upper().startswith('TOTAL'):
                break
            if not isinstance(codigo, (int, float)):
                continue
            nombre = _texto(ws.cell(f, 2).value)
            cantidad_total = _dec(ws.cell(f, c_total).value, Decimal(0))
            importe = _dec(ws.cell(f, c_precio).value, Decimal(0))
            if not cantidad_total:
                continue
            unitario = (importe / cantidad_total).quantize(Decimal('0.0001'))
            articulo, creado = Articulo.objects.get_or_create(
                codigo=int(codigo), defaults={'nombre': nombre[:120], 'categoria': categoria, 'precio': redondear(unitario)})
            if not creado:
                articulo.precio = redondear(unitario)  # queda el precio más reciente
                articulo.save(update_fields=['precio'])
            sin_fecha = cantidad_total
            for c, fecha in fechas.items():
                cantidad = _dec(ws.cell(f, c).value)
                if cantidad:
                    EntregaInsumo.objects.create(liquidacion=liquidacion, fecha=fecha, articulo=articulo,
                                                 cantidad=cantidad, precio_unitario=unitario)
                    sin_fecha -= cantidad
                    entregas += 1
            if sin_fecha > 0:
                # Cantidades sin fecha en la grilla: se cargan con la fecha de fin de mes.
                EntregaInsumo.objects.create(liquidacion=liquidacion, fecha=liquidacion.periodo, articulo=articulo,
                                             cantidad=sin_fecha, precio_unitario=unitario, observaciones='sin fecha en la planilla')
                entregas += 1
    return servicios, entregas


# ---------- Importación completa ----------

@transaction.atomic
def importar(contenido):
    """Importa la planilla (bytes). Devuelve un resumen con lo cargado y los avisos."""
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        try:
            wb = openpyxl.load_workbook(io.BytesIO(contenido), data_only=True)
        except Exception as e:
            raise ErrorImportacion(f'No pude abrir el archivo como Excel ({e}).')
    for hoja in ('LIQUIDACIONES', 'PAGOS', 'FACTURAS', 'IMPUTACION PAGOS', 'IMPUTACION FACTURAS'):
        if hoja not in wb.sheetnames:
            raise ErrorImportacion(f'La planilla no tiene la hoja "{hoja}".')
    avisos = []

    # Se borra lo anterior de Marco Antonio (carga inicial).
    ImputacionPago.objects.all().delete()
    ImputacionComprobante.objects.all().delete()
    Pago.objects.all().delete()
    Comprobante.objects.all().delete()
    EntregaInsumo.objects.all().delete()
    ServicioMAT.objects.all().delete()
    Liquidacion.objects.all().delete()

    # Liquidaciones
    ws = wb['LIQUIDACIONES']
    iva = _dec(ws['B3'].value, Decimal('0.105')) * 100
    por_codigo = {}
    for fila, v in _filas(ws, 6, 9):
        codigo, cierre, neto, pct = _texto(v[0]), _fecha(v[2]), _dec(v[7]), _dec(v[8])
        if not codigo or not cierre:
            continue
        # Un mes sin importe en LIQUIDACIONES todavía no está liquidado: queda abierto.
        liq = Liquidacion.objects.create(
            periodo=cierre.replace(day=1), fecha_cierre=cierre if neto is not None else None, porcentaje_iva=iva,
            porcentaje_facturado=(pct * 100) if pct is not None else Decimal(50), neto_manual=neto)
        por_codigo[codigo] = liq

    # Hojas de cada mes (detalle). Si el mes no estaba en LIQUIDACIONES, se crea con lo que sume el detalle.
    detalle = {}
    for nombre in wb.sheetnames:
        m = re.fullmatch(r'(\d{1,2})-(\d{4})', nombre.strip())
        if not m:
            continue
        periodo = date(int(m.group(2)), int(m.group(1)), 1)
        liq = Liquidacion.objects.filter(periodo=periodo).first()
        if not liq:
            liq = Liquidacion.objects.create(periodo=periodo, porcentaje_iva=iva)
            por_codigo[liq.codigo] = liq
        servicios, entregas = _importar_mes(wb[nombre], liq, avisos)
        detalle[nombre] = (servicios, entregas)
        if liq.neto_manual is not None and (servicios or entregas):
            suma = redondear(liq.total_servicios() + liq.total_agua() + liq.total_insumos())
            if abs(suma - liq.neto_manual) >= 1:
                avisos.append(f'{liq.nombre}: el detalle de la hoja suma $ {pesos_texto(suma)} pero LIQUIDACIONES dice '
                              f'$ {pesos_texto(liq.neto_manual)}. Se usa el de LIQUIDACIONES.')

    # Comprobantes
    comprobantes = {}
    for fila, v in _filas(wb['FACTURAS'], 4, 11):
        ref, fecha = _texto(v[0]), _fecha(v[1])
        if not ref or not fecha:
            continue
        motivo = MOTIVOS.get(_texto(v[10]).upper(), 'otro')
        comprobantes[ref] = Comprobante.objects.create(
            ref_planilla=ref, fecha=fecha, tipo=_texto(v[2]).upper() or 'OTRO', numero=_texto(v[3]),
            importe=_dec(v[5], Decimal(0)), motivo=motivo, observaciones=_texto(v[9])[:200])
    por_numero = {re.sub(r'\D', '', c.numero).lstrip('0'): c for c in comprobantes.values()}

    # Pagos
    pagos = {}
    for fila, v in _filas(wb['PAGOS'], 4, 12):
        ref, fecha = _texto(v[0]), _fecha(v[1])
        if not ref or not fecha:
            continue
        moneda = _texto(v[3]).upper() or 'ARS'
        observaciones = _texto(v[11])
        vinculado = None
        m = re.search(r'FAC\s*[AM]?\s*([AM]?\d[\d-]+)', observaciones.upper())
        if m:
            vinculado = por_numero.get(re.sub(r'\D', '', m.group(1)).lstrip('0'))
        pagos[ref] = Pago.objects.create(
            ref_planilla=ref, fecha=fecha, medio=MEDIOS.get(_texto(v[2]).upper(), 'otro'), moneda=moneda,
            importe_origen=_dec(v[4], Decimal(0)), tipo_cambio=_dec(v[5], Decimal(1)) if moneda == 'USD' else Decimal(1),
            tipo_recibo=_texto(v[7]).upper() if _texto(v[7]).upper() in ('REC A', 'REC M') else '',
            numero_recibo=_texto(v[8]), comprobante=vinculado, observaciones=observaciones[:200],
            banco_referencia=observaciones.split('/')[0].strip()[:120] if '/' in observaciones else '')

    # Imputaciones
    def imputar(hoja, origenes, modelo, campo):
        cantidad = 0
        for fila, v in _filas(wb[hoja], 4, 5):
            ref, codigo_liq, parte, importe = _texto(v[0]), _texto(v[1]), _texto(v[2]).upper(), _dec(v[3])
            if not ref or not importe:
                continue
            if ref not in origenes or codigo_liq not in por_codigo or parte not in PARTES:
                avisos.append(f'{hoja} fila {fila}: no pude imputar {ref} a {codigo_liq} ({parte or "sin parte"}).')
                continue
            modelo.objects.create(**{campo: origenes[ref]}, liquidacion=por_codigo[codigo_liq], parte=PARTES[parte],
                                  importe=importe, observaciones=_texto(v[4])[:200])
            cantidad += 1
        return cantidad

    imp_pagos = imputar('IMPUTACION PAGOS', pagos, ImputacionPago, 'pago')
    imp_comp = imputar('IMPUTACION FACTURAS', comprobantes, ImputacionComprobante, 'comprobante')

    # Facturas M y sus recibos: sin IVA, en negro (parte en efectivo), diga lo que diga la planilla
    for objeto in list(comprobantes.values()) + list(pagos.values()):
        if forzar_efectivo(objeto):
            avisos.append(f'{objeto}: es "M" (en negro, sin IVA); su imputación se pasó a la parte en efectivo.')

    return {
        'liquidaciones': Liquidacion.objects.count(), 'pagos': len(pagos), 'comprobantes': len(comprobantes),
        'imputaciones_pagos': imp_pagos, 'imputaciones_comprobantes': imp_comp,
        'servicios': ServicioMAT.objects.count(), 'entregas': EntregaInsumo.objects.count(),
        'articulos': Articulo.objects.count(), 'avisos': avisos,
    }
