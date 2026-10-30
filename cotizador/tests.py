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
        # La planilla no tenía impuestos sobre la venta: se comparan con esos impuestos destildados.
        r = calculo.calcular(Parametros.actuales(), datos_cot302(items_excluidos='Impuestos sobre la venta'))
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
        uno = calculo.calcular(p, datos_cot302())['costo_operativo']
        dos = calculo.calcular(p, datos_cot302(cantidad_vehiculos=2))['costo_operativo']
        self.assertAlmostEqual(dos, uno * 2, delta=Decimal('0.1'))

    def test_proyeccion_por_inflacion(self):
        p = Parametros.actuales()
        hoy = calculo.calcular(p, datos_cot302())
        # Viaje que sale 90 días después de la cotización: 3 meses al 2% = +6,1%
        futuro = calculo.calcular(p, datos_cot302(fecha=date(2026, 10, 1), salida=datetime(2026, 12, 30, 7, 0),
                                                  proyectar_inflacion=True, inflacion_mensual=Decimal(2)))
        self.assertEqual(futuro['inflacion']['meses'], Decimal('3.0'))
        self.assertEqual(futuro['inflacion']['porcentaje'], Decimal('6.1'))
        self.assertEqual(futuro['inflacion']['costo_hoy'], hoy['costo_operativo'])
        self.assertAlmostEqual(futuro['costo_operativo'], hoy['costo_operativo'] * Decimal('1.061208'), delta=Decimal(1))
        self.assertGreater(futuro['filas'][1]['total'], hoy['filas'][1]['total'])
        # Dentro de los 30 días, o con la opción apagada, no se proyecta
        cerca = datos_cot302(fecha=date(2026, 10, 1), salida=datetime(2026, 10, 20, 7, 0), proyectar_inflacion=True,
                             inflacion_mensual=Decimal(2))
        self.assertIsNone(calculo.calcular(p, cerca)['inflacion'])
        apagado = datos_cot302(fecha=date(2026, 10, 1), salida=datetime(2026, 12, 30, 7, 0), proyectar_inflacion=False,
                               inflacion_mensual=Decimal(2))
        self.assertEqual(calculo.calcular(p, apagado)['costo_operativo'], hoy['costo_operativo'])

    def test_impuestos_sobre_la_venta(self):
        p = Parametros.actuales()
        r = calculo.calcular(p, datos_cot302())
        self.assertEqual(r['tasa_impuestos'], Decimal('6.20'))
        # Sobre la tarifa final de 6.950.000: 6,2% = 430.900
        impuestos = {i['nombre']: i for i in r['items']}['Impuestos sobre la venta']
        self.assertEqual(impuestos['importe'], Decimal('430900.00'))
        self.assertEqual(r['costo'], r['costo_operativo'] + Decimal('430900.00'))
        self.assertEqual(r['final']['ganancia'], Decimal('6950000') - r['costo_operativo'] - Decimal('430900.00'))
        # El precio "Costo" cubre los impuestos: ganancia cero
        self.assertEqual(r['filas'][0]['ganancia'], 0)
        # El margen mínimo (20%) queda limpio después de impuestos
        minimo = r['filas'][1]
        self.assertAlmostEqual(minimo['ganancia'], r['costo_operativo'] * Decimal('0.2'), delta=Decimal(2000))
        # El seguro: póliza ÷ flota ÷ 30 × días = 2.000.000 ÷ 14 ÷ 30 × 5
        seguro = {i['nombre']: i['importe'] for i in r['items']}['Seguro obligatorio']
        self.assertEqual(seguro, Decimal('23809.52'))

    def test_factor_y_valor_dia_por_cotizacion(self):
        p = Parametros.actuales()
        base = calculo.calcular(p, datos_cot302())
        sueldo = lambda r: {i['nombre']: i['importe'] for i in r['items']}['Sueldo de conductor']
        cargas = lambda r: {i['nombre']: i['importe'] for i in r['items']}['Cargas sociales']
        # Mismo cálculo: 480 × 200 × 5 días × 2 choferes + no remunerativo
        otro = calculo.calcular(p, datos_cot302(factor_sueldo_conductor=Decimal(200)))
        self.assertEqual(sueldo(otro), Decimal(480 * 200 * 5 * 2) + Decimal('33333.33'))
        self.assertEqual(cargas(otro), Decimal('480000.00'))   # 50% × 480 × 200 × 5 × 2
        self.assertGreater(otro['costo_operativo'], base['costo_operativo'])
        valor = calculo.calcular(p, datos_cot302(valor_dia_turismo=Decimal(500)))
        self.assertEqual(sueldo(valor), Decimal(500 * 166 * 5 * 2) + Decimal('33333.33'))

    def test_colaciones(self):
        p = Parametros.actuales()
        sin = calculo.calcular(p, datos_cot302())
        con = calculo.calcular(p, datos_cot302(colaciones_cantidad=45, colaciones_precio=Decimal(3500)))
        colaciones = {i['nombre']: i for i in con['items']}['Colaciones']
        self.assertEqual(colaciones['importe'], Decimal('157500.00'))
        self.assertEqual(colaciones['detalle'], '45 × $3.500')
        self.assertEqual(con['costo_operativo'], sin['costo_operativo'] + Decimal('157500'))
        # Se puede destildar como cualquier costo
        quitado = calculo.calcular(p, datos_cot302(colaciones_cantidad=45, colaciones_precio=Decimal(3500),
                                                   items_excluidos='Colaciones'))
        self.assertEqual(quitado['costo_operativo'], sin['costo_operativo'])

    def test_destildar_costos(self):
        p = Parametros.actuales()
        todo = calculo.calcular(p, datos_cot302())
        sin = calculo.calcular(p, datos_cot302(items_excluidos='Lavadero|Hotel'))
        self.assertEqual(sin['costo_operativo'], todo['costo_operativo'] - Decimal('340000') - Decimal('350000'))
        lavadero = {i['nombre']: i for i in sin['items']}['Lavadero']
        self.assertTrue(lavadero['excluido'])
        self.assertEqual(lavadero['importe'], Decimal('340000.00'))   # se sigue mostrando
        self.assertEqual(sin['excluidos'], ['Hotel', 'Lavadero'])

    def test_varios_vehiculos(self):
        p = Parametros.actuales()
        bus = TipoVehiculo.objects.get(nombre='Piso elevado')
        minibus = TipoVehiculo.objects.get(nombre='Minibus')
        minibus.rendimiento_km_litro = Decimal(6)
        minibus.save()
        solo_bus = calculo.calcular(p, datos_cot302())
        r = calculo.calcular(p, datos_cot302(lineas=[{'vehiculo': bus, 'cantidad': 1, 'choferes': 2},
                                                     {'vehiculo': minibus, 'cantidad': 1, 'choferes': 1}]))
        self.assertEqual(r['capacidad'], 48 + 22)
        combustible = {i['nombre']: i['importe'] for i in r['items']}['Combustible']
        # bus 1700 km / 3 km/l + minibus 1700 km / 6 km/l, a $2500
        self.assertEqual(combustible, Decimal('1416666.67') + Decimal('708333.33'))
        self.assertGreater(r['costo'], solo_bus['costo'])
        self.assertLess(r['costo'], solo_bus['costo'] * 2)

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
            'dias': '1', 'noches': '0', 'viaticos_por_chofer': '2',
            'lineas-TOTAL_FORMS': '1', 'lineas-INITIAL_FORMS': '0', 'lineas-MIN_NUM_FORMS': '1', 'lineas-MAX_NUM_FORMS': '1000',
            'lineas-0-vehiculo': self.vehiculo.pk, 'lineas-0-cantidad': '1', 'lineas-0-choferes': '1',
            'lineas-0-descripcion': 'BUS  Piso Elevado 50 pasajeros',
            'habitaciones': '1', 'incluye_estacionamiento': 'on', 'peaje': '0', 'otros_gastos': '0', 'colaciones_cantidad': '0', 'colaciones_precio': '0', 'valor_dia_turismo': '480', 'factor_sueldo_conductor': '166',
            'inflacion_mensual': '1.70', 'tarifa_neta': '1700000', 'incluye': 'Traslado ida y regreso.\nViáticos de personal.',
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

    def test_word_con_dos_tipos_de_vehiculo(self):
        minibus = TipoVehiculo.objects.get(nombre='Minibus')
        datos = self.post_datos(**{'lineas-TOTAL_FORMS': '2', 'lineas-1-vehiculo': minibus.pk, 'lineas-1-cantidad': '2',
                                   'lineas-1-choferes': '1', 'lineas-1-descripcion': 'MINIBUS  22 pasajeros'})
        self.client.post(reverse('cotizador:nueva'), datos)
        cot = Cotizacion.objects.get()
        self.assertEqual(cot.vehiculos_texto, '1 × Piso elevado, 2 × Minibus')
        self.assertEqual(cot.detalle['capacidad'], 92)
        xml = zipfile.ZipFile(io.BytesIO(word.generar(cot))).read('word/document.xml').decode()
        self.assertIn('BUS  Piso Elevado 50 pasajeros', xml)
        self.assertIn('MINIBUS  22 pasajeros', xml)
        self.assertIn('>02 <', xml)
        # Editar: quitar el minibus
        linea = cot.lineas.get(vehiculo=minibus)
        datos.update({'lineas-INITIAL_FORMS': '2', 'lineas-0-id': cot.lineas.exclude(pk=linea.pk).get().pk,
                      'lineas-1-id': linea.pk, 'lineas-1-DELETE': 'on'})
        self.client.post(reverse('cotizador:editar', args=[cot.pk]), datos)
        self.assertEqual(cot.lineas.count(), 1)

    def test_colaciones_en_la_cotizacion(self):
        p = Parametros.actuales()
        p.precio_colacion = Decimal(4000)
        p.save()
        self.assertContains(self.client.get(reverse('cotizador:nueva')), 'value="4000.00"')
        self.client.post(reverse('cotizador:nueva'), self.post_datos(colaciones_cantidad='20', colaciones_precio='4000'))
        cot = Cotizacion.objects.get()
        self.assertEqual((cot.colaciones_cantidad, cot.colaciones_precio), (20, Decimal('4000')))
        self.assertContains(self.client.get(reverse('cotizador:detalle', args=[cot.pk])), '20 × $4.000')

    def test_destildar_se_guarda_en_la_cotizacion(self):
        self.client.post(reverse('cotizador:nueva'), self.post_datos(items_excluidos='Lavadero'))
        cot = Cotizacion.objects.get()
        self.assertEqual(cot.items_excluidos, 'Lavadero')
        self.assertEqual(cot.detalle['excluidos'], ['Lavadero'])
        r = self.client.get(reverse('cotizador:detalle', args=[cot.pk]))
        self.assertContains(r, 'no se suma')
        r = self.client.post(reverse('cotizador:calcular'), self.post_datos(items_excluidos='Lavadero'))
        self.assertContains(r, 'data-item="Lavadero"')
        self.assertNotContains(r, 'data-item="Lavadero" checked')

    def test_vista_previa(self):
        r = self.client.post(reverse('cotizador:calcular'), self.post_datos())
        self.assertContains(r, 'Mínimo (20%)')
        self.assertContains(r, 'usar-tarifa')
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
            respuesta = mock.Mock(status_code=200)
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

    def test_buscar_km_con_respaldo_si_nominatim_y_osrm_fallan(self):
        """En Render, Nominatim y el OSRM principal pueden rechazar los pedidos: se usan Photon y el otro OSRM."""
        usados = []

        def falso_get(url, params=None, **kw):
            usados.append(url.split('/')[2])
            if 'nominatim' in url or 'project-osrm' in url:
                return mock.Mock(status_code=403, text='Access blocked')
            if 'photon' in url:
                return mock.Mock(status_code=200, json=lambda: {'features': [{
                    'properties': {'name': 'Metán', 'state': 'Salta', 'country': 'Argentina'},
                    'geometry': {'coordinates': [-64.97, -25.49]}}]})
            return mock.Mock(status_code=200, json=lambda: {'code': 'Ok', 'routes': [{'legs': [{'distance': 139000}, {'distance': 139400}]}]})

        with mock.patch.object(rutas.requests, 'get', side_effect=falso_get):
            r = self.client.post(reverse('cotizador:buscar_km'),
                                 {'origen': 'Salta, Salta', 'paradas': 'Metán, Salta', 'ida_y_vuelta': 'on'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['km'], 278)
        self.assertIn('photon.komoot.io', usados)
        self.assertIn('routing.openstreetmap.de', usados)
        self.assertEqual(Lugar.objects.get(busqueda='metán, salta').nombre, 'Metán, Salta, Argentina')

    def test_buscar_km_todo_caido_explica_que_fallo(self):
        with mock.patch.object(rutas.requests, 'get', side_effect=rutas.requests.ConnectionError('sin red')):
            r = self.client.post(reverse('cotizador:buscar_km'), {'origen': 'Salta, Salta', 'paradas': 'Metán, Salta'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('Nominatim no respondió', r.json()['error'])
        self.assertIn('cargá los km a mano', r.json()['error'])

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


class ReciboTest(BaseVistas):
    def test_letras(self):
        from .letras import numero_a_letras, pesos_en_letras
        self.assertEqual(numero_a_letras(21000), 'veintiún mil')
        self.assertEqual(numero_a_letras(1878500), 'un millón ochocientos setenta y ocho mil quinientos')
        self.assertEqual(numero_a_letras(100), 'cien')
        self.assertEqual(numero_a_letras(121000000), 'ciento veintiún millones')
        self.assertEqual(pesos_en_letras(Decimal('800000.50')), 'PESOS OCHOCIENTOS MIL CON 50/100')

    def test_recibo_de_pago(self):
        self.client.post(reverse('cotizador:nueva'), self.post_datos())
        cot = Cotizacion.objects.get()
        self.client.post(reverse('cotizador:cambiar_estado', args=[cot.pk]), {'estado': 'aceptada'})
        url = reverse('cotizador:movimiento_nuevo', args=[cot.pk])
        self.client.post(url, {'fecha': '2026-10-25', 'tipo': 'pago', 'concepto': 'Seña', 'importe': '800000', 'medio': 'efectivo'})
        self.client.post(url, {'fecha': '2026-10-28', 'tipo': 'pago', 'concepto': 'Saldo', 'importe': '1078500',
                               'medio': 'transferencia', 'referencia': 'op 99'})
        primero, segundo = cot.movimientos.filter(tipo='pago').order_by('numero_recibo')
        self.assertEqual((primero.numero_recibo, segundo.numero_recibo), (1, 2))
        self.assertIsNone(cot.movimientos.get(tipo='cargo').numero_recibo)

        r = self.client.get(reverse('cotizador:recibo', args=[segundo.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertIn('Recibo_000002_Mauricio_Vivas.docx', r['Content-Disposition'])
        xml = zipfile.ZipFile(io.BytesIO(r.content)).read('word/document.xml').decode()
        for texto in ('RECIBO N° 000002', 'MAURICIO VIVAS', 'PESOS UN MILLÓN SETENTA Y OCHO MIL QUINIENTOS CON 00/100',
                      'Transferencia – op 99', '$ 1.878.500', '$ 0'):
            self.assertIn(texto, xml)
        # Un cargo no tiene recibo
        self.assertEqual(self.client.get(reverse('cotizador:recibo', args=[cot.movimientos.get(tipo='cargo').pk])).status_code, 404)
        self.assertContains(self.client.get(reverse('cotizador:detalle', args=[cot.pk])), 'Recibo 2')


class EstadisticasTest(BaseVistas):
    def test_estadisticas(self):
        for numero, parada, estado, motivo in ((303, 'Orán, Salta', 'aceptada', ''), (304, 'orán, salta ', 'rechazada', 'precio'),
                                               (305, 'Cafayate, Salta', 'rechazada', 'Precio'), (306, 'Cafayate, Salta', None, '')):
            self.client.post(reverse('cotizador:nueva'), self.post_datos(numero=numero, paradas=parada, nuevo_cliente=f'Cliente {numero}'))
            if estado:
                cot = Cotizacion.objects.get(numero=numero)
                self.client.post(reverse('cotizador:cambiar_estado', args=[cot.pk]), {'estado': estado, 'motivo': motivo})
        from . import estadisticas
        e = estadisticas.calcular(date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual((e['resumen']['total'], e['resumen']['aceptadas'], e['resumen']['pendientes']), (4, 1, 1))
        self.assertEqual(e['resumen']['tasa_aceptacion'], Decimal('33.3'))
        self.assertEqual(e['resumen']['vendido'], Decimal('1700000'))
        self.assertEqual(e['motivos'][0]['motivo'], 'Precio')
        self.assertEqual(e['motivos'][0]['cantidad'], 2)
        oran = next(d for d in e['destinos'] if d['destino'] == 'Orán, Salta')
        self.assertEqual((oran['pedidos'], oran['aceptados']), (2, 1))
        self.assertEqual(e['vehiculos'][0], {'vehiculo': 'Piso elevado', 'cantidad': 1, 'barra': 100})
        r = self.client.get(reverse('cotizador:estadisticas') + '?desde=2026-01-01&hasta=2026-12-31')
        self.assertContains(r, 'Orán, Salta')
        self.assertContains(self.client.get(reverse('cotizador:estadisticas')), 'Estadísticas')


def diagrama_de_prueba():
    """Un diagrama chico con el mismo formato que el real (sin datos reales)."""
    import openpyxl
    from openpyxl.comments import Comment
    from openpyxl.styles import PatternFill
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for mes, dias, fila_fechas in ((10, 31, 2), (11, 30, 1)):
        ws = wb.create_sheet(f'{mes}-2026')
        for d in range(1, dias + 1):
            ws.cell(row=fila_fechas, column=d + 1, value=datetime(2026, mes, d))
        base = fila_fechas + 1
        for i, unidad in enumerate([61, '30 - TRANSIT', 15]):
            ws.cell(row=base + i * 3, column=1, value=unidad)
            ws.merge_cells(start_row=base + i * 3, start_column=1, end_row=base + i * 3 + 2, end_column=1)
        ws.cell(row=base + 9, column=1, value='REFERENCIAS')
        if mes == 10:
            ws['E3'] = 'TAN'                                # 61 con salida de TAN el 4/10 (disponible)
            ws['E3'].fill = PatternFill('solid', fgColor='FFE68EE6')
            ws['H3'] = 'MAT'                                # 61 ocupada del 7 al 9/10 (celda combinada)
            ws.merge_cells('H3:J3')
            ws['C4'] = 'LIBRE'                              # "LIBRE" cuenta como libre
            ws['E6'] = 'MANSFIELD'
            ws['E6'].fill = PatternFill('solid', fgColor='FF8E7CC3')
            ws['E6'].comment = Comment('comentario que no se tiene que perder', 'x')
    salida = io.BytesIO()
    wb.save(salida)
    return salida.getvalue()


class DiagramaTest(TestCase):
    def test_disponibilidad(self):
        from . import diagrama as dg
        d = dg.Diagrama(diagrama_de_prueba())
        disp = d.disponibilidad(['61', '30'], date(2026, 10, 2), date(2026, 10, 9))
        self.assertEqual(disp['61'][date(2026, 10, 2)], '')
        self.assertEqual(disp['61'][date(2026, 10, 4)], 'TAN')
        self.assertEqual(disp['61'][date(2026, 10, 8)], 'MAT')      # dentro de la combinación
        self.assertEqual(disp['30'][date(2026, 10, 4)], 'MANSFIELD')
        self.assertEqual(d.libres(['61', '30', '15'], date(2026, 10, 1), date(2026, 10, 3)), ['61', '30', '15'])
        # TAN no quita disponibilidad
        self.assertEqual(d.libres(['61', '30', '15'], date(2026, 10, 4), date(2026, 10, 4)), ['61', '15'])
        self.assertEqual(dg.estado(disp['61'][date(2026, 10, 4)]), 'tan')
        self.assertEqual(dg.estado(disp['61'][date(2026, 10, 8)]), 'ocupada')
        # Colores como en la planilla
        colores = d.colores(['61', '30'], date(2026, 10, 4), date(2026, 10, 4))
        self.assertEqual(colores['61'][date(2026, 10, 4)], '#E68EE6')
        self.assertEqual(colores['30'][date(2026, 10, 4)], '#8E7CC3')
        # Mes sin hoja: no se puede saber
        self.assertIsNone(d.disponibilidad(['61'], date(2026, 12, 1), date(2026, 12, 1))['61'][date(2026, 12, 1)])

    def test_anotar_varios_dias_y_cruzando_de_mes(self):
        from . import diagrama as dg
        original = diagrama_de_prueba()
        nuevo = dg.anotar(original, '30', date(2026, 10, 30), date(2026, 11, 2),
                          ['CLIENTE X', 'SALTA - TUCUMAN - SALTA', 'COT 400'])
        d = dg.Diagrama(nuevo)
        disp = d.disponibilidad(['30'], date(2026, 10, 30), date(2026, 11, 2))['30']
        self.assertTrue(all(t == 'CLIENTE X / SALTA - TUCUMAN - SALTA / COT 400' for t in disp.values()))
        octubre = d.libro['10-2026']
        self.assertIn('AE6:AF6', [str(r) for r in octubre.merged_cells.ranges])
        self.assertIn('B5:C5', [str(r) for r in d.libro['11-2026'].merged_cells.ranges])
        # El resto del archivo queda igual (incluido el comentario)
        self.assertEqual(octubre['E6'].comment.text, 'comentario que no se tiene que perder')
        a, b = zipfile.ZipFile(io.BytesIO(original)), zipfile.ZipFile(io.BytesIO(nuevo))
        cambiados = {n for n in a.namelist() if a.read(n) != b.read(n)}
        self.assertEqual(cambiados, {'xl/worksheets/sheet1.xml', 'xl/worksheets/sheet2.xml'})

    def test_no_pisa_lo_que_ya_hay(self):
        from . import diagrama as dg
        with self.assertRaisesRegex(dg.ErrorDiagrama, 'no está libre'):
            dg.anotar(diagrama_de_prueba(), '61', date(2026, 10, 6), date(2026, 10, 7), ['X'])
        with self.assertRaisesRegex(dg.ErrorDiagrama, 'no está libre'):
            dg.anotar(diagrama_de_prueba(), '61', date(2026, 10, 9), date(2026, 10, 9), ['X'])
        with self.assertRaisesRegex(dg.ErrorDiagrama, 'no está libre'):
            dg.anotar(diagrama_de_prueba(), '30', date(2026, 10, 4), date(2026, 10, 4), ['X'])

    def test_al_reservar_reemplaza_el_tan(self):
        from . import diagrama as dg
        nuevo = dg.anotar(diagrama_de_prueba(), '61', date(2026, 10, 3), date(2026, 10, 5),
                          ['CLIENTE TAN', 'SALTA - CACHI - SALTA', 'COT 500'])
        d = dg.Diagrama(nuevo)
        disp = d.disponibilidad(['61'], date(2026, 10, 3), date(2026, 10, 5))['61']
        self.assertTrue(all(t == 'CLIENTE TAN / SALTA - CACHI - SALTA / COT 500' for t in disp.values()))
        octubre = d.libro['10-2026']
        self.assertIsNone(octubre['E3'].value)                 # el TAN se borró
        self.assertIn('D3:F3', [str(r) for r in octubre.merged_cells.ranges])
        # La reserva no queda con el color rosa del TAN
        self.assertIsNone(d.colores(['61'], date(2026, 10, 3), date(2026, 10, 3))['61'][date(2026, 10, 3)])


class DiagramaVistasTest(BaseVistas):
    def setUp(self):
        super().setUp()
        import tempfile
        archivo = tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False)
        archivo.write(diagrama_de_prueba())
        archivo.close()
        self.archivo = archivo.name
        self.entorno = mock.patch.dict('os.environ', {'DIAGRAMA_LOCAL': self.archivo})
        self.entorno.start()
        p = Parametros.actuales()
        p.unidades_turismo = '61, 30, 15'
        p.save()

    def tearDown(self):
        self.entorno.stop()
        import os
        os.remove(self.archivo)

    def test_disponibilidad_y_anotar_venta(self):
        r = self.client.get(reverse('cotizador:disponibilidad') + '?desde=2026-10-04&hasta=2026-10-04')
        unidades = {u['unidad']: u for u in r.json()['unidades']}
        self.assertEqual({u: x['libre'] for u, x in unidades.items()}, {'61': True, '30': False, '15': True})
        self.assertTrue(unidades['61']['tan'])
        self.assertEqual(unidades['61']['aviso'], 'Hay salida de TAN el 04/10')
        r = self.client.get(reverse('cotizador:unidades') + '?desde=2026-10-03&hasta=2026-10-05')
        self.assertContains(r, 'background: #8E7CC3')   # color de la planilla
        self.assertContains(r, 'dia tan')

        datos = self.post_datos(salida='2026-10-20T07:00', regreso='2026-10-21T20:00', dias='2', noches='1')
        self.client.post(reverse('cotizador:nueva'), datos)
        cot = Cotizacion.objects.get()
        # Pendiente: no se ofrece asignar
        self.assertNotContains(self.client.get(reverse('cotizador:detalle', args=[cot.pk])), 'elegir unidades')
        r = self.client.post(reverse('cotizador:anotar_diagrama', args=[cot.pk]), {'unidades': ['61']})
        self.assertEqual(r.status_code, 404)

        self.client.post(reverse('cotizador:cambiar_estado', args=[cot.pk]), {'estado': 'aceptada'})
        r = self.client.get(reverse('cotizador:detalle', args=[cot.pk]))
        self.assertContains(r, 'elegir unidades')
        self.assertContains(r, 'Todavía no')
        self.assertContains(r, 'MAURICIO VIVAS')

        self.client.post(reverse('cotizador:anotar_diagrama', args=[cot.pk]), {'unidades': ['61']})
        self.assertEqual(list(cot.asignaciones.values_list('unidad', flat=True)), ['61'])
        from . import diagrama as dg
        with open(self.archivo, 'rb') as f:
            disp = dg.Diagrama(f.read()).disponibilidad(['61'], date(2026, 10, 20), date(2026, 10, 20))
        self.assertEqual(disp['61'][date(2026, 10, 20)], 'MAURICIO VIVAS / SALTA - ORÁN - SALTA / COT 303 · 2 DÍAS - 1 NOCHES')
        self.assertContains(self.client.get(reverse('cotizador:detalle', args=[cot.pk])), 'anotada en el diagrama')
        self.assertContains(self.client.get(reverse('cotizador:ventas')), '>61<')
        r = self.client.get(reverse('cotizador:unidades') + '?desde=2026-10-19&hasta=2026-10-22')
        self.assertContains(r, 'MAURICIO VIVAS')

        # Volver a pendiente avisa que hay que borrarlo a mano del Excel
        r = self.client.post(reverse('cotizador:cambiar_estado', args=[cot.pk]), {'estado': 'pendiente'}, follow=True)
        self.assertContains(r, 'borrar a mano del diagrama la unidad 61')
        self.assertFalse(cot.asignaciones.exists())

    def test_sin_conexion(self):
        with mock.patch.dict('os.environ', {'DIAGRAMA_LOCAL': '', 'GOOGLE_SERVICE_ACCOUNT_JSON': ''}):
            self.assertContains(self.client.get(reverse('cotizador:unidades')), 'Conectar el diagrama de Drive')
            r = self.client.get(reverse('cotizador:disponibilidad') + '?desde=2026-10-04')
            self.assertEqual(r.json()['conectado'], False)


class AnulacionTest(BaseVistas):
    def venta_con_pago(self, pago='800000'):
        self.client.post(reverse('cotizador:nueva'), self.post_datos())
        cot = Cotizacion.objects.get()
        self.client.post(reverse('cotizador:cambiar_estado', args=[cot.pk]), {'estado': 'aceptada'})
        if pago:
            self.client.post(reverse('cotizador:movimiento_nuevo', args=[cot.pk]),
                             {'fecha': '2026-10-25', 'tipo': 'pago', 'concepto': 'Seña', 'importe': pago, 'medio': 'efectivo'})
        return cot

    def test_anular_cotizacion_pendiente(self):
        self.client.post(reverse('cotizador:nueva'), self.post_datos())
        cot = Cotizacion.objects.get()
        # Sin motivo no se anula
        self.client.post(reverse('cotizador:anular', args=[cot.pk]), {'motivo': ''})
        cot.refresh_from_db()
        self.assertEqual(cot.estado, Cotizacion.PENDIENTE)
        self.client.post(reverse('cotizador:anular', args=[cot.pk]), {'motivo': 'Se cargó dos veces'})
        cot.refresh_from_db()
        self.assertEqual((cot.estado, cot.motivo_anulacion), (Cotizacion.ANULADA, 'Se cargó dos veces'))
        self.assertContains(self.client.get(reverse('cotizador:detalle', args=[cot.pk])), 'ANULADA')
        self.assertContains(self.client.get(reverse('cotizador:lista') + '?estado=anulada'), 'Mauricio Vivas')
        # Una anulada no vuelve a cambiar de estado por los botones comunes
        self.client.post(reverse('cotizador:cambiar_estado', args=[cot.pk]), {'estado': 'aceptada'})
        cot.refresh_from_db()
        self.assertEqual(cot.estado, Cotizacion.ANULADA)

    def test_anular_venta_reteniendo_la_sena(self):
        cot = self.venta_con_pago()
        self.client.post(reverse('cotizador:anular', args=[cot.pk]), {'motivo': 'Canceló el viaje', 'pagado': 'retener'})
        cot.refresh_from_db()
        self.assertEqual(cot.estado, Cotizacion.ANULADA)
        self.assertEqual(cot.estado_antes_de_anular, Cotizacion.ACEPTADA)
        self.assertEqual(cot.saldo(), 0)
        self.assertTrue(cot.movimientos.get(automatico=True).anulado)
        retenida = cot.movimientos.get(concepto__startswith='Seña retenida')
        self.assertEqual(retenida.importe, Decimal('800000'))
        # Sale de "Ventas y saldos", queda el historial en el detalle y en la cuenta del cliente
        self.assertNotContains(self.client.get(reverse('cotizador:ventas') + '?filtro=todas'), 'Mauricio Vivas')
        r = self.client.get(reverse('cotizador:detalle', args=[cot.pk]))
        self.assertContains(r, 'Seña retenida')
        self.assertNotContains(r, 'Cargar un pago')
        self.assertContains(self.client.get(reverse('cotizador:cliente', args=[cot.cliente_id])), 'Seña retenida')
        # No se puede eliminar
        self.client.post(reverse('cotizador:eliminar', args=[cot.pk]))
        self.assertTrue(Cotizacion.objects.filter(pk=cot.pk).exists())

    def test_anular_venta_devolviendo(self):
        cot = self.venta_con_pago()
        self.client.post(reverse('cotizador:anular', args=[cot.pk]),
                         {'motivo': 'Canceló con tiempo', 'pagado': 'devolver', 'medio': 'transferencia'})
        devolucion = cot.movimientos.get(tipo=Movimiento.DEVOLUCION)
        self.assertEqual((devolucion.importe, devolucion.medio), (Decimal('800000'), 'transferencia'))
        self.assertEqual(cot.saldo(), 0)

    def test_anular_pago_y_recibo(self):
        cot = self.venta_con_pago()
        pago = cot.movimientos.get(tipo=Movimiento.PAGO)
        saldo_antes = cot.saldo()
        self.client.post(reverse('cotizador:movimiento_anular', args=[pago.pk]), {'motivo': 'Transferencia rechazada'})
        pago.refresh_from_db()
        self.assertTrue(pago.anulado)
        self.assertEqual(pago.numero_recibo, 1)              # el número no se pierde
        self.assertEqual(cot.saldo(), saldo_antes + Decimal('800000'))
        xml = zipfile.ZipFile(io.BytesIO(self.client.get(reverse('cotizador:recibo', args=[pago.pk])).content)).read(
            'word/document.xml').decode()
        self.assertIn('ANULADO', xml)
        self.assertIn('Transferencia rechazada', xml)
        self.assertContains(self.client.get(reverse('cotizador:detalle', args=[cot.pk])), 'ANULADO')
        # El siguiente pago sigue la numeración
        self.client.post(reverse('cotizador:movimiento_nuevo', args=[cot.pk]),
                         {'fecha': '2026-10-26', 'tipo': 'pago', 'concepto': 'Seña', 'importe': '800000', 'medio': 'transferencia'})
        self.assertEqual(cot.movimientos.filter(tipo=Movimiento.PAGO).order_by('-numero_recibo').first().numero_recibo, 2)
        # Excel sin el anulado
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(self.client.get(reverse('cotizador:cuentas_excel')).content))
        self.assertEqual(wb['Resumen por cliente']['F2'].value, 800000)


class AnulacionDiagramaTest(DiagramaVistasTest):
    def test_quitar_del_diagrama_y_anular(self):
        datos = self.post_datos(salida='2026-10-20T07:00', regreso='2026-10-21T20:00', dias='2', noches='1')
        self.client.post(reverse('cotizador:nueva'), datos)
        cot = Cotizacion.objects.get()
        self.client.post(reverse('cotizador:cambiar_estado', args=[cot.pk]), {'estado': 'aceptada'})
        self.client.post(reverse('cotizador:anotar_diagrama', args=[cot.pk]), {'unidades': ['61']})
        asignacion = cot.asignaciones.get()
        from . import diagrama as dg

        def texto_dia():
            with open(self.archivo, 'rb') as f:
                return dg.Diagrama(f.read()).disponibilidad(['61'], date(2026, 10, 20), date(2026, 10, 20))['61'][date(2026, 10, 20)]

        self.assertTrue(texto_dia().startswith('MAURICIO VIVAS'))
        self.client.post(reverse('cotizador:quitar_unidad', args=[asignacion.pk]))
        self.assertEqual(texto_dia(), '')
        self.assertFalse(cot.asignaciones.exists())

        # Se vuelve a anotar y se anula la venta quitando del diagrama
        self.client.post(reverse('cotizador:anotar_diagrama', args=[cot.pk]), {'unidades': ['61']})
        self.client.post(reverse('cotizador:anular', args=[cot.pk]), {'motivo': 'Cancelado', 'quitar_diagrama': 'on'})
        cot.refresh_from_db()
        self.assertEqual(cot.estado, Cotizacion.ANULADA)
        self.assertEqual(texto_dia(), '')

    def test_no_quita_si_la_cambiaron_a_mano(self):
        from . import diagrama as dg
        with open(self.archivo, 'rb') as f:
            contenido = dg.anotar(f.read(), '61', date(2026, 10, 20), date(2026, 10, 20), ['OTRO CLIENTE'])
        with self.assertRaisesRegex(dg.ErrorDiagrama, 'Borrala a mano'):
            dg.quitar(contenido, '61', date(2026, 10, 20), date(2026, 10, 20), 'Mauricio Vivas')
