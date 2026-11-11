import io
from datetime import date, datetime
from decimal import Decimal

import openpyxl
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from . import control, importador
from .models import (EFECTIVO, FACTURADA, Articulo, Comprobante, EntregaInsumo, ImputacionComprobante, ImputacionPago,
                     Liquidacion, Pago, ServicioMAT)


def planilla_de_prueba():
    """Planilla chica con la misma forma que "PL - MARCO ANTONIO TOURS NACIONAL 2026" (sin datos reales)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'LIQUIDACIONES'
    ws['B3'] = 0.105
    ws.append([])
    ws.cell(6, 1, 'LIQ-2026-01'); ws.cell(6, 3, datetime(2026, 1, 31)); ws.cell(6, 8, 1000000); ws.cell(6, 9, 0.5)
    ws.cell(7, 1, 'LIQ-2026-02'); ws.cell(7, 3, datetime(2026, 2, 28)); ws.cell(7, 8, 400000); ws.cell(7, 9, 0)

    p = wb.create_sheet('PAGOS')
    filas = [('P-001', datetime(2026, 1, 10), 'EFECTIVO', 'USD', 100, 1000, None, 'REC M', 'M1', None, None, 'Pago a cuenta'),
             ('P-002', datetime(2026, 1, 15), 'TRANSFERENCIA', 'ARS', 552500, 1, None, 'REC A', '700', None, None,
              'Galicia / Pago informado contra FACA A00008-00000339'),
             ('P-003', datetime(2026, 2, 5), 'TRANSFERENCIA', 'ARS', 50000, 1, None, 'REC A', '701', None, None, 'BBVA')]
    for i, f in enumerate(filas, start=4):
        for j, v in enumerate(f, start=1):
            p.cell(i, j, v)

    f = wb.create_sheet('FACTURAS')
    for i, fila in enumerate([('F-001', datetime(2026, 1, 15), 'FAC A', 'A00008-00000339', 'TRANSFERENCIA', 552500, None,
                               None, None, 'Factura/pago a cuenta', 'PAGO'),
                              ('F-002', datetime(2026, 3, 2), 'FAC M', '00020-00000405', 'EFECTIVO', 500000, None, None,
                               None, 'LIQUIDACION ENERO', 'CIERRE')], start=4):
        for j, v in enumerate(fila, start=1):
            f.cell(i, j, v)

    ip = wb.create_sheet('IMPUTACION PAGOS')
    for i, fila in enumerate([('P-001', 'LIQ-2026-01', 'EFECTIVO NETO', 100000),
                              ('P-002', 'LIQ-2026-01', 'TRANSFERENCIA c/IVA', 552500)], start=4):
        for j, v in enumerate(fila, start=1):
            ip.cell(i, j, v)
    ic = wb.create_sheet('IMPUTACION FACTURAS')
    for i, fila in enumerate([('F-001', 'LIQ-2026-01', 'TRANSFERENCIA c/IVA', 552500),
                              ('F-002', 'LIQ-2026-01', 'EFECTIVO NETO', 500000)], start=4):
        for j, v in enumerate(fila, start=1):
            ic.cell(i, j, v)

    m = wb.create_sheet('03-2026')  # mes con detalle y sin fila en LIQUIDACIONES
    m['D3'] = 'VALOR AGUA UNIT.'; m['E3'] = 400
    for j, t in enumerate(['FECHA', 'UNIDAD', 'SERVICIO', 'TARIFA MÍNIMA', 'TARIFA INTERMEDIA', 'TARIFA ÓPTIMA',
                           'TARIFA VENDIDA', 'TARIFA SELECCIONADA', 'UNID. AGUA'], start=1):
        m.cell(6, j, t)
    for j, v in enumerate([datetime(2026, 3, 5), 'MINIBUS', 'CACHI', 800000, 900000, 1000000, 'ÓPTIMA', 1000000, 10], start=1):
        m.cell(7, j, v)
    m['A8'] = 'TOTALES'
    m['A10'] = 'INSUMOS'; m['B10'] = 'COLACIONES'
    for j, t in enumerate(['CÓDIGO', 'ARTÍCULO', 'CANTIDAD', None, 'TOTAL', 'PRECIO'], start=1):
        if t:
            m.cell(11, j, t)
    m['C12'] = datetime(2026, 3, 5); m['D12'] = datetime(2026, 3, 6)
    m['A13'] = 300; m['B13'] = 'Galletas'; m['C13'] = 10; m['D13'] = 5; m['E13'] = 15; m['F13'] = 3000
    m['A14'] = 'TOTAL SECCIÓN'
    salida = io.BytesIO()
    wb.save(salida)
    return salida.getvalue()


class ModeloTest(TestCase):
    def test_liquidacion_en_dos_partes(self):
        liq = Liquidacion.objects.create(periodo=date(2026, 8, 1), precio_agua=Decimal(455))
        ServicioMAT.objects.create(liquidacion=liq, fecha=date(2026, 8, 12), unidad='DOBLE PISO', servicio='COCHABAMBA',
                                   tarifa_minima=7200000, tarifa_intermedia=7800000, tarifa_optima=8100000,
                                   tarifa_elegida='intermedia', unidades_agua=324)
        art = Articulo.objects.create(codigo=200, nombre='Turrón', precio=Decimal('255.20'))
        EntregaInsumo.objects.create(liquidacion=liq, fecha=date(2026, 8, 11), articulo=art, cantidad=432,
                                     precio_unitario=Decimal('255.2'))
        # 7.800.000 + 324 × 455 + 432 × 255,20
        self.assertEqual(liq.neto(), Decimal('7800000') + Decimal('147420') + Decimal('110246.40'))
        self.assertEqual(liq.importe(FACTURADA), liq.facturada_neto() + liq.facturada_iva())
        self.assertEqual(liq.facturada_iva(), (liq.facturada_neto() * Decimal('0.105')).quantize(Decimal('0.01')))
        self.assertEqual(liq.importe(EFECTIVO) + liq.facturada_neto(), liq.neto())
        # Pago imputado a la parte en efectivo
        pago = Pago.objects.create(fecha=date(2026, 9, 3), medio='efectivo', importe_origen=1000000)
        ImputacionPago.objects.create(pago=pago, liquidacion=liq, parte=EFECTIVO, importe=1000000)
        self.assertEqual(liq.saldo(EFECTIVO), liq.importe(EFECTIVO) - 1000000)
        self.assertEqual(liq.saldo(FACTURADA), liq.importe(FACTURADA))
        # Un pago anulado deja de contar
        pago.anulado = True
        pago.save()
        self.assertEqual(liq.saldo(EFECTIVO), liq.importe(EFECTIVO))

    def test_comprobante_anticipado(self):
        liq = Liquidacion.objects.create(periodo=date(2026, 4, 1), fecha_cierre=date(2026, 4, 30), neto_manual=100)
        c = Comprobante.objects.create(fecha=date(2026, 2, 14), tipo='FAC A', numero='1-344', importe=100, motivo='a_cuenta')
        ImputacionComprobante.objects.create(comprobante=c, liquidacion=liq, parte=FACTURADA, importe=50)
        self.assertEqual(c.anticipos()[0][1], 'antes del mes liquidado')
        self.assertEqual(c.sin_imputar(), 50)


class ImportadorTest(TestCase):
    def test_importa_la_planilla(self):
        r = importador.importar(planilla_de_prueba())
        self.assertEqual((r['liquidaciones'], r['pagos'], r['comprobantes']), (3, 3, 2))
        enero = Liquidacion.objects.get(periodo=date(2026, 1, 1))
        self.assertEqual(enero.neto(), 1000000)
        self.assertEqual(enero.importe(EFECTIVO), 500000)
        self.assertEqual(enero.importe(FACTURADA), Decimal('552500.00'))   # 500.000 + IVA 10,5%
        self.assertEqual(enero.saldo(FACTURADA), 0)
        self.assertEqual(enero.saldo(EFECTIVO), 400000)
        febrero = Liquidacion.objects.get(periodo=date(2026, 2, 1))
        self.assertEqual((febrero.importe(FACTURADA), febrero.importe(EFECTIVO)), (0, 400000))
        # Pago en dólares, recibo y vínculo con la factura que nombra la observación
        usd = Pago.objects.get(ref_planilla='P-001')
        self.assertEqual(usd.importe_ars, 100000)
        self.assertEqual(Pago.objects.get(ref_planilla='P-002').comprobante.numero, 'A00008-00000339')
        # Mes con detalle (marzo): abierto, calculado desde servicios + agua + insumos
        marzo = Liquidacion.objects.get(periodo=date(2026, 3, 1))
        self.assertFalse(marzo.cerrada)
        self.assertEqual(marzo.neto(), Decimal('1000000') + Decimal('4000') + Decimal('3000'))
        self.assertEqual(EntregaInsumo.objects.count(), 2)
        self.assertEqual(Articulo.objects.get(codigo=300).precio, Decimal('200.00'))
        # Reimportar reemplaza (no duplica)
        importador.importar(planilla_de_prueba())
        self.assertEqual(Pago.objects.count(), 3)

    def test_controles_y_cuenta_corriente(self):
        importador.importar(planilla_de_prueba())
        cc = control.cuenta_corriente()
        # Cerradas: enero (552.500 + 500.000) y febrero (400.000). Recibido: 100.000 + 552.500 + 50.000
        self.assertEqual(cc['total_liquidado'], Decimal('1452500.00'))
        self.assertEqual(cc['recibido'], Decimal('702500.00'))
        self.assertEqual(cc['saldo'], Decimal('750000.00'))
        self.assertEqual(cc['en_curso'], Decimal('1059867.50'))   # marzo abierta: 1.007.000 + IVA de la mitad facturada
        c = control.controles()
        self.assertEqual([p.ref_planilla for p in c['transferencias_sin_factura']], ['P-003'])
        self.assertEqual([p.ref_planilla for p, _ in c['pagos_sin_imputar']], ['P-003'])
        self.assertTrue(any(comp.ref_planilla == 'F-001' and motivo == 'antes del cierre' for comp, _, motivo in c['anticipados']))
        self.assertTrue(any(liq.periodo == date(2026, 2, 1) for liq, _ in c['pendiente_facturar']) is False)


class VistasTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('tatiana', 't@x.com', 'clave-segura-123')
        self.client.force_login(self.user)

    def test_pantallas(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        archivo = SimpleUploadedFile('mat.xlsx', planilla_de_prueba())
        r = self.client.post(reverse('marcoantonio:importar'), {'archivo': archivo, 'confirmar': 'on'})
        self.assertContains(r, 'Planilla importada')
        self.assertContains(self.client.get(reverse('marcoantonio:tablero')), 'Parte en efectivo sin factura')
        liq = Liquidacion.objects.get(periodo=date(2026, 3, 1))
        r = self.client.get(reverse('marcoantonio:liquidacion', args=[liq.pk]))
        self.assertContains(r, 'CACHI')
        self.assertContains(r, 'Galletas')
        for nombre in ('pagos', 'comprobantes', 'articulos', 'pago_nuevo', 'comprobante_nuevo', 'liquidacion_nueva'):
            self.assertEqual(self.client.get(reverse(f'marcoantonio:{nombre}')).status_code, 200, nombre)
        r = self.client.get(reverse('marcoantonio:excel'))
        wb = openpyxl.load_workbook(io.BytesIO(r.content))
        self.assertEqual(wb.sheetnames, ['Liquidaciones', 'Pagos', 'Comprobantes', 'Imputaciones'])

    def test_cargar_pago_imputado_y_cerrar(self):
        liq = Liquidacion.objects.create(periodo=date(2026, 9, 1), neto_manual=200000)
        datos = {'fecha': '2026-10-01', 'medio': 'transferencia', 'moneda': 'ARS', 'importe_origen': '110500',
                 'tipo_cambio': '1', 'banco_referencia': 'Galicia', 'tipo_recibo': 'REC A', 'numero_recibo': '800',
                 'comprobante': '', 'observaciones': '',
                 'imp-TOTAL_FORMS': '2', 'imp-INITIAL_FORMS': '0', 'imp-MIN_NUM_FORMS': '0', 'imp-MAX_NUM_FORMS': '1000',
                 'imp-0-liquidacion': liq.pk, 'imp-0-parte': FACTURADA, 'imp-0-importe': '110500', 'imp-0-observaciones': ''}
        r = self.client.post(reverse('marcoantonio:pago_nuevo'), datos)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(liq.saldo(FACTURADA), 0)
        self.client.post(reverse('marcoantonio:liquidacion_cerrar', args=[liq.pk]))
        liq.refresh_from_db()
        self.assertTrue(liq.cerrada)
        art = Articulo.objects.create(codigo=1, nombre='Alfajor', precio=300)
        self.client.post(reverse('marcoantonio:entrega_nueva', args=[liq.pk]),
                         {'fecha': '2026-09-10', 'articulo': art.pk, 'cantidad': '4', 'observaciones': ''})
        self.assertEqual(liq.entregas.get().total, Decimal('1200.00'))

    def test_sin_permiso(self):
        self.client.force_login(User.objects.create_user('otro', password='x'))
        self.assertEqual(self.client.get(reverse('marcoantonio:tablero')).status_code, 403)


class SalidasTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('tatiana', 't@x.com', 'clave-segura-123')
        self.client.force_login(self.user)

    def _salida(self, liq, dia, precio):
        return ServicioMAT.objects.create(liquidacion=liq, fecha=date(2026, 10, dia), unidad='DP', servicio=f'S{dia}',
                                          tarifa_elegida='otra', tarifa_otra=precio)

    def test_reparto_y_estados(self):
        liq = Liquidacion.objects.create(periodo=date(2026, 10, 1), porcentaje_facturado=0)
        s1, s2 = self._salida(liq, 5, 1000000), self._salida(liq, 20, 500000)
        art = Articulo.objects.create(codigo=7, nombre='Alfajor', precio=100)
        EntregaInsumo.objects.create(liquidacion=liq, servicio=s1, fecha=date(2026, 10, 5), articulo=art,
                                     cantidad=10, precio_unitario=100)
        self.assertEqual(s1.neto(), Decimal('1001000'))
        self.assertEqual(s1.estado_pagos()['estado'], 'pendiente')
        # Pago a cuenta del mes: se reparte de la salida más vieja a la más nueva
        pago = Pago.objects.create(fecha=date(2026, 10, 25), medio='efectivo', importe_origen=1200000)
        ImputacionPago.objects.create(pago=pago, liquidacion=liq, parte=EFECTIVO, importe=1200000)
        rep = liq.reparto_pagos()
        self.assertEqual(s1.estado_pagos(rep)['estado'], 'pagada')
        e2 = s2.estado_pagos(rep)
        self.assertEqual(e2['estado'], 'parcial')
        self.assertEqual(e2['saldo'], Decimal('301000'))
        # Pago directo a la segunda salida
        pago2 = Pago.objects.create(fecha=date(2026, 10, 28), medio='efectivo', importe_origen=301000)
        ImputacionPago.objects.create(pago=pago2, liquidacion=liq, servicio=s2, parte=EFECTIVO, importe=301000)
        self.assertEqual(s2.estado_pagos(liq.reparto_pagos())['estado'], 'pagada')

    def test_pantallas_de_salidas(self):
        datos = {'fecha': '2026-10-14', 'unidad': 'DOBLE PISO', 'servicio': 'CAFAYATE', 'tarifa_minima': '',
                 'tarifa_intermedia': '', 'tarifa_optima': '', 'tarifa_elegida': 'otra', 'tarifa_otra': '2000000',
                 'unidades_agua': '0', 'observaciones': ''}
        r = self.client.post(reverse('marcoantonio:salida_nueva'), datos)
        sal = ServicioMAT.objects.get()
        self.assertRedirects(r, reverse('marcoantonio:salida', args=[sal.pk]))
        self.assertEqual(sal.liquidacion.periodo, date(2026, 10, 1))
        art = Articulo.objects.create(codigo=3, nombre='Agua saborizada', precio=500)
        self.client.post(reverse('marcoantonio:salida_insumo', args=[sal.pk]),
                         {'fecha': '2026-10-14', 'articulo': art.pk, 'cantidad': '40', 'observaciones': ''})
        self.assertEqual(sal.total_insumos(), Decimal('20000.00'))
        r = self.client.get(reverse('marcoantonio:salida', args=[sal.pk]))
        self.assertContains(r, 'Agua saborizada')
        self.assertContains(r, 'Pendiente')
        self.assertContains(self.client.get(reverse('marcoantonio:salidas')), 'CAFAYATE')
        self.assertContains(self.client.get(reverse('marcoantonio:liquidacion', args=[sal.liquidacion_id])), 'CAFAYATE')
        r = self.client.get(reverse('marcoantonio:pago_nuevo') + f'?salida={sal.pk}')
        self.assertContains(r, 'CAFAYATE')
        # Pago imputado directo a la salida (el mes se completa solo)
        total = sal.total()
        datos = {'fecha': '2026-10-30', 'medio': 'efectivo', 'moneda': 'ARS', 'importe_origen': str(total),
                 'tipo_cambio': '1', 'banco_referencia': '', 'tipo_recibo': '', 'numero_recibo': '',
                 'comprobante': '', 'observaciones': '',
                 'imp-TOTAL_FORMS': '2', 'imp-INITIAL_FORMS': '0', 'imp-MIN_NUM_FORMS': '0', 'imp-MAX_NUM_FORMS': '1000',
                 'imp-0-servicio': sal.pk, 'imp-0-liquidacion': '', 'imp-0-parte': EFECTIVO,
                 'imp-0-importe': str(sal.importe(EFECTIVO)), 'imp-0-observaciones': '',
                 'imp-1-servicio': sal.pk, 'imp-1-liquidacion': '', 'imp-1-parte': FACTURADA,
                 'imp-1-importe': str(sal.importe(FACTURADA)), 'imp-1-observaciones': ''}
        r = self.client.post(reverse('marcoantonio:pago_nuevo'), datos)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(ImputacionPago.objects.filter(liquidacion=sal.liquidacion).count(), 2)
        self.assertEqual(sal.estado_pagos()['estado'], 'pagada')
        self.assertContains(self.client.get(reverse('marcoantonio:salidas') + '?estado=pagadas'), 'CAFAYATE')
