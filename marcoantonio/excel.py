"""Excel de Marco Antonio Tours: liquidaciones (con las dos partes), pagos, comprobantes e imputaciones."""
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .models import EFECTIVO, FACTURADA, Comprobante, ImputacionComprobante, ImputacionPago, Liquidacion, Pago

AZUL = '1F3B7A'
PESOS = '"$" #,##0.00;[Red]-"$" #,##0.00'
FECHA = 'DD/MM/YYYY'


def _hoja(wb, titulo, encabezados, anchos, primera=False):
    ws = wb.active if primera else wb.create_sheet()
    ws.title = titulo
    ws.append(encabezados)
    for celda in ws[1]:
        celda.font = Font(bold=True, color='FFFFFF')
        celda.fill = PatternFill('solid', fgColor=AZUL)
        celda.alignment = Alignment(vertical='center', wrap_text=True)
    ws.row_dimensions[1].height = 32
    for i, ancho in enumerate(anchos, start=1):
        ws.column_dimensions[get_column_letter(i)].width = ancho
    ws.freeze_panes = 'A2'
    return ws


def _formatear(ws, pesos=(), fechas=()):
    for fila in ws.iter_rows(min_row=2):
        for celda in fila:
            if celda.column in pesos:
                celda.number_format = PESOS
            if celda.column in fechas:
                celda.number_format = FECHA
    ws.auto_filter.ref = ws.dimensions


def generar():
    wb = Workbook()
    ws = _hoja(wb, 'Liquidaciones', ['Código', 'Mes', 'Cierre', 'Neto total', '% facturado', 'Facturada neto',
                                     'IVA', 'Facturada (neto + IVA)', 'Pagado facturada', 'Saldo facturada',
                                     'Comprobado facturada', 'Efectivo sin factura', 'Pagado efectivo', 'Saldo efectivo',
                                     'Comprobado efectivo'],
               [13, 16, 12, 16, 10, 16, 14, 18, 16, 16, 16, 18, 16, 16, 16], primera=True)
    for l in Liquidacion.objects.prefetch_related('servicios', 'entregas__articulo'):
        ws.append([l.codigo, l.nombre, l.fecha_cierre, float(l.neto()), float(l.porcentaje_facturado) / 100,
                   float(l.facturada_neto()), float(l.facturada_iva()), float(l.importe(FACTURADA)),
                   float(l.pagado(FACTURADA)), float(l.saldo(FACTURADA)), float(l.comprobado(FACTURADA)),
                   float(l.importe(EFECTIVO)), float(l.pagado(EFECTIVO)), float(l.saldo(EFECTIVO)), float(l.comprobado(EFECTIVO))])
    _formatear(ws, pesos=(4, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15), fechas=(3,))
    for fila in ws.iter_rows(min_row=2, min_col=5, max_col=5):
        fila[0].number_format = '0.00%'

    ws = _hoja(wb, 'Pagos', ['Ref.', 'Fecha', 'Forma', 'Moneda', 'Importe', 'T.C.', 'Importe $', 'Recibo', 'N° recibo',
                             'Factura que paga', 'Imputado', 'Sin imputar', 'Banco / ref.', 'Observaciones', 'Anulado'],
               [8, 12, 14, 8, 15, 8, 16, 9, 18, 20, 16, 16, 18, 40, 9])
    for p in Pago.objects.select_related('comprobante'):
        ws.append([p.ref_planilla, p.fecha, p.get_medio_display(), p.moneda, float(p.importe_origen), float(p.tipo_cambio),
                   float(p.importe_ars), p.tipo_recibo, p.numero_recibo, str(p.comprobante) if p.comprobante else '',
                   float(p.imputado()), float(p.sin_imputar()), p.banco_referencia, p.observaciones, 'Sí' if p.anulado else ''])
    _formatear(ws, pesos=(5, 7, 11, 12), fechas=(2,))

    ws = _hoja(wb, 'Comprobantes', ['Ref.', 'Fecha', 'Tipo', 'Número', 'Importe', 'Motivo', 'Imputado', 'Sin imputar',
                                    'Anticipado', 'Observaciones', 'Anulado'],
               [8, 12, 8, 20, 16, 22, 16, 16, 30, 40, 9])
    for c in Comprobante.objects.prefetch_related('imputaciones__liquidacion'):
        anticipos = ', '.join(f'{imp.liquidacion.codigo} ({motivo})' for imp, motivo in c.anticipos())
        ws.append([c.ref_planilla, c.fecha, c.tipo, c.numero, float(c.importe), c.get_motivo_display(), float(c.imputado()),
                   float(c.sin_imputar()), anticipos, c.observaciones, 'Sí' if c.anulado else ''])
    _formatear(ws, pesos=(5, 7, 8), fechas=(2,))

    ws = _hoja(wb, 'Imputaciones', ['Origen', 'Ref.', 'Fecha', 'Liquidación', 'Parte', 'Importe', 'Observaciones'],
               [12, 22, 12, 13, 28, 16, 40])
    for i in ImputacionPago.objects.select_related('pago', 'liquidacion'):
        ws.append(['Pago', i.pago.ref_planilla or f'#{i.pago_id}', i.pago.fecha, i.liquidacion.codigo, i.get_parte_display(),
                   float(i.importe), i.observaciones])
    for i in ImputacionComprobante.objects.select_related('comprobante', 'liquidacion'):
        ws.append(['Comprobante', str(i.comprobante), i.comprobante.fecha, i.liquidacion.codigo, i.get_parte_display(),
                   float(i.importe), i.observaciones])
    _formatear(ws, pesos=(6,), fechas=(3,))

    salida = io.BytesIO()
    wb.save(salida)
    return salida.getvalue()
