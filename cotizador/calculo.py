"""Cálculo del costo de un viaje, igual que la planilla "COTIZACIONES 2026".

Cada ítem se calcula por vehículo y después se multiplica por la cantidad de vehículos.
"""
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

CERO = Decimal('0')
CIEN = Decimal('100')


def redondear(valor, decimales='0.01'):
    return Decimal(valor).quantize(Decimal(decimales), rounding=ROUND_HALF_UP)


def _txt(valor):
    """Número para los textos de ayuda: 2500.00 -> 2.500 ; 10.50 -> 10,5"""
    valor = Decimal(valor).normalize()
    entero, _, dec = f'{valor:f}'.partition('.')
    entero = f'{int(entero):,}'.replace(',', '.')
    return f'{entero},{dec}' if dec else entero


def _dec(valor):
    if valor in (None, ''):
        return CERO
    return Decimal(str(valor))


def proyeccion(p, datos):
    """Si el viaje sale más adelante, cuánto subirían los costos hasta esa fecha por inflación.
    Devuelve None si no corresponde proyectar."""
    fecha, salida = datos.get('fecha'), datos.get('salida')
    tasa = _dec(datos.get('inflacion_mensual'))
    if not datos.get('proyectar_inflacion') or not fecha or not salida or tasa <= 0:
        return None
    if isinstance(salida, datetime):
        salida = timezone.localtime(salida).date() if timezone.is_aware(salida) else salida.date()
    dias = (salida - fecha).days
    if dias <= p.proyectar_desde_dias:
        return None
    meses = redondear(Decimal(dias) / 30, '0.1')
    factor = (1 + tasa / CIEN) ** meses
    return {'dias': dias, 'meses': meses, 'tasa': tasa, 'factor': factor,
            'porcentaje': redondear((factor - 1) * CIEN, '0.1')}


def calcular(p, datos):
    """p: Parametros. datos: dict con km_servicio, km_vacios, dias, noches, choferes,
    viaticos_por_chofer, habitaciones, cantidad_vehiculos, vehiculo (TipoVehiculo),
    incluye_hotel, incluye_estacionamiento, incluye_lavadero, peaje, otros_gastos, tarifa_neta."""
    km_totales = _dec(datos.get('km_servicio')) + _dec(datos.get('km_vacios'))
    dias = _dec(datos.get('dias'))
    noches = _dec(datos.get('noches'))
    choferes = _dec(datos.get('choferes'))
    cantidad = max(_dec(datos.get('cantidad_vehiculos')), Decimal(1))
    vehiculo = datos.get('vehiculo')
    rendimiento = vehiculo.rendimiento_km_litro if vehiculo and vehiculo.rendimiento_km_litro else Decimal(3)
    capacidad = (vehiculo.capacidad if vehiculo else 0) * cantidad

    sueldo_dia = p.valor_dia_turismo * p.factor_sueldo_conductor
    divisor = Decimal(p.divisor_prorrateo or 1)
    flota = Decimal(p.vehiculos_flota or 1)
    vida_util = Decimal(p.vida_util_meses or 1)

    items = [
        ('Cargas sociales', sueldo_dia * p.porcentaje_cargas_sociales / CIEN * dias * choferes,
         f'{_txt(p.porcentaje_cargas_sociales)}% del sueldo × {_txt(dias)} días × {_txt(choferes)} chofer/es'),
        ('Sueldo de conductor', sueldo_dia * dias * choferes + p.no_remunerativo_mensual / 30 * dias * choferes,
         f'(sueldo diario + no remunerativo) × {_txt(dias)} días × {_txt(choferes)} chofer/es'),
        ('Gastos de administración', p.gastos_admin_mensuales / divisor, f'gastos mensuales ÷ {_txt(divisor)}'),
        ('Hotel', p.hotel_por_noche * noches * _dec(datos.get('habitaciones')) if datos.get('incluye_hotel') else CERO,
         f'{_txt(noches)} noches × {datos.get("habitaciones") or 0} habitación/es' if datos.get('incluye_hotel') else 'no incluido'),
        ('Viáticos', p.viatico_por_unidad * _dec(datos.get('viaticos_por_chofer')) * choferes,
         f'{datos.get("viaticos_por_chofer") or 0} viáticos × {_txt(choferes)} chofer/es'),
        ('Peajes', _dec(datos.get('peaje')), ''),
        ('Combustible', p.precio_combustible * km_totales / rendimiento,
         f'{_txt(km_totales)} km ÷ {_txt(rendimiento)} km/l × ${_txt(p.precio_combustible)}'),
        ('Depreciación', (p.valor_adquisicion - p.valor_residual) / vida_util / divisor,
         f'(valor - residual) ÷ {_txt(vida_util)} meses ÷ {_txt(divisor)}'),
        ('Estacionamiento', p.estacionamiento if datos.get('incluye_estacionamiento') else CERO,
         '' if datos.get('incluye_estacionamiento') else 'no incluido'),
        ('Lavadero', p.lavadero if datos.get('incluye_lavadero') else CERO,
         '' if datos.get('incluye_lavadero') else 'no incluido'),
        ('Seguro obligatorio', p.seguro_mensual_flota / flota / 30 * dias, f'seguro por vehículo ÷ 30 × {_txt(dias)} días'),
        ('Insumos de limpieza', p.insumos_limpieza, ''),
        ('Otros gastos', _dec(datos.get('otros_gastos')), ''),
    ]
    items = [{'nombre': n, 'importe': redondear(v * cantidad), 'detalle': d} for n, v, d in items]
    costo_hoy = sum((i['importe'] for i in items), CERO)
    inflacion = proyeccion(p, datos)
    if inflacion:
        inflacion['costo_hoy'] = costo_hoy
        items.append({'nombre': 'Ajuste por inflación', 'importe': redondear(costo_hoy * (inflacion['factor'] - 1)),
                      'detalle': f"{_txt(inflacion['meses'])} meses al {_txt(inflacion['tasa'])}% mensual "
                                 f"= +{_txt(inflacion['porcentaje'])}% hasta la salida",
                      'inflacion': True})
        del inflacion['factor']
    costo = sum((i['importe'] for i in items), CERO)
    costo_km = costo / km_totales if km_totales else CERO

    def fila(nombre, total, valor_km=None):
        total = redondear(total)
        ganancia = total - costo
        iva = redondear(total * p.porcentaje_iva / CIEN)
        return {
            'nombre': nombre,
            'valor_km': redondear(valor_km if valor_km is not None else (total / km_totales if km_totales else CERO)),
            'total': total,
            'ganancia': ganancia,
            'perdida': ganancia < 0,
            'rentabilidad': redondear(ganancia / total * CIEN, '0.1') if total else CERO,
            'por_pax': redondear(total / capacidad) if capacidad else CERO,
            'iva': iva,
            'bruto': total + iva,
        }

    filas = [fila('Costo', costo, costo_km)]
    for nombre, margen in (('Margen mínimo', p.margen_minimo), ('Margen intermedio', p.margen_intermedio),
                           ('Valor de mercado', p.margen_mercado), ('Margen óptimo', p.margen_optimo)):
        valor_km = redondear(costo_km * (1 + margen / CIEN), '1')
        f = fila(f'{nombre} ({_txt(margen)}%)', valor_km * km_totales, valor_km)
        f['sugerido'] = redondear(f['total'] / 10000, '1') * 10000 if f['total'] else CERO
        filas.append(f)
    filas.append(fila(f'Referencia ${_txt(p.precio_referencia_km)} por km', p.precio_referencia_km * km_totales,
                      p.precio_referencia_km))

    tarifa = _dec(datos.get('tarifa_neta'))
    final = fila('Tarifa final', tarifa) if tarifa else None

    return {
        'km_totales': km_totales,
        'capacidad': capacidad,
        'items': items,
        'costo': redondear(costo),
        'costo_km': redondear(costo_km),
        'filas': filas,
        'final': final,
        'inflacion': inflacion,
    }


def para_guardar(resultado, p):
    """Versión del cálculo que se guarda en la cotización (texto, para JSON)."""
    def limpio(valor):
        if isinstance(valor, Decimal):
            return str(valor)
        if isinstance(valor, dict):
            return {k: limpio(v) for k, v in valor.items()}
        if isinstance(valor, list):
            return [limpio(v) for v in valor]
        return valor

    parametros = {f.verbose_name: str(getattr(p, f.name)) for f in p._meta.concrete_fields
                  if f.get_internal_type() in ('DecimalField', 'PositiveIntegerField')}
    return limpio({**resultado, 'parametros': parametros})
