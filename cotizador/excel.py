"""Excel de cuentas corrientes: resumen por cliente, ventas y movimientos con saldo."""
import io
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from django.utils import timezone

from .models import Cotizacion, Movimiento

AZUL = '1F3B7A'
AZUL_CLARO = 'E6EDFA'
PESOS = '"$" #,##0;[Red]-"$" #,##0'
FECHA = 'DD/MM/YYYY'
LINEA = Side(style='thin', color='DFE6F3')


def _hoja(wb, titulo, encabezados, anchos, primera=False):
    ws = wb.active if primera else wb.create_sheet()
    ws.title = titulo
    ws.append(encabezados)
    for celda in ws[1]:
        celda.font = Font(bold=True, color='FFFFFF')
        celda.fill = PatternFill('solid', fgColor=AZUL)
        celda.alignment = Alignment(vertical='center', wrap_text=True)
    ws.row_dimensions[1].height = 30
    for i, ancho in enumerate(anchos, start=1):
        ws.column_dimensions[get_column_letter(i)].width = ancho
    ws.freeze_panes = 'A2'
    return ws


def _formatear(ws, columnas_pesos=(), columnas_fecha=()):
    for fila in ws.iter_rows(min_row=2):
        for celda in fila:
            celda.border = Border(bottom=LINEA)
            if celda.column in columnas_pesos:
                celda.number_format = PESOS
            if celda.column in columnas_fecha:
                celda.number_format = FECHA
    ws.auto_filter.ref = ws.dimensions


def _fila_total(ws, etiqueta, columnas_suma, columnas_pesos):
    n = ws.max_row
    fila = [''] * ws.max_column
    fila[0] = etiqueta
    ws.append(fila)
    for col in columnas_suma:
        letra = get_column_letter(col)
        ws.cell(row=n + 1, column=col, value=f'=SUBTOTAL(9,{letra}2:{letra}{n})')
    for celda in ws[n + 1]:
        celda.font = Font(bold=True, color=AZUL)
        celda.fill = PatternFill('solid', fgColor=AZUL_CLARO)
        if celda.column in columnas_pesos:
            celda.number_format = PESOS


def generar(cliente=None):
    ventas = Cotizacion.objects.filter(estado=Cotizacion.ACEPTADA).select_related('cliente').order_by('cliente__nombre', 'salida')
    if cliente:
        ventas = ventas.filter(cliente=cliente)
    ventas = list(ventas)
    movimientos = Movimiento.objects.filter(cotizacion__in=ventas).select_related('cotizacion__cliente') \
        .order_by('cotizacion__cliente__nombre', 'fecha', 'id')

    wb = Workbook()

    # Resumen por cliente
    ws = _hoja(wb, 'Resumen por cliente', ['Cliente', 'CUIT / DNI', 'Teléfono', 'Ventas', 'Total vendido', 'Pagado', 'Saldo'],
               [34, 16, 18, 9, 16, 16, 16], primera=True)
    por_cliente = {}
    for v in ventas:
        d = por_cliente.setdefault(v.cliente_id, {'cliente': v.cliente, 'n': 0, 'cargos': Decimal(0), 'pagos': Decimal(0)})
        d['n'] += 1
        d['cargos'] += v.total_cargos()
        d['pagos'] += v.total_pagos()
    for d in por_cliente.values():
        c = d['cliente']
        ws.append([c.nombre, c.cuit, c.telefono, d['n'], float(d['cargos']), float(d['pagos']), float(d['cargos'] - d['pagos'])])
    _formatear(ws, columnas_pesos=(5, 6, 7))
    _fila_total(ws, 'TOTAL', (4, 5, 6, 7), (5, 6, 7))

    # Ventas
    ws = _hoja(wb, 'Ventas', ['N° COT', 'Cliente', 'Aceptada', 'Salida', 'Itinerario', 'Total', 'Pagado', 'Saldo'],
               [9, 30, 12, 12, 48, 16, 16, 16])
    for v in ventas:
        cargos, pagos = v.total_cargos(), v.total_pagos()
        ws.append([v.numero, v.cliente.nombre, v.fecha_estado, timezone.localtime(v.salida).date(), v.itinerario,
                   float(cargos), float(pagos), float(cargos - pagos)])
    _formatear(ws, columnas_pesos=(6, 7, 8), columnas_fecha=(3, 4))
    _fila_total(ws, 'TOTAL', (6, 7, 8), (6, 7, 8))

    # Movimientos con saldo acumulado por cliente
    ws = _hoja(wb, 'Movimientos', ['Cliente', 'Fecha', 'N° COT', 'Concepto', 'Medio de pago', 'Comprobante', 'Cargo', 'Pago', 'Saldo del cliente'],
               [30, 12, 9, 36, 15, 18, 15, 15, 17])
    saldo, actual = Decimal(0), None
    for m in movimientos:
        if m.cotizacion.cliente_id != actual:
            actual, saldo = m.cotizacion.cliente_id, Decimal(0)
        cargo = m.importe if m.tipo == Movimiento.CARGO else None
        pago = m.importe if m.tipo == Movimiento.PAGO else None
        saldo += (cargo or 0) - (pago or 0)
        ws.append([m.cotizacion.cliente.nombre, m.fecha, m.cotizacion.numero, m.concepto, m.get_medio_display(), m.referencia,
                   float(cargo) if cargo else None, float(pago) if pago else None, float(saldo)])
    _formatear(ws, columnas_pesos=(7, 8, 9), columnas_fecha=(2,))

    for hoja in wb.worksheets:
        hoja.sheet_view.zoomScale = 110
    salida = io.BytesIO()
    wb.save(salida)
    return salida.getvalue()
