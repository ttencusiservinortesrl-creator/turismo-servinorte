from django import forms

from .models import Cotizacion, Parametros, TipoVehiculo


class CotizacionForm(forms.ModelForm):
    class Meta:
        model = Cotizacion
        fields = [
            'numero', 'fecha', 'cliente', 'contacto',
            'origen', 'paradas', 'ida_y_vuelta', 'itinerario', 'km_servicio', 'km_vacios', 'km_mapa',
            'salida', 'regreso', 'texto_salida', 'dias', 'noches',
            'vehiculo', 'cantidad_vehiculos', 'descripcion_vehiculo', 'choferes', 'viaticos_por_chofer', 'habitaciones',
            'incluye_hotel', 'incluye_estacionamiento', 'incluye_lavadero', 'peaje', 'otros_gastos',
            'tarifa_neta', 'incluye', 'no_incluye', 'notas_internas',
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
        self.fields['vehiculo'].queryset = TipoVehiculo.objects.filter(activo=True)
        self.fields['vehiculo'].empty_label = None
        for nombre, campo in self.fields.items():
            if isinstance(campo.widget, forms.CheckboxInput):
                campo.widget.attrs['class'] = 'form-check-input'
            elif isinstance(campo.widget, forms.Select):
                campo.widget.attrs['class'] = 'form-select'
            else:
                campo.widget.attrs['class'] = 'form-control'

    def clean(self):
        datos = super().clean()
        if datos.get('salida') and datos.get('regreso') and datos['regreso'] < datos['salida']:
            self.add_error('regreso', 'El regreso no puede ser antes de la salida.')
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
