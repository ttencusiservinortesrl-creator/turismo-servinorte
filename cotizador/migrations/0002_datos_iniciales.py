from django.db import migrations

VEHICULOS = [
    # nombre, pasajeros, descripción en el Word
    ('Doble piso', 60, 'BUS  Doble Piso 60 pasajeros'),
    ('Piso elevado', 48, 'BUS  Piso Elevado 50 pasajeros'),
    ('Piso elevado +', 56, 'BUS  Piso Elevado 56 pasajeros'),
    ('Minibus', 22, 'MINIBUS  22 pasajeros'),
    ('Transit', 15, 'TRANSIT  15 pasajeros'),
]


def cargar(apps, schema_editor):
    TipoVehiculo = apps.get_model('cotizador', 'TipoVehiculo')
    Parametros = apps.get_model('cotizador', 'Parametros')
    orden = {'Piso elevado': 1}
    for i, (nombre, capacidad, descripcion) in enumerate(VEHICULOS):
        TipoVehiculo.objects.get_or_create(nombre=nombre, defaults={
            'capacidad': capacidad, 'descripcion_word': descripcion, 'orden': orden.get(nombre, i + 2)})
    if not Parametros.objects.exists():
        Parametros.objects.create()


class Migration(migrations.Migration):
    dependencies = [('cotizador', '0001_inicial')]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
