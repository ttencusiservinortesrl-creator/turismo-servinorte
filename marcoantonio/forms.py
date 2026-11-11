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


class ServicioForm(Estilado, forms.ModelForm):
    class Meta:
        model = ServicioMAT
        fields = ['fecha', 'unidad', 'servicio', 'tarifa_minima', 'tarifa_intermedia', 'tarifa_optima', 'tarifa_elegida',
                  'tarifa_otra', 'unidades_agua', 'observaciones']
        widgets = {'fecha': FECHA}


class EntregaForm(Estilado, forms.ModelForm):
    class Meta:
        model = EntregaInsumo
        fields = ['fecha', 'articulo', 'cantidad', 'observaciones']
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
        fields = ['liquidacion', 'parte', 'importe', 'observaciones']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['liquidacion'].label_from_instance = lambda l: f'{l.codigo} · {l.nombre}'


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
