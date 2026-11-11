from django import forms

from .models import (Articulo, Comprobante, EntregaInsumo, ImputacionComprobante, ImputacionPago, Liquidacion, Pago,
                     ServicioMAT)


def _estilo(form):
    for campo in form.fields.values():
        if isinstance(campo.widget, forms.CheckboxInput):
            campo.widget.attrs['class'] = 'form-check-input'
        elif isinstance(campo.widget, forms.Select):
            campo.widget.attrs['class'] = 'form-select'
        else:
            campo.widget.attrs['class'] = 'form-control'


FECHA = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


class Estilado:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _estilo(self)


class LiquidacionForm(Estilado, forms.ModelForm):
    mes = forms.DateField(label='Mes', widget=forms.DateInput(attrs={'type': 'month'}, format='%Y-%m'),
                          input_formats=['%Y-%m', '%Y-%m-%d'])

    class Meta:
        model = Liquidacion
        fields = ['porcentaje_facturado', 'porcentaje_iva', 'precio_agua', 'neto_manual', 'notas']
        widgets = {'notas': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['mes'].initial = self.instance.periodo
        self.order_fields(['mes'] + list(self.Meta.fields))

    def clean_mes(self):
        mes = self.cleaned_data['mes'].replace(day=1)
        otra = Liquidacion.objects.filter(periodo=mes).exclude(pk=self.instance.pk)
        if otra.exists():
            raise forms.ValidationError('Ya hay una liquidación para ese mes.')
        return mes

    def save(self, commit=True):
        self.instance.periodo = self.cleaned_data['mes']
        return super().save(commit)


class TarifasOpcionales:
    """Las tres tarifas no son obligatorias: si se dejan vacías quedan en 0."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for c in ('tarifa_minima', 'tarifa_intermedia', 'tarifa_optima', 'unidades_agua'):
            self.fields[c].required = False

    def clean(self):
        datos = super().clean()
        for c in ('tarifa_minima', 'tarifa_intermedia', 'tarifa_optima', 'unidades_agua'):
            if datos.get(c) in (None, ''):
                datos[c] = 0
        return datos


class SalidaForm(Estilado, TarifasOpcionales, forms.ModelForm):
    """Salida nueva: el mes (liquidación) se toma de la fecha."""
    class Meta:
        model = ServicioMAT
        fields = ['fecha', 'unidad', 'servicio', 'tarifa_minima', 'tarifa_intermedia', 'tarifa_optima', 'tarifa_elegida',
                  'tarifa_otra', 'unidades_agua', 'observaciones']
        widgets = {'fecha': FECHA}


class ServicioForm(Estilado, TarifasOpcionales, forms.ModelForm):
    class Meta:
        model = ServicioMAT
        fields = ['fecha', 'unidad', 'servicio', 'tarifa_minima', 'tarifa_intermedia', 'tarifa_optima', 'tarifa_elegida',
                  'tarifa_otra', 'unidades_agua', 'observaciones']
        widgets = {'fecha': FECHA}


class EntregaForm(Estilado, forms.ModelForm):
    class Meta:
        model = EntregaInsumo
        fields = ['fecha', 'articulo', 'cantidad', 'observaciones']
        # La salida (o "del mes") la pone la pantalla desde donde se carga.
        widgets = {'fecha': FECHA}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['articulo'].queryset = Articulo.objects.filter(activo=True)

    def save(self, commit=True):
        if not self.instance.precio_unitario:
            self.instance.precio_unitario = self.cleaned_data['articulo'].precio
        return super().save(commit)


class ArticuloForm(Estilado, forms.ModelForm):
    class Meta:
        model = Articulo
        fields = ['codigo', 'nombre', 'categoria', 'precio', 'activo']


class ComprobanteForm(Estilado, forms.ModelForm):
    class Meta:
        model = Comprobante
        fields = ['fecha', 'tipo', 'numero', 'importe', 'motivo', 'observaciones']
        widgets = {'fecha': FECHA}


class PagoForm(Estilado, forms.ModelForm):
    class Meta:
        model = Pago
        fields = ['fecha', 'medio', 'moneda', 'importe_origen', 'tipo_cambio', 'banco_referencia', 'tipo_recibo',
                  'numero_recibo', 'comprobante', 'observaciones']
        widgets = {'fecha': FECHA}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['comprobante'].queryset = Comprobante.objects.filter(anulado=False).order_by('-fecha')
        self.fields['comprobante'].empty_label = '— sin factura —'


class ImputacionForm(Estilado, forms.ModelForm):
    class Meta:
        fields = ['servicio', 'liquidacion', 'parte', 'importe', 'observaciones']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['liquidacion'].label_from_instance = lambda l: f'{l.codigo} · {l.nombre}'
        self.fields['liquidacion'].required = False
        self.fields['liquidacion'].help_text = 'Si elegís una salida, se completa solo.'
        self.fields['servicio'].queryset = ServicioMAT.objects.select_related('liquidacion').order_by('-fecha')
        self.fields['servicio'].label_from_instance = lambda s: f'{s.fecha:%d/%m/%Y} · {s.servicio} · {s.unidad}'
        self.fields['servicio'].empty_label = '— a cuenta del mes —'

    def clean(self):
        datos = super().clean()
        salida, liquidacion = datos.get('servicio'), datos.get('liquidacion')
        if salida and liquidacion and salida.liquidacion_id != liquidacion.pk:
            self.add_error('liquidacion', 'La salida es de otro mes.')
        elif salida:
            datos['liquidacion'] = salida.liquidacion
            self.instance.liquidacion = salida.liquidacion
        elif not liquidacion and datos.get('importe'):
            self.add_error('liquidacion', 'Elegí la salida o el mes.')
        return datos


class ImputacionPagoForm(ImputacionForm):
    class Meta(ImputacionForm.Meta):
        model = ImputacionPago


class ImputacionComprobanteForm(ImputacionForm):
    class Meta(ImputacionForm.Meta):
        model = ImputacionComprobante


ImputacionesPagoFormSet = forms.inlineformset_factory(Pago, ImputacionPago, form=ImputacionPagoForm, extra=2, can_delete=True)
ImputacionesComprobanteFormSet = forms.inlineformset_factory(Comprobante, ImputacionComprobante, form=ImputacionComprobanteForm,
                                                             extra=2, can_delete=True)


class ImportarForm(forms.Form):
    archivo = forms.FileField(label='Planilla de Excel (.xlsx)')
    confirmar = forms.BooleanField(label='Entiendo que se reemplaza todo lo cargado de Marco Antonio', required=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _estilo(self)
