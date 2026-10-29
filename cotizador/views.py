import logging
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

from . import calculo, diagrama as dg, drive, estadisticas as estadisticas_calculo, excel, recibo, rutas, word
from .forms import (ClienteForm, CotizacionForm, LineaVehiculoForm, MovimientoForm, ParametrosForm,
                    TipoVehiculoForm, lineas_validas)
from .models import AsignacionUnidad, Cliente, Cotizacion, LineaVehiculo, Movimiento, Parametros, TipoVehiculo

logger = logging.getLogger(__name__)


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
            'colaciones_precio': p.precio_colacion,
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
        if not m.anulado:
            saldo += m.importe if m.suma else -m.importe
        filas.append((m, saldo))
    return filas


@login_required
def detalle(request, pk):
    cot = get_object_or_404(Cotizacion.objects.select_related('creado_por', 'cliente').prefetch_related('lineas__vehiculo'), pk=pk)
    contexto = {'cot': cot, 'r': cot.detalle}
    if cot.fue_venta:
        pagado = cot.total_pagos()
        saldo = cot.saldo()
        contexto.update({
            'movimientos': _con_saldo_acumulado(cot.movimientos.all()),
            'pagado': pagado, 'saldo': saldo, 'cargos': cot.total_cargos(),
            'sena': cot.sena_requerida(), 'falta_sena': max(cot.sena_requerida() - pagado, 0),
            'pago_urgente': saldo > 0 and cot.salida - timezone.now() < timedelta(hours=72),
            'mov_form': MovimientoForm(initial={'fecha': timezone.localdate(), 'tipo': Movimiento.PAGO}),
        })
        if cot.estado == Cotizacion.ACEPTADA:
            contexto.update(_diagrama_para_venta(cot))
        else:
            contexto['asignaciones'] = list(cot.asignaciones.all())
    if cot.estado != Cotizacion.ANULADA:
        contexto['pagado_para_anular'] = cot.total_pagos() if cot.estado == Cotizacion.ACEPTADA else 0
        contexto['medios'] = Movimiento.MEDIOS
    return render(request, 'cotizador/detalle.html', contexto)


def _fechas_viaje(cot):
    return timezone.localtime(cot.salida).date(), timezone.localtime(cot.regreso).date()


def renglones_diagrama(cot):
    """Los 3 renglones que se escriben en el diagrama: cliente / recorrido / detalle."""
    ciudades = [cot.origen] + [p for p in cot.paradas.splitlines() if p.strip()]
    if cot.ida_y_vuelta:
        ciudades.append(cot.origen)
    recorrido = ' - '.join(c.split(',')[0].strip().upper() for c in ciudades)
    detalle = f'COT {cot.numero}'
    if cot.noches:
        detalle += f' · {cot.dias} DÍAS - {cot.noches} NOCHES'
    return [cot.cliente.nombre.upper(), recorrido, detalle]


def _resumen_disponibilidad(disponibilidad):
    """Por unidad: si está disponible todo el viaje, si algún día tiene salida de TAN y el detalle."""
    resumen = []
    for u, dias in disponibilidad.items():
        dias_tan = [d for d, t in dias.items() if dg.estado(t) == 'tan']
        resumen.append({
            'unidad': u,
            'libre': all(dg.estado(t) in ('libre', 'tan') for t in dias.values()),
            'tan': bool(dias_tan),
            'aviso': ('Hay salida de TAN el ' + ', '.join(f'{d:%d/%m}' for d in dias_tan)) if dias_tan else '',
            'detalle': ' | '.join(f'{d:%d/%m}: {t or "sin hoja en el diagrama"}' for d, t in dias.items() if t != ''),
        })
    return resumen


def _diagrama_para_venta(cot):
    """Datos para la tarjeta "Diagrama de unidades" de una venta aceptada."""
    datos = {'asignaciones': list(cot.asignaciones.all()), 'diagrama_conectado': drive.configurado(),
             'renglones_diagrama': renglones_diagrama(cot)}
    if datos['asignaciones'] or not datos['diagrama_conectado']:
        return datos
    desde, hasta = _fechas_viaje(cot)
    p = Parametros.actuales()
    try:
        disponibilidad = drive.diagrama_actual(p).disponibilidad(p.lista_unidades(), desde, hasta)
    except (drive.ErrorDrive, dg.ErrorDiagrama) as e:
        datos['error_diagrama'] = str(e)
        return datos
    datos['unidades_diagrama'] = _resumen_disponibilidad(disponibilidad)
    return datos


@login_required
@require_POST
def anotar_diagrama(request, pk):
    cot = get_object_or_404(Cotizacion, pk=pk, estado=Cotizacion.ACEPTADA)
    elegidas = request.POST.getlist('unidades')
    if not elegidas:
        messages.error(request, 'Elegí al menos una unidad para anotar en el diagrama.')
        return redirect('cotizador:detalle', pk)
    p = Parametros.actuales()
    desde, hasta = _fechas_viaje(cot)
    renglones = renglones_diagrama(cot)
    try:
        drive.anotar(p.diagrama_drive_id, [(u, desde, hasta, renglones) for u in elegidas])
    except (drive.ErrorDrive, dg.ErrorDiagrama) as e:
        messages.error(request, f'No se anotó en el diagrama: {e}')
        return redirect('cotizador:detalle', pk)
    for u in elegidas:
        AsignacionUnidad.objects.create(cotizacion=cot, unidad=u, desde=desde, hasta=hasta, anotado_por=request.user)
    que = f'unidades {", ".join(elegidas)} anotadas' if len(elegidas) > 1 else f'unidad {elegidas[0]} anotada'
    messages.success(request, f'Listo: {que} en el diagrama del {desde:%d/%m} al {hasta:%d/%m}.')
    return redirect('cotizador:detalle', pk)


@login_required
def disponibilidad(request):
    """Para el formulario: qué unidades de turismo están libres entre dos fechas."""
    desde = parse_date(request.GET.get('desde', ''))
    hasta = parse_date(request.GET.get('hasta', '')) or desde
    if not desde or not drive.configurado():
        return JsonResponse({'conectado': drive.configurado(), 'unidades': []})
    if hasta < desde or (hasta - desde).days > 60:
        return JsonResponse({'conectado': True, 'error': 'Revisá las fechas del viaje.', 'unidades': []})
    p = Parametros.actuales()
    try:
        disp = drive.diagrama_actual(p).disponibilidad(p.lista_unidades(), desde, hasta)
    except (drive.ErrorDrive, dg.ErrorDiagrama) as e:
        return JsonResponse({'conectado': True, 'error': str(e), 'unidades': []})
    return JsonResponse({'conectado': True, 'unidades': _resumen_disponibilidad(disp)})


def _es_oscuro(color):
    """Para elegir letra blanca o negra sobre el color de la planilla."""
    if not color:
        return False
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.299 * r + 0.587 * g + 0.114 * b < 140


@login_required
def unidades(request):
    """Grilla de las unidades de turismo por día, leída del diagrama."""
    hoy = timezone.localdate()
    desde = parse_date(request.GET.get('desde', '')) or hoy
    hasta = parse_date(request.GET.get('hasta', '')) or desde + timedelta(days=13)
    if hasta < desde or (hasta - desde).days > 45:
        hasta = desde + timedelta(days=13)
    p = Parametros.actuales()
    dias = [desde + timedelta(days=i) for i in range((hasta - desde).days + 1)]
    contexto = {'desde': desde, 'hasta': hasta, 'dias': dias, 'conectado': drive.configurado(),
                'mail_cuenta': drive.mail_cuenta(), 'p': p}
    if contexto['conectado']:
        try:
            diagrama = drive.diagrama_actual(p)
            disp = diagrama.disponibilidad(p.lista_unidades(), desde, hasta)
            colores = diagrama.colores(p.lista_unidades(), desde, hasta)
            contexto['filas'] = [{'unidad': u, 'dias': [{'texto': disp[u][d], 'estado': dg.estado(disp[u][d]),
                                                         'color': colores[u][d], 'oscuro': _es_oscuro(colores[u][d])}
                                                        for d in dias],
                                  'libres': sum(1 for d in dias if dg.estado(disp[u][d]) in ('libre', 'tan'))}
                                 for u in p.lista_unidades()]
            contexto['libres_por_dia'] = [sum(1 for u in p.lista_unidades() if dg.estado(disp[u][d]) in ('libre', 'tan'))
                                          for d in dias]
        except (drive.ErrorDrive, dg.ErrorDiagrama) as e:
            contexto['error'] = str(e)
    return render(request, 'cotizador/unidades.html', contexto)


@login_required
@require_POST
@transaction.atomic
def cambiar_estado(request, pk):
    cot = get_object_or_404(Cotizacion, pk=pk)
    nuevo = request.POST.get('estado')
    if nuevo not in dict(Cotizacion.ESTADOS) or nuevo == cot.estado or Cotizacion.ANULADA in (nuevo, cot.estado):
        return redirect('cotizador:detalle', pk)
    if cot.estado == Cotizacion.ACEPTADA:
        if cot.movimientos.filter(automatico=False, anulado=False).exists():
            messages.error(request, 'Esta venta ya tiene pagos o cargos cargados. Si el viaje se cancela, usá "Anular venta".')
            return redirect('cotizador:detalle', pk)
        cot.movimientos.filter(automatico=True).delete()
    asignadas = [a.unidad for a in cot.asignaciones.all()]
    if asignadas and nuevo != Cotizacion.ACEPTADA:
        cot.asignaciones.all().delete()
        messages.warning(request, f'Acordate de borrar a mano del diagrama la unidad {", ".join(asignadas)} '
                                  f'(la app no borra lo que ya está escrito en el Excel).')
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
        nombre = {Movimiento.PAGO: 'Pago', Movimiento.CARGO: 'Cargo', Movimiento.DEVOLUCION: 'Devolución'}[mov.tipo]
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
def movimiento_anular(request, pk):
    """Anula un pago o cargo: queda en la cuenta (tachado, con su recibo marcado ANULADO) pero no suma ni resta."""
    mov = get_object_or_404(Movimiento, pk=pk, automatico=False, anulado=False,
                            cotizacion__estado=Cotizacion.ACEPTADA)
    motivo = request.POST.get('motivo', '').strip()
    if not motivo:
        messages.error(request, 'Escribí el motivo de la anulación.')
        return redirect('cotizador:detalle', mov.cotizacion_id)
    mov.anulado, mov.anulado_en, mov.anulado_por, mov.motivo_anulacion = True, timezone.now(), request.user, motivo[:200]
    mov.save()
    que = f'Recibo N° {mov.numero_recibo}' if mov.numero_recibo else mov.get_tipo_display().split(' (')[0]
    messages.success(request, f'{que} anulado. Ya no cuenta en el saldo.')
    return redirect('cotizador:detalle', mov.cotizacion_id)


@login_required
@require_POST
@transaction.atomic
def anular_cotizacion(request, pk):
    """Anula una cotización. Si era una venta: anula su deuda y decide qué pasa con lo pagado."""
    cot = get_object_or_404(Cotizacion.objects.select_related('cliente'), pk=pk)
    if cot.estado == Cotizacion.ANULADA:
        return redirect('cotizador:detalle', pk)
    motivo = request.POST.get('motivo', '').strip()
    if not motivo:
        messages.error(request, 'Escribí el motivo de la anulación.')
        return redirect('cotizador:detalle', pk)
    avisos = []
    if cot.estado == Cotizacion.ACEPTADA:
        asignaciones = list(cot.asignaciones.all())
        if asignaciones and request.POST.get('quitar_diagrama'):
            p = Parametros.actuales()
            try:
                drive.quitar(p.diagrama_drive_id, [(a.unidad, a.desde, a.hasta, cot.cliente.nombre) for a in asignaciones])
            except (drive.ErrorDrive, dg.ErrorDiagrama) as e:
                messages.error(request, f'No se anuló: no se pudo quitar la reserva del diagrama ({e}). '
                                        f'Podés destildar "Quitar del diagrama" y borrarla a mano.')
                return redirect('cotizador:detalle', pk)
            cot.asignaciones.all().delete()
            avisos.append(f'se quitó del diagrama la unidad {", ".join(a.unidad for a in asignaciones)}')
        elif asignaciones:
            avisos.append(f'acordate de borrar del diagrama la unidad {", ".join(a.unidad for a in asignaciones)}')
        pagado = cot.total_pagos()
        ahora = timezone.now()
        cot.movimientos.filter(tipo__in=Movimiento.SUMAN, anulado=False).update(
            anulado=True, anulado_en=ahora, anulado_por=request.user, motivo_anulacion=f'Venta anulada: {motivo}'[:200])
        if pagado > 0:
            if request.POST.get('pagado') == 'devolver':
                Movimiento.objects.create(
                    cotizacion=cot, fecha=timezone.localdate(), tipo=Movimiento.DEVOLUCION, importe=pagado,
                    concepto=f'Devolución por cancelación de COT {cot.numero}', medio=request.POST.get('medio', '') or 'otro',
                    creado_por=request.user)
                avisos.append(f'se registró la devolución de $ {round(pagado):,}'.replace(',', '.'))
            else:
                Movimiento.objects.create(
                    cotizacion=cot, fecha=timezone.localdate(), tipo=Movimiento.CARGO, importe=pagado,
                    concepto=f'Seña retenida por cancelación de COT {cot.numero} (sin reintegro)', creado_por=request.user)
                avisos.append(f'lo pagado ($ {round(pagado):,}) queda como seña retenida'.replace(',', '.'))
    cot.estado_antes_de_anular = cot.estado
    cot.estado = Cotizacion.ANULADA
    cot.anulada_en, cot.anulada_por, cot.motivo_anulacion = timezone.now(), request.user, motivo[:200]
    cot.save()
    messages.success(request, f'Cotización {cot.numero} anulada' + (': ' + '; '.join(avisos) if avisos else '') + '.')
    return redirect('cotizador:detalle', pk)


@login_required
@require_POST
def quitar_unidad(request, pk):
    """Quita del diagrama de Drive la reserva de una unidad que anotó la app."""
    asignacion = get_object_or_404(AsignacionUnidad.objects.select_related('cotizacion__cliente'), pk=pk)
    cot = asignacion.cotizacion
    p = Parametros.actuales()
    try:
        drive.quitar(p.diagrama_drive_id, [(asignacion.unidad, asignacion.desde, asignacion.hasta, cot.cliente.nombre)])
    except (drive.ErrorDrive, dg.ErrorDiagrama) as e:
        messages.error(request, f'No se quitó del diagrama: {e}')
        return redirect('cotizador:detalle', cot.pk)
    asignacion.delete()
    messages.success(request, f'Se quitó la reserva de la unidad {asignacion.unidad} del diagrama.')
    return redirect('cotizador:detalle', cot.pk)


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
    if cot.fue_venta:
        messages.error(request, 'Una venta no se puede eliminar (tiene cuenta corriente). Usá "Anular".')
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
    aceptadas = Cotizacion.objects.filter(estado=Cotizacion.ACEPTADA).select_related('cliente').prefetch_related('lineas__vehiculo', 'asignaciones')
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
        cotizacion__cliente=cliente_obj, cotizacion__estado__in=Cotizacion.CON_CUENTA
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
    except Exception:
        logger.exception('Error inesperado buscando km')
        return JsonResponse({'error': 'Hubo un error inesperado al buscar en el mapa. Cargá los km a mano '
                                      'y avisá para revisarlo.'}, status=500)
    nombres = [origen] + paradas + ([origen] if ida_y_vuelta else [])
    return JsonResponse({
        'km': recorrido['km'],
        'tramos': recorrido['tramos'],
        'itinerario': ' – '.join(nombres) + '.',
        'encontrados': [l.nombre for l in recorrido['lugares']],
    })


def estado_mapa(request):
    """Diagnóstico: si cada servicio de mapas responde desde este servidor (sin datos de la empresa)."""
    return JsonResponse(rutas.estado_servicios(), json_dumps_params={'ensure_ascii': False})


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
                              'insumos_limpieza', 'precio_colacion']),
        ('Márgenes e IVA', ['margen_minimo', 'margen_intermedio', 'margen_mercado', 'margen_optimo',
                            'precio_referencia_km', 'porcentaje_iva']),
        ('Impuestos sobre la venta', ['porcentaje_tissh', 'porcentaje_amt', 'porcentaje_iibb']),
        ('Viajes a futuro', ['inflacion_mensual', 'proyectar_desde_dias']),
        ('Word de la cotización', ['origen_habitual', 'porcentaje_sena', 'vigencia_dias', 'incluye', 'no_incluye']),
        ('Diagrama de unidades', ['unidades_turismo', 'diagrama_drive_id']),
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
