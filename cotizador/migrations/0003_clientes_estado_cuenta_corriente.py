import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def pasar_clientes(apps, schema_editor):
    """El cliente era un texto en cada cotización: se crea una ficha por nombre."""
    Cliente = apps.get_model('cotizador', 'Cliente')
    Cotizacion = apps.get_model('cotizador', 'Cotizacion')
    for cot in Cotizacion.objects.all():
        nombre = cot.cliente.strip() or 'Sin nombre'
        cliente = Cliente.objects.filter(nombre__iexact=nombre).first()
        if not cliente:
            cliente = Cliente.objects.create(nombre=nombre, telefono=cot.contacto[:60])
        cot.cliente_ficha = cliente
        cot.save(update_fields=['cliente_ficha'])


class Migration(migrations.Migration):

    dependencies = [
        ('cotizador', '0002_datos_iniciales'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Cliente',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=200, verbose_name='Nombre o razón social')),
                ('cuit', models.CharField(blank=True, max_length=20, verbose_name='CUIT / DNI')),
                ('condicion_iva', models.CharField(blank=True, choices=[('Consumidor Final', 'Consumidor Final'), ('Responsable Inscripto', 'Responsable Inscripto'), ('Monotributista', 'Monotributista'), ('Exento', 'Exento')], max_length=40, verbose_name='Condición de IVA')),
                ('contacto', models.CharField(blank=True, max_length=120, verbose_name='Persona de contacto')),
                ('telefono', models.CharField(blank=True, max_length=60, verbose_name='Teléfono')),
                ('email', models.EmailField(blank=True, max_length=254, verbose_name='Mail')),
                ('direccion', models.CharField(blank=True, max_length=200, verbose_name='Dirección')),
                ('localidad', models.CharField(blank=True, max_length=120)),
                ('notas', models.TextField(blank=True)),
                ('creado', models.DateTimeField(auto_now_add=True)),
            ],
            options={'ordering': ['nombre']},
        ),
        migrations.AddField(
            model_name='cotizacion',
            name='cliente_ficha',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='cotizaciones', to='cotizador.cliente'),
        ),
        migrations.RunPython(pasar_clientes, migrations.RunPython.noop),
        migrations.RemoveField(model_name='cotizacion', name='cliente'),
        migrations.RemoveField(model_name='cotizacion', name='contacto'),
        migrations.RenameField(model_name='cotizacion', old_name='cliente_ficha', new_name='cliente'),
        migrations.AlterField(
            model_name='cotizacion',
            name='cliente',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='cotizaciones', to='cotizador.cliente'),
        ),
        migrations.AddField(
            model_name='cotizacion',
            name='estado',
            field=models.CharField(choices=[('pendiente', 'Pendiente'), ('aceptada', 'Aceptada'), ('rechazada', 'Rechazada')], default='pendiente', max_length=10),
        ),
        migrations.AddField(
            model_name='cotizacion',
            name='fecha_estado',
            field=models.DateField(blank=True, null=True, verbose_name='Fecha de aceptación / rechazo'),
        ),
        migrations.AddField(
            model_name='cotizacion',
            name='motivo_rechazo',
            field=models.CharField(blank=True, max_length=200, verbose_name='Motivo del rechazo'),
        ),
        migrations.CreateModel(
            name='Movimiento',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha', models.DateField()),
                ('tipo', models.CharField(choices=[('cargo', 'Cargo (suma a la deuda)'), ('pago', 'Pago / seña')], max_length=10)),
                ('concepto', models.CharField(max_length=200)),
                ('importe', models.DecimalField(decimal_places=2, max_digits=16)),
                ('medio', models.CharField(blank=True, choices=[('efectivo', 'Efectivo'), ('transferencia', 'Transferencia'), ('cheque', 'Cheque'), ('tarjeta', 'Tarjeta'), ('otro', 'Otro')], max_length=20, verbose_name='Medio de pago')),
                ('referencia', models.CharField(blank=True, help_text='N° de recibo, factura, transferencia o cheque.', max_length=120, verbose_name='Comprobante / referencia')),
                ('automatico', models.BooleanField(default=False, editable=False)),
                ('creado', models.DateTimeField(auto_now_add=True)),
                ('cotizacion', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='movimientos', to='cotizador.cotizacion')),
                ('creado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={'verbose_name': 'movimiento de cuenta corriente', 'verbose_name_plural': 'movimientos de cuenta corriente', 'ordering': ['fecha', 'id']},
        ),
    ]
