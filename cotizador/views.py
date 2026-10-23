from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import calculo, rutas, word
from .forms import CotizacionForm, ParametrosForm, TipoVehiculoForm
from .models import Cotizacion, Parametros, TipoVehiculo


@login_required
def lista(request):
    q = request.GET.get('q', '').strip()
    cotizaciones = Cotizacion.objects.select_related('vehiculo')
    if q:
        filtro = Q(cliente__icontains=q) | Q(itinerario__icontains=q) | Q(paradas__icontains=q)
        if q.isdigit():
            filtro |= Q(numero=int(q))
        cotizaciones = cotizaciones.filter(filtro)
    return render(request, 'cotizador/lista.html', {'cotizaciones': cotizaciones[:200], 'q': q})


def _guardar(request, form, p):
    cot = form.save(commit=False)
    resultado = calculo.calcular(p, {**form.cleaned_data})
    cot.costo_total = resultado['costo']
    cot.detalle = calculo.para_guardar(resultado, p)
    if not cot.creado_por_id:
        cot.creado_por = request.user
    cot.save()
    return cot


@login_required
def nueva(request):
    p = Parametros.actuales()
    if request.method == 'POST':
        form = CotizacionForm(request.POST)
        if form.is_valid():
            cot = _guardar(request, form, p)
            messages.success(request, f'Cotización {cot.numero} guardada.')
            return redirect('cotizador:detalle', cot.pk)
    else:
        inicial = {
            'numero': Cotizacion.proximo_numero(), 'fecha': timezone.localdate(),
            'origen': p.origen_habitual, 'incluye': p.incluye, 'no_incluye': p.no_incluye,
        }
        base = Cotizacion.objects.filter(pk=request.GET.get('copiar')).first() if request.GET.get('copiar') else None
        if base:
            copia = {f: getattr(base, f) for f in CotizacionForm.Meta.fields if f not in ('numero', 'fecha')}
            copia['vehiculo'] = base.vehiculo_id
            copia['salida'] = timezone.localtime(base.salida)
            copia['regreso'] = timezone.localtime(base.regreso)
            inicial.update(copia)
        else:
            vehiculo = TipoVehiculo.objects.filter(activo=True).first()
            if vehiculo:
                inicial.update(vehiculo=vehiculo.pk, descripcion_vehiculo=vehiculo.descripcion_word)
        form = CotizacionForm(initial=inicial)
    return render(request, 'cotizador/form.html', {'form': form, 'p': p, 'vehiculos': _vehiculos_js()})


@login_required
def editar(request, pk):
    cot = get_object_or_404(Cotizacion, pk=pk)
    p = Parametros.actuales()
    if request.method == 'POST':
        form = CotizacionForm(request.POST, instance=cot)
        if form.is_valid():
            _guardar(request, form, p)
            messages.success(request, f'Cotización {cot.numero} actualizada con los parámetros de hoy.')
            return redirect('cotizador:detalle', cot.pk)
    else:
        form = CotizacionForm(instance=cot, initial={
            'salida': timezone.localtime(cot.salida), 'regreso': timezone.localtime(cot.regreso)})
    return render(request, 'cotizador/form.html', {'form': form, 'p': p, 'cot': cot, 'vehiculos': _vehiculos_js()})


def _vehiculos_js():
    return {v.pk: {'descripcion': v.descripcion_word, 'capacidad': v.capacidad}
            for v in TipoVehiculo.objects.filter(activo=True)}


@login_required
def detalle(request, pk):
    cot = get_object_or_404(Cotizacion.objects.select_related('vehiculo', 'creado_por'), pk=pk)
    return render(request, 'cotizador/detalle.html', {'cot': cot, 'r': cot.detalle})


@login_required
def descargar_word(request, pk):
    cot = get_object_or_404(Cotizacion, pk=pk)
    respuesta = HttpResponse(
        word.generar(cot),
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    respuesta['Content-Disposition'] = f'attachment; filename="{word.nombre_archivo(cot)}"'
    return respuesta


@login_required
@require_POST
def eliminar(request, pk):
    cot = get_object_or_404(Cotizacion, pk=pk)
    numero = cot.numero
    cot.delete()
    messages.success(request, f'Cotización {numero} eliminada.')
    return redirect('cotizador:lista')


@login_required
@require_POST
def calcular(request):
    """Vista previa del cálculo mientras se completa el formulario."""
    form = CotizacionForm(request.POST)
    form.is_valid()
    resultado = calculo.calcular(Parametros.actuales(), form.cleaned_data)
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
