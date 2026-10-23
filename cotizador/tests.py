import io
import zipfile
from datetime import date, datetime
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import calculo, rutas, word
from .models import Cliente, Cotizacion, Lugar, Movimiento, Parametros, TipoVehiculo


def datos_cot302(**cambios):
    """Datos de la hoja COT302 de la planilla (Club Cachorros, Salta - San Martín, Córdoba)."""
    datos = {
        'km_servicio': 1400, 'km_vacios': 300, 'dias': 5, 'noches': 5, 'choferes': 2, 'viaticos_por_chofer': 10,
        'habitaciones': 1, 'cantidad_vehiculos': 1, 'vehiculo': TipoVehiculo.objects.get(nombre='Piso elevado'),
        'incluye_hotel': True, 'incluye_estacionamiento': True, 'incluye_lavadero': True,
        'peaje': 0, 'otros_gastos': 0, 'tarifa_neta': Decimal(6950000),
    }
    datos.update(cambios)
    return datos


class CalculoTest(TestCase):
    def test_coincide_con_la_planilla(self):
        r = calculo.calcular(Parametros.actuales(), datos_cot302())
        importes = {i['nombre']: i['importe'] for i in r['items']}
        self.assertEqual(importes['Cargas sociales'], Decimal('398400.00'))
        self.assertEqual(importes['Sueldo de conductor'], Decimal('830133.33'))
        self.assertEqual(importes['Gastos de administración'], Decimal('49252.41'))
        self.assertEqual(importes['Hotel'], Decimal('350000.00'))
        self.assertEqual(importes['Viáticos'], Decimal('600000.00'))
        self.assertEqual(importes['Combustible'], Decimal('1416666.67'))
        self.assertEqual(importes['Depreciación'], Decimal('22947.50'))
        self.assertEqual(importes['Seguro obligatorio'], Decimal('23809.52'))
        # Total de la planilla: 4.071.209,43
        self.assertEqual(r['costo'], Decimal('4071209.43'))
        minimo = r['filas'][1]
        self.assertEqual(minimo['valor_km'], Decimal('2874'))
        self.assertEqual(minimo['total'], Decimal('4885800.00'))
        self.assertEqual(r['final']['iva'], Decimal('729750.00'))
        self.assertEqual(r['final']['por_pax'], Decimal('144791.67'))

    def test_dos_vehiculos_duplican_costo(self):
        p = Parametros.actuales()
        uno = calculo.calcular(p, datos_cot302())['costo']
        dos = calculo.calcular(p, datos_cot302(cantidad_vehiculos=2))['costo']
        self.assertAlmostEqual(dos, uno * 2, delta=Decimal('0.1'))

    def test_sin_km_no_divide_por_cero(self):
        r = calculo.calcular(Parametros.actuales(), datos_cot302(km_servicio=0, km_vacios=0))
        self.assertEqual(r['costo_km'], 0)


class BaseVistas(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('tatiana', 't@x.com', 'clave-segura-123')
        self.client.force_login(self.user)
        self.vehiculo = TipoVehiculo.objects.get(nombre='Piso elevado')

    def post_datos(self, **cambios):
        datos = {
            'numero': 303, 'fecha': '2026-10-23', 'cliente': '', 'nuevo_cliente': 'Mauricio Vivas', 'nuevo_cliente_telefono': '387 555',
            'origen': 'Salta, Salta', 'paradas': 'Orán, Salta', 'ida_y_vuelta': 'on',
            'itinerario': 'Salta, Salta – Orán, Salta – Salta, Salta. Con paradas intermedias.',
            'km_servicio': '540', 'km_vacios': '60', 'km_mapa': '540',
            'salida': '2026-11-09T07:00', 'regreso': '2026-11-09T19:30', 'texto_salida': 'desde Salta. Ida y regreso en el día.',
            'dias': '1', 'noches': '0', 'vehiculo': self.vehiculo.pk, 'cantidad_vehiculos': '1',
            'descripcion_vehiculo': 'BUS  Piso Elevado 50 pasajeros', 'choferes': '1', 'viaticos_por_chofer': '2',
            'habitaciones': '1', 'incluye_estacionamiento': 'on', 'peaje': '0', 'otros_gastos': '0',
            'tarifa_neta': '1700000', 'incluye': 'Traslado ida y regreso.\nViáticos de personal.',
            'no_incluye': 'Gastos no especificados & extras.', 'notas_internas': '',
        }
        datos.update(cambios)
        return datos


class VistasTest(BaseVistas):
    def test_requiere_login(self):
        self.client.logout()
        r = self.client.get(reverse('cotizador:lista'))
        self.assertEqual(r.status_code, 302)

    def test_crear_y_descargar_word(self):
        r = self.client.post(reverse('cotizador:nueva'), self.post_datos())
        self.assertEqual(r.status_code, 302, getattr(r, 'context', None) and r.context['form'].errors)
        cot = Cotizacion.objects.get(numero=303)
        self.assertGreater(cot.costo_total, 0)
        self.assertIn('parametros', cot.detalle)

        r = self.client.get(reverse('cotizador:word', args=[cot.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertIn('COT_303_Mauricio_Vivas_09-11-26.docx', r['Content-Disposition'])
        xml = zipfile.ZipFile(io.BytesIO(r.content)).read('word/document.xml').decode()
        self.assertNotIn('{{', xml)
        for texto in ('Salta, 23 de octubre 2026', '303', 'MAURICIO VIVAS', '09/11/2026 07:00 HS desde Salta',
                      'TOTAL: $1.700.000', '+IVA 10,5%: $178.500', 'TOTAL: $1.878.500', 'Viáticos de personal.',
                      'Gastos no especificados &amp; extras.', 'seña del 40%', 'vigencia de 7 días',
                      '01 ', 'BUS  Piso Elevado 50 pasajeros'):
            self.assertIn(texto, xml)

        self.assertEqual(self.client.get(reverse('cotizador:detalle', args=[cot.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('cotizador:lista') + '?q=vivas').status_code, 200)
        self.assertEqual(self.client.get(reverse('cotizador:nueva') + f'?copiar={cot.pk}').status_code, 200)

    def test_vista_previa(self):
        r = self.client.post(reverse('cotizador:calcular'), self.post_datos())
        self.assertContains(r, 'Margen mínimo')
        self.assertContains(r, 'Tarifa final')

    def test_parametros_editables(self):
        datos = {f.name: getattr(Parametros.actuales(), f.name) for f in Parametros._meta.concrete_fields
                 if f.name not in ('id', 'actualizado', 'actualizado_por')}
        datos['precio_combustible'] = '3000'
        r = self.client.post(reverse('cotizador:parametros'), datos)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Parametros.actuales().precio_combustible, Decimal('3000'))

    def test_usuario_sin_permiso_no_edita_parametros(self):
        self.client.force_login(User.objects.create_user('vendedor', password='x'))
        self.assertEqual(self.client.get(reverse('cotizador:parametros')).status_code, 403)

    def test_buscar_km(self):
        def falso_get(url, params=None, **kw):
            respuesta = mock.Mock()
            respuesta.raise_for_status = lambda: None
            if 'nominatim' in url:
                respuesta.json = lambda: [{'display_name': params['q'], 'lat': '-24.8', 'lon': '-65.4'}]
            else:
                respuesta.json = lambda: {'code': 'Ok', 'routes': [{'legs': [{'distance': 271451}, {'distance': 272017}]}]}
            return respuesta

        with mock.patch.object(rutas.requests, 'get', side_effect=falso_get):
            r = self.client.post(reverse('cotizador:buscar_km'),
                                 {'origen': 'Salta, Salta', 'paradas': 'Orán, Salta', 'ida_y_vuelta': 'on'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['km'], 543)
        self.assertEqual(Lugar.objects.count(), 2)

    def test_buscar_km_sin_destino(self):
        r = self.client.post(reverse('cotizador:buscar_km'), {'origen': 'Salta', 'paradas': ''})
        self.assertEqual(r.status_code, 400)


class VentasTest(BaseVistas):
    """Estado de la cotización, cuenta corriente y clientes."""

    def crear(self, **cambios):
        self.client.post(reverse('cotizador:nueva'), self.post_datos(**cambios))
        return Cotizacion.objects.latest('id')

    def test_cliente_nuevo_se_reutiliza(self):
        cot = self.crear()
        self.assertEqual(cot.cliente.nombre, 'Mauricio Vivas')
        self.assertEqual(cot.cliente.telefono, '387 555')
        otra = self.crear(numero=304, nuevo_cliente='mauricio vivas')
        self.assertEqual(otra.cliente, cot.cliente)
        tercera = self.crear(numero=305, nuevo_cliente='', cliente=cot.cliente.pk)
        self.assertEqual(Cliente.objects.count(), 1)
        self.assertEqual(tercera.cliente, cot.cliente)

    def test_sin_cliente_da_error(self):
        r = self.client.post(reverse('cotizador:nueva'), self.post_datos(nuevo_cliente=''))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Cotizacion.objects.exists())

    def test_aceptar_cobrar_y_saldo(self):
        cot = self.crear()
        self.assertEqual(cot.estado, Cotizacion.PENDIENTE)
        self.client.post(reverse('cotizador:cambiar_estado', args=[cot.pk]), {'estado': 'aceptada'})
        cot.refresh_from_db()
        self.assertEqual(cot.estado, Cotizacion.ACEPTADA)
        # El cargo automático es el total con IVA (1.700.000 + 10,5%)
        self.assertEqual(cot.total_cargos(), Decimal('1878500'))
        self.assertEqual(cot.sena_requerida(), 751400)

        url = reverse('cotizador:movimiento_nuevo', args=[cot.pk])
        self.client.post(url, {'fecha': '2026-10-25', 'tipo': 'pago', 'concepto': 'Seña', 'importe': '800000',
                               'medio': 'transferencia', 'referencia': 'op 123'})
        self.client.post(url, {'fecha': '2026-10-26', 'tipo': 'cargo', 'concepto': 'Km extra', 'importe': '50000'})
        self.assertEqual(cot.saldo(), Decimal('1128500.00'))
        # Pago sin medio: no se carga
        self.client.post(url, {'fecha': '2026-10-26', 'tipo': 'pago', 'concepto': 'x', 'importe': '10'})
        self.assertEqual(cot.movimientos.count(), 3)

        r = self.client.get(reverse('cotizador:detalle', args=[cot.pk]))
        self.assertContains(r, 'Cuenta corriente de la venta')
        r = self.client.get(reverse('cotizador:ventas'))
        self.assertContains(r, 'Mauricio Vivas')
        r = self.client.get(reverse('cotizador:cliente', args=[cot.cliente_id]))
        self.assertContains(r, '1.128.500')

        # Si cambia el precio, el cargo automático sigue al nuevo total
        self.client.post(reverse('cotizador:editar', args=[cot.pk]),
                         self.post_datos(cliente=cot.cliente_id, nuevo_cliente='', tarifa_neta='2000000'))
        self.assertEqual(cot.movimientos.get(automatico=True).importe, Decimal('2210000'))

        # Con pagos cargados no se puede rechazar ni eliminar
        self.client.post(reverse('cotizador:cambiar_estado', args=[cot.pk]), {'estado': 'rechazada'})
        cot.refresh_from_db()
        self.assertEqual(cot.estado, Cotizacion.ACEPTADA)
        self.client.post(reverse('cotizador:eliminar', args=[cot.pk]))
        self.assertTrue(Cotizacion.objects.filter(pk=cot.pk).exists())

    def test_rechazar_y_volver(self):
        cot = self.crear()
        self.client.post(reverse('cotizador:cambiar_estado', args=[cot.pk]), {'estado': 'aceptada'})
        self.client.post(reverse('cotizador:cambiar_estado', args=[cot.pk]), {'estado': 'rechazada', 'motivo': 'Precio'})
        cot.refresh_from_db()
        self.assertEqual((cot.estado, cot.motivo_rechazo), (Cotizacion.RECHAZADA, 'Precio'))
        self.assertFalse(Movimiento.objects.exists())
        r = self.client.get(reverse('cotizador:lista') + '?estado=rechazada')
        self.assertContains(r, 'Mauricio Vivas')

    def test_pantallas_de_clientes(self):
        r = self.client.post(reverse('cotizador:cliente_nuevo'), {'nombre': 'Colegio X', 'cuit': '30-1', 'email': ''})
        cliente = Cliente.objects.get(nombre='Colegio X')
        self.assertRedirects(r, reverse('cotizador:cliente', args=[cliente.pk]))
        self.assertContains(self.client.get(reverse('cotizador:clientes') + '?q=colegio'), 'Colegio X')
        self.assertContains(self.client.get(reverse('cotizador:nueva') + f'?cliente={cliente.pk}'), 'selected')
        self.client.post(reverse('cotizador:cliente_eliminar', args=[cliente.pk]))
        self.assertFalse(Cliente.objects.exists())


class ExcelTest(BaseVistas):
    def test_cuentas_corrientes_en_excel(self):
        import openpyxl
        self.client.post(reverse('cotizador:nueva'), self.post_datos())
        cot = Cotizacion.objects.get()
        self.client.post(reverse('cotizador:cambiar_estado', args=[cot.pk]), {'estado': 'aceptada'})
        self.client.post(reverse('cotizador:movimiento_nuevo', args=[cot.pk]),
                         {'fecha': '2026-10-25', 'tipo': 'pago', 'concepto': 'Seña', 'importe': '800000', 'medio': 'efectivo'})
        for url in (reverse('cotizador:cuentas_excel'), reverse('cotizador:cuentas_excel') + f'?cliente={cot.cliente_id}'):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            wb = openpyxl.load_workbook(io.BytesIO(r.content))
            self.assertEqual(wb.sheetnames, ['Resumen por cliente', 'Ventas', 'Movimientos'])
            resumen = wb['Resumen por cliente']
            self.assertEqual(resumen['A2'].value, 'Mauricio Vivas')
            self.assertEqual(resumen['G2'].value, 1878500 - 800000)
            self.assertEqual(wb['Movimientos']['I3'].value, 1078500)
