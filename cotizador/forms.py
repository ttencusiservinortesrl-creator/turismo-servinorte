from django import forms

from .models import Cliente, Cotizacion, LineaVehiculo, Movimiento, Parametros, TipoVehiculo


def _estilo(form):
    for campo in form.fields.values():
        if isinstance(campo.widget, forms.CheckboxInput):
            campo.widget.attrs['class'] = 'form-check-input'
        elif isinstance(campo.widget, forms.Select):
            campo.widget.attrs['class'] = 'form-select'
        else:
            campo.widget.attrs['class'] = 'form-control'


class CotizacionForm(forms.ModelForm):
    nuevo_cliente = forms.CharField(label='…o cliente nuevo (nombre)', required=False, max_length=200)
    nuevo_cliente_telefono = forms.CharField(label='Teléfono del cliente nuevo', required=False, max_length=60)

    class Meta:
        model = Cotizacion
        fields = [
            'numero', 'fecha', 'cliente',
            'origen', 'paradas', 'ida_y_vuelta', 'itinerario', 'km_servicio', 'km_vacios', 'km_mapa',
            'salida', 'regreso', 'texto_salida', 'dias', 'noches',
            'viaticos_por_chofer', 'habitaciones',
            'incluye_hotel', 'incluye_estacionamiento', 'incluye_lavadero', 'peaje', 'otros_gastos',
            'proyectar_inflacion', 'inflacion_mensual', 'tarifa_neta', 'incluye', 'no_incluye', 'notas_internas',
        ]
        widgets = {
            'fecha': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'salida': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'regreso': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'paradas': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Ej.:\nOrán, Salta'}),
            'incluye': forms.Textarea(attrs={'rows': 4}),
            'no_incluye': forms.Textarea(attrs={'rows': 2}),
            'notas_internas': forms.Textarea(attrs={'rows': 2}),
            'km_mapa': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['cliente'].required = False
        self.fields['cliente'].empty_label = '— elegir cliente —'
        _estilo(self)

    def clean(self):
        datos = super().clean()
        if datos.get('salida') and datos.get('regreso') and datos['regreso'] < datos['salida']:
            self.add_error('regreso', 'El regreso no puede ser antes de la salida.')
        if not datos.get('cliente') and not datos.get('nuevo_cliente', '').strip():
            self.add_error('cliente', 'Elegí un cliente o escribí el nombre de uno nuevo.')
        return datos

    def save(self, commit=True):
        cot = super().save(commit=False)
        nombre = self.cleaned_data.get('nuevo_cliente', '').strip()
        if nombre and not self.cleaned_data.get('cliente'):
            cliente = Cliente.objects.filter(nombre__iexact=nombre).first()
            cot.cliente = cliente or Cliente.objects.create(
                nombre=nombre, telefono=self.cleaned_data.get('nuevo_cliente_telefono', '').strip())
        if commit:
            cot.save()
        return cot


class LineaVehiculoForm(forms.ModelForm):
    class Meta:
        model = LineaVehiculo
        fields = ['vehiculo', 'cantidad', 'choferes', 'descripcion']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['vehiculo'].queryset = TipoVehiculo.objects.filter(activo=True)
        self.fields['vehiculo'].empty_label = None
        self.fields['cantidad'].min_value = 1
        _estilo(self)


def lineas_validas(formset):
    """Las líneas completas del formset (para la vista previa, aunque el resto tenga errores)."""
    lineas = []
    for f in formset.forms:
        datos = getattr(f, 'cleaned_data', None) or {}
        if datos.get('vehiculo') and not datos.get('DELETE'):
            lineas.append(datos)
    return lineas


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ['nombre', 'cuit', 'condicion_iva', 'contacto', 'telefono', 'email', 'direccion', 'localidad', 'notas']
        widgets = {'notas': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _estilo(self)


class MovimientoForm(forms.ModelForm):
    class Meta:
        model = Movimiento
        fields = ['fecha', 'tipo', 'concepto', 'importe', 'medio', 'referencia']
        widgets = {'fecha': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _estilo(self)

    def clean_importe(self):
        importe = self.cleaned_data['importe']
        if importe <= 0:
            raise forms.ValidationError('El importe tiene que ser mayor a cero.')
        return importe

    def clean(self):
        datos = super().clean()
        if datos.get('tipo') == Movimiento.PAGO and not datos.get('medio'):
            self.add_error('medio', 'Indicá cómo pagó.')
        return datos


class ParametrosForm(forms.ModelForm):
    class Meta:
        model = Parametros
        exclude = ['actualizado', 'actualizado_por']
        widgets = {
            'incluye': forms.Textarea(attrs={'rows': 4}),
            'no_incluye': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            campo.widget.attrs['class'] = 'form-control'


class TipoVehiculoForm(forms.ModelForm):
    class Meta:
        model = TipoVehiculo
        fields = ['nombre', 'capacidad', 'rendimiento_km_litro', 'descripcion_word', 'orden', 'activo']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            campo.widget.attrs['class'] = 'form-check-input' if isinstance(campo.widget, forms.CheckboxInput) else 'form-control'
