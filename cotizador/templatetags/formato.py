from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def pesos(valor, decimales=0):
    """1700000 -> 1.700.000 (formato argentino)."""
    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        return valor
    texto = f'{numero:,.{int(decimales)}f}'
    return texto.replace(',', 'X').replace('.', ',').replace('X', '.')
