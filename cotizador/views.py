from datetime import timedelta
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from . import calculo, estadisticas as estadisticas_calculo, excel, recibo, rutas, word
from .forms import (ClienteForm, CotizacionForm, LineaVehiculoForm, MovimientoForm, ParametrosForm,
                    TipoVehiculoForm, lineas_validas)
from .models import Cliente, Cotizacion, LineaVehiculo, Movimiento, Parametros, TipoVehiculo


@login_required
def lista(request):
    q = request.GET.get('q', '').strip()
    estado = request.GET.get('estado', '')
    cotizaciones = Cotizacion.objects.select_related('cliente').prefetch_related('lineas__vehiculo')
    if q:
        filtro = Q(cliente__nombre__icontains=q) | Q(itinerario__icontains=q) | Q(paradas__icontains=q)
        if q.isdigit():
            filtro |= Q(numero=int(q))
        cotizaciones = cotizaciones.filter(filtro)
    if estado in dict(Cotizacion.ESTADOS):
        cotizaciones = cotizaciones.filter(estado=estado)
    conteo = dict(Cotizacion.objects.values_list('estado').annotate(n=Count('id')))
    return render(request, 'cotizador/lista.html', {
        'cotizaciones': cotizaciones[:300], 'q': q, 'estado': estado,
        'estados': [(k, v, conteo.get(k, 0)) for k, v in Cotizacion.ESTADOS]})


def _formset_lineas(data=None, instance=None, inicial=None):
    """Formulario de vehículos de la cotización. `inicial`: lista de líneas para una cotización nueva."""
    extra = max(len(inicial) - 1, 0) if inicial else 0
    clase = forms.inlineformset_factory(Cotizacion, LineaVehiculo, form=LineaVehiculoForm, extra=extra,
                                        min_num=1, validate_min=True, can_delete=True)
    return clase(data, instance=instance or Cotizacion(), prefix='lineas', initial=inicial)


@transaction.atomic
def _guardar(request, form, formset, p):
    cot = form.save(commit=False)
    resultado = calculo.calcular(p, {**form.cleaned_data, 'lineas': lineas_validas(formset)})
    cot.costo_total = resultado['costo']
    cot.detalle = calculo.para_guardar(resultado, p)
    if not cot.creado_por_id:
        cot.creado_por = request.user
    cot.save()
    formset.instance = cot
    lineas = formset.save(commit=False)
    for linea in formset.deleted_objects:
        linea.delete()
    for orden, linea in enumerate(lineas):
        linea.cotizacion = cot
        linea.orden = orden
        linea.save()
    cot.actualizar_cargo_automatico()
    return cot


@login_required
def nueva(request):
    p = Parametros.actuales()
    if request.method == 'POST':
        form = CotizacionForm(request.POST)
        formset = _formset_lineas(request.POST)
        if form.is_valid() and formset.is_valid():
            cot = _guardar(request, form, formset, p)
            messages.success(request, f'Cotización {cot.numero} guardada.')
            return redirect('cotizador:detalle', cot.pk)
    else:
        inicial = {
            'numero': Cotizacion.proximo_numero(), 'fecha': timezone.localdate(),
            'origen': p.origen_habitual, 'incluye': p.incluye, 'no_incluye': p.no_incluye,
            'cliente': request.GET.get('cliente'),
            'inflacion_mensual': p.inflacion_mensual,
        }
        base = Cotizacion.objects.filter(pk=request.GET.get('copiar')).first() if request.GET.get('copiar') else None
        if base:
            copia = {f: getattr(base, f) for f in CotizacionForm.Meta.fields if f not in ('numero', 'fecha')}
            copia['cliente'] = base.cliente_id
            copia['salida'] = timezone.localtime(base.salida)
            copia['regreso'] = timezone.localtime(base.regreso)
            inicial.update(copia)
            lineas = [{'vehiculo': l.vehiculo_id, 'cantidad': l.cantidad, 'choferes': l.choferes,
                       'descripcion': l.descripcion} for l in base.lineas.all()]
        else:
            vehiculo = TipoVehiculo.objects.filter(activo=True).first()
            lineas = [{'vehiculo': vehiculo.pk, 'cantidad': 1, 'choferes': 1,
                       'descripcion': vehiculo.descripcion_word}] if vehiculo else None
        form = CotizacionForm(initial=inicial)
        formset = _formset_lineas(inicial=lineas)
    return render(request, 'cotizador/form.html', {'form': form, 'formset': formset, 'p': p, 'vehiculos': _vehiculos_js()})


@login_required
def editar(request, pk):
    cot = get_object_or_404(Cotizacion, pk=pk)
    p = Parametros.actuales()
    if request.method == 'POST':
        form = CotizacionForm(request.POST, instance=cot)
        formset = _formset_lineas(request.POST, instance=cot)
        if form.is_valid() and formset.is_valid():
            _guardar(request, form, formset, p)
            messages.success(request, f'Cotización {cot.numero} actualizada con los parámetros de hoy.')
            return redirect('cotizador:detalle', cot.pk)
    else:
        form = CotizacionForm(instance=cot, initial={
            'salida': timezone.localtime(cot.salida), 'regreso': timezone.localtime(cot.regreso)})
        formset = _formset_lineas(instance=cot)
    return render(request, 'cotizador/form.html', {
        'form': form, 'formset': formset, 'p': p, 'cot': cot, 'vehiculos': _vehiculos_js()})


def _vehiculos_js():
    return {v.pk: {'descripcion': v.descripcion_word, 'capacidad': v.capacidad}
            for v in TipoVehiculo.objects.filter(activo=True)}


def _con_saldo_acumulado(movimientos):
    """Agrega a cada movimiento el saldo que queda después de él (como un resumen de cuenta)."""
    saldo = Decimal(0)
    filas = []
    for m in movimientos:
        saldo += m.importe if m.tipo == Movimiento.CARGO else -m.importe
        filas.append((m, saldo))
    return filas


@login_required
def detalle(request, pk):
    cot = get_object_or_404(Cotizacion.objects.select_related('creado_por', 'cliente').prefetch_related('lineas__vehiculo'), pk=pk)
    contexto = {'cot': cot, 'r': cot.detalle}
    if cot.estado == Cotizacion.ACEPTADA:
        pagado = cot.total_pagos()
        saldo = cot.saldo()
        contexto.update({
            'movimientos': _con_saldo_acumulado(cot.movimientos.all()),
            'pagado': pagado, 'saldo': saldo, 'cargos': cot.total_cargos(),
            'sena': cot.sena_requerida(), 'falta_sena': max(cot.sena_requerida() - pagado, 0),
            'pago_urgente': saldo > 0 and cot.salida - timezone.now() < timedelta(hours=72),
            'mov_form': MovimientoForm(initial={'fecha': timezone.localdate(), 'tipo': Movimiento.PAGO}),
        })
    return render(request, 'cotizador/detalle.html', contexto)


@login_required
@require_POST
@transaction.atomic
def cambiar_estado(request, pk):
    cot = get_object_or_404(Cotizacion, pk=pk)
    nuevo = request.POST.get('estado')
    if nuevo not in dict(Cotizacion.ESTADOS) or nuevo == cot.estado:
        return redirect('cotizador:detalle', pk)
    if cot.estado == Cotizacion.ACEPTADA:
        if cot.movimientos.filter(automatico=False).exists():
            messages.error(request, 'Esta venta ya tiene pagos o cargos cargados. Borralos primero de la cuenta corriente.')
            return redirect('cotizador:detalle', pk)
        cot.movimientos.filter(automatico=True).delete()
    cot.estado = nuevo
    cot.fecha_estado = timezone.localdate() if nuevo != Cotizacion.PENDIENTE else None
    cot.motivo_rechazo = request.POST.get('motivo', '').strip()[:200] if nuevo == Cotizacion.RECHAZADA else ''
    cot.save()
    cot.actualizar_cargo_automatico()
    textos = {Cotizacion.ACEPTADA: 'aceptada: ya podés cargar señas y pagos en la cuenta corriente',
              Cotizacion.RECHAZADA: 'marcada como rechazada', Cotizacion.PENDIENTE: 'vuelta a pendiente'}
    messages.success(request, f'Cotización {cot.numero} {textos[nuevo]}.')
    return redirect('cotizador:detalle', pk)


@login_required
@require_POST
def movimiento_nuevo(request, pk):
    cot = get_object_or_404(Cotizacion, pk=pk, estado=Cotizacion.ACEPTADA)
    form = MovimientoForm(request.POST)
    if form.is_valid():
        mov = form.save(commit=False)
        mov.cotizacion = cot
        mov.creado_por = request.user
        if mov.tipo == Movimiento.CARGO:
            mov.medio = ''
        mov.save()
        nombre = 'Pago' if mov.tipo == Movimiento.PAGO else 'Cargo'
        messages.success(request, f'{nombre} de $ {round(mov.importe):,} cargado.'.replace(',', '.'))
    else:
        errores = ' '.join(e for lista_errores in form.errors.values() for e in lista_errores)
        messages.error(request, f'No se cargó el movimiento: {errores}')
    return redirect('cotizador:detalle', pk)


@login_required
def descargar_recibo(request, pk):
    mov = get_object_or_404(Movimiento.objects.select_related('cotizacion__cliente'), pk=pk, tipo=Movimiento.PAGO)
    respuesta = HttpResponse(
        recibo.generar(mov),
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    respuesta['Content-Disposition'] = f'attachment; filename="{recibo.nombre_archivo(mov)}"'
    return respuesta


@login_required
@require_POST
def movimiento_eliminar(request, pk):
    mov = get_object_or_404(Movimiento, pk=pk, automatico=False)
    cot_pk = mov.cotizacion_id
    mov.delete()
    messages.success(request, 'Movimiento eliminado.')
    return redirect('cotizador:detalle', cot_pk)


@login_required
def descargar_word(request, pk):
    cot = get_object_or_404(Cotizacion.objects.select_related('cliente'), pk=pk)
    respuesta = HttpResponse(
        word.generar(cot),
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    respuesta['Content-Disposition'] = f'attachment; filename="{word.nombre_archivo(cot)}"'
    return respuesta


@login_required
@require_POST
def eliminar(request, pk):
    cot = get_object_or_404(Cotizacion, pk=pk)
    if cot.estado == Cotizacion.ACEPTADA:
        messages.error(request, 'Una cotización aceptada no se puede eliminar. Pasala a pendiente o rechazada primero.')
        return redirect('cotizador:detalle', pk)
    numero = cot.numero
    cot.delete()
    messages.success(request, f'Cotización {numero} eliminada.')
    return redirect('cotizador:lista')


@login_required
def ventas(request):
    """Cotizaciones aceptadas con lo cobrado y lo que falta cobrar."""
    filtro = request.GET.get('filtro', 'saldo')
    lista_ventas = []
    aceptadas = Cotizacion.objects.filter(estado=Cotizacion.ACEPTADA).select_related('cliente').prefetch_related('lineas__vehiculo')
    for cot in aceptadas.order_by('salida'):
        saldo = cot.saldo()
        if filtro == 'saldo' and saldo <= 0:
            continue
        lista_ventas.append({'cot': cot, 'cargos': cot.total_cargos(), 'pagado': cot.total_pagos(), 'saldo': saldo})
    total_saldo = sum((v['saldo'] for v in lista_ventas), Decimal(0))
    return render(request, 'cotizador/ventas.html', {
        'ventas': lista_ventas, 'filtro': filtro, 'total_saldo': total_saldo, 'ahora': timezone.now()})


@login_required
def cuentas_excel(request):
    """Todas las cuentas corrientes en Excel (o las de un cliente con ?cliente=id)."""
    cliente_obj = get_object_or_404(Cliente, pk=request.GET['cliente']) if request.GET.get('cliente') else None
    nombre = f'Cuenta_corriente_{cliente_obj.pk}' if cliente_obj else 'Cuentas_corrientes'
    respuesta = HttpResponse(
        excel.generar(cliente_obj),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    respuesta['Content-Disposition'] = f'attachment; filename="{nombre}_{timezone.localdate():%d-%m-%Y}.xlsx"'
    return respuesta


@login_required
def estadisticas(request):
    hoy = timezone.localdate()
    hasta = parse_date(request.GET.get('hasta', '')) or hoy
    desde = parse_date(request.GET.get('desde', '')) or hasta.replace(year=hasta.year - 1, day=1)
    return render(request, 'cotizador/estadisticas.html', {
        'desde': desde, 'hasta': hasta, **estadisticas_calculo.calcular(desde, hasta)})


@login_required
def clientes(request):
    q = request.GET.get('q', '').strip()
    lista_clientes = Cliente.objects.annotate(n_cot=Count('cotizaciones'))
    if q:
        lista_clientes = lista_clientes.filter(
            Q(nombre__icontains=q) | Q(cuit__icontains=q) | Q(contacto__icontains=q)
            | Q(telefono__icontains=q) | Q(localidad__icontains=q))
    return render(request, 'cotizador/clientes.html', {'clientes': lista_clientes[:300], 'q': q})


@login_required
def cliente_form(request, pk=None):
    cliente_obj = get_object_or_404(Cliente, pk=pk) if pk else None
    if request.method == 'POST':
        form = ClienteForm(request.POST, instance=cliente_obj)
        if form.is_valid():
            cliente_obj = form.save()
            messages.success(request, f'Cliente {cliente_obj.nombre} guardado.')
            return redirect('cotizador:cliente', cliente_obj.pk)
    else:
        form = ClienteForm(instance=cliente_obj)
    return render(request, 'cotizador/cliente_form.html', {'form': form, 'cliente': cliente_obj})


@login_required
def cliente(request, pk):
    cliente_obj = get_object_or_404(Cliente, pk=pk)
    movimientos = Movimiento.objects.filter(
        cotizacion__cliente=cliente_obj, cotizacion__estado=Cotizacion.ACEPTADA
    ).select_related('cotizacion').order_by('fecha', 'id')
    filas = _con_saldo_acumulado(movimientos)
    return render(request, 'cotizador/cliente.html', {
        'cliente': cliente_obj, 'cotizaciones': cliente_obj.cotizaciones.prefetch_related('lineas__vehiculo'),
        'movimientos': filas, 'saldo': filas[-1][1] if filas else Decimal(0)})


@login_required
@require_POST
def cliente_eliminar(request, pk):
    cliente_obj = get_object_or_404(Cliente, pk=pk)
    if cliente_obj.cotizaciones.exists():
        messages.error(request, 'No se puede eliminar un cliente que tiene cotizaciones.')
        return redirect('cotizador:cliente', pk)
    cliente_obj.delete()
    messages.success(request, 'Cliente eliminado.')
    return redirect('cotizador:clientes')


@login_required
@require_POST
def calcular(request):
    """Vista previa del cálculo mientras se completa el formulario."""
    form = CotizacionForm(request.POST)
    form.is_valid()
    formset = _formset_lineas(request.POST)
    formset.is_valid()
    resultado = calculo.calcular(Parametros.actuales(), {**form.cleaned_data, 'lineas': lineas_validas(formset)})
    return render(request, 'cotizador/_resultado.html', {'r': resultado, 'usar': True})


@login_required
@require_POST
def buscar_km(request):
    origen = request.POST.get('origen', '').strip()
    paradas = [x.strip() for x in request.POST.get('paradas', '').splitlines() if x.strip()]
    ida_y_vuelta = request.POST.get('ida_y_vuelta') in ('on', 'true', '1')
    try:
        recorrido = rutas.calcular_recorrido(origen, paradas, ida_y_vuelta)
    except rutas.ErrorRuta as e:
        return JsonResponse({'error': str(e)}, status=400)
    nombres = [origen] + paradas + ([origen] if ida_y_vuelta else [])
    return JsonResponse({
        'km': recorrido['km'],
        'tramos': recorrido['tramos'],
        'itinerario': ' – '.join(nombres) + '.',
        'encontrados': [l.nombre for l in recorrido['lugares']],
    })


@login_required
@permission_required('cotizador.change_parametros', raise_exception=True)
def parametros(request):
    p = Parametros.actuales()
    if request.method == 'POST':
        form = ParametrosForm(request.POST, instance=p)
        if form.is_valid():
            p = form.save(commit=False)
            p.actualizado_por = request.user
            p.save()
            messages.success(request, 'Parámetros actualizados. Las cotizaciones nuevas ya usan estos valores.')
            return redirect('cotizador:parametros')
    else:
        form = ParametrosForm(instance=p)
    grupos = [
        ('Personal', ['valor_dia_turismo', 'factor_sueldo_conductor', 'porcentaje_cargas_sociales',
                      'no_remunerativo_mensual', 'viatico_por_unidad', 'hotel_por_noche']),
        ('Vehículo', ['precio_combustible', 'valor_adquisicion', 'valor_residual', 'vida_util_meses',
                      'seguro_mensual_flota', 'vehiculos_flota']),
        ('Gastos por viaje', ['gastos_admin_mensuales', 'divisor_prorrateo', 'estacionamiento', 'lavadero',
                              'insumos_limpieza']),
        ('Márgenes e IVA', ['margen_minimo', 'margen_intermedio', 'margen_mercado', 'margen_optimo',
                            'precio_referencia_km', 'porcentaje_iva']),
        ('Viajes a futuro', ['inflacion_mensual', 'proyectar_desde_dias']),
        ('Word de la cotización', ['origen_habitual', 'porcentaje_sena', 'vigencia_dias', 'incluye', 'no_incluye']),
    ]
    grupos = [(titulo, [form[c] for c in campos]) for titulo, campos in grupos]
    return render(request, 'cotizador/parametros.html', {'form': form, 'grupos': grupos, 'p': p})


@login_required
@permission_required('cotizador.change_tipovehiculo', raise_exception=True)
def vehiculos(request, pk=None):
    vehiculo = get_object_or_404(TipoVehiculo, pk=pk) if pk else None
    if request.method == 'POST':
        form = TipoVehiculoForm(request.POST, instance=vehiculo)
        if form.is_valid():
            form.save()
            messages.success(request, 'Vehículo guardado.')
            return redirect('cotizador:vehiculos')
    else:
        form = TipoVehiculoForm(instance=vehiculo)
    return render(request, 'cotizador/vehiculos.html', {
        'form': form, 'vehiculo': vehiculo, 'vehiculos': TipoVehiculo.objects.all()})
