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
    # Para un insumo que no está en el catálogo: se da de alta en el momento
    otro_nombre = forms.CharField(label='Otro insumo (no está en la lista)', max_length=120, required=False)
    otro_precio = forms.DecimalField(label='Precio unitario', max_digits=14, decimal_places=2, required=False, min_value=0)
    otro_categoria = forms.ChoiceField(label='Sección', choices=Articulo.CATEGORIAS, required=False, initial='otro')

    class Meta:
        model = EntregaInsumo
        fields = ['fecha', 'articulo', 'cantidad', 'observaciones']
        # La salida (o "del mes") la pone la pantalla desde donde se carga.
        widgets = {'fecha': FECHA}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['articulo'].queryset = Articulo.objects.filter(activo=True)
        self.fields['articulo'].required = False
        self.fields['articulo'].empty_label = '— elegí de la lista —'

    def clean(self):
        datos = super().clean()
        if not datos.get('articulo'):
            if not datos.get('otro_nombre'):
                raise forms.ValidationError('Elegí un artículo de la lista o escribí el nombre del otro insumo.')
            if datos.get('otro_precio') is None:
                self.add_error('otro_precio', 'Poné el precio del otro insumo.')
        return datos

    def save(self, commit=True):
        articulo = self.cleaned_data.get('articulo')
        if not articulo:
            # Se agrega al catálogo para poder elegirlo la próxima vez
            nombre = self.cleaned_data['otro_nombre'].strip()
            articulo = Articulo.objects.filter(nombre__iexact=nombre).first()
            if not articulo:
                ultimo = Articulo.objects.order_by('-codigo').values_list('codigo', flat=True).first() or 0
                articulo = Articulo.objects.create(codigo=ultimo + 1, nombre=nombre,
                                                   categoria=self.cleaned_data.get('otro_categoria') or 'otro',
                                                   precio=self.cleaned_data['otro_precio'])
            self.instance.articulo = articulo
            self.instance.precio_unitario = self.cleaned_data['otro_precio']
        if not self.instance.precio_unitario:
            self.instance.precio_unitario = articulo.precio
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
    """Los pagos y comprobantes son mensuales: se aplican al mes (y se reparten entre sus salidas)."""
    class Meta:
        fields = ['liquidacion', 'parte', 'importe', 'observaciones']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['liquidacion'].label = 'Mes'
        self.fields['liquidacion'].label_from_instance = lambda l: f'{l.nombre} ({l.servicios.count()} salidas)'
        self.fields['liquidacion'].queryset = Liquidacion.objects.order_by('-periodo')


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
