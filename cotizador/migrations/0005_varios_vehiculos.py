import django.db.models.deletion
from django.db import migrations, models


def pasar_a_lineas(apps, schema_editor):
    """Cada cotización tenía un solo tipo de vehículo: pasa a ser su primera línea."""
    Cotizacion = apps.get_model('cotizador', 'Cotizacion')
    LineaVehiculo = apps.get_model('cotizador', 'LineaVehiculo')
    for cot in Cotizacion.objects.all():
        LineaVehiculo.objects.create(cotizacion=cot, vehiculo_id=cot.vehiculo_id, cantidad=cot.cantidad_vehiculos,
                                     choferes=cot.choferes, descripcion=cot.descripcion_vehiculo)


class Migration(migrations.Migration):

    dependencies = [
        ('cotizador', '0004_inflacion'),
    ]

    operations = [
        migrations.CreateModel(
            name='LineaVehiculo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cantidad', models.PositiveIntegerField(default=1)),
                ('choferes', models.PositiveIntegerField(default=1, verbose_name='Choferes c/u')),
                ('descripcion', models.CharField(max_length=120, verbose_name='Cómo sale en el Word')),
                ('orden', models.PositiveIntegerField(default=0)),
                ('cotizacion', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lineas', to='cotizador.cotizacion')),
                ('vehiculo', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='cotizador.tipovehiculo', verbose_name='Vehículo')),
            ],
            options={
                'verbose_name': 'vehículo de la cotización',
                'verbose_name_plural': 'vehículos de la cotización',
                'ordering': ['orden', 'id'],
            },
        ),
        migrations.RunPython(pasar_a_lineas, migrations.RunPython.noop),
        migrations.RemoveField(model_name='cotizacion', name='cantidad_vehiculos'),
        migrations.RemoveField(model_name='cotizacion', name='choferes'),
        migrations.RemoveField(model_name='cotizacion', name='descripcion_vehiculo'),
        migrations.RemoveField(model_name='cotizacion', name='vehiculo'),
        migrations.AlterField(
            model_name='cotizacion',
            name='habitaciones',
            field=models.PositiveIntegerField(default=1, verbose_name='Habitaciones de hotel por vehículo'),
        ),
        migrations.AlterField(
            model_name='cotizacion',
            name='peaje',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name='Peajes por vehículo ($)'),
        ),
    ]
