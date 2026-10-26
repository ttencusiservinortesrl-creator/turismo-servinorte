"""Importes en letras para el recibo: 1878500 -> 'un millón ochocientos setenta y ocho mil quinientos'."""

UNIDADES = ['', 'uno', 'dos', 'tres', 'cuatro', 'cinco', 'seis', 'siete', 'ocho', 'nueve', 'diez',
            'once', 'doce', 'trece', 'catorce', 'quince', 'dieciséis', 'diecisiete', 'dieciocho', 'diecinueve',
            'veinte', 'veintiuno', 'veintidós', 'veintitrés', 'veinticuatro', 'veinticinco', 'veintiséis',
            'veintisiete', 'veintiocho', 'veintinueve']
DECENAS = ['', '', '', 'treinta', 'cuarenta', 'cincuenta', 'sesenta', 'setenta', 'ochenta', 'noventa']
CENTENAS = ['', 'ciento', 'doscientos', 'trescientos', 'cuatrocientos', 'quinientos', 'seiscientos',
            'setecientos', 'ochocientos', 'novecientos']


def _hasta_999(n):
    if n == 0:
        return ''
    if n == 100:
        return 'cien'
    c, resto = divmod(n, 100)
    partes = [CENTENAS[c]] if c else []
    if resto < 30:
        partes.append(UNIDADES[resto])
    else:
        d, u = divmod(resto, 10)
        partes.append(DECENAS[d] + (f' y {UNIDADES[u]}' if u else ''))
    return ' '.join(p for p in partes if p)


def _apocope(texto):
    """'veintiuno mil' -> 'veintiún mil', 'uno millones' -> 'un millones' (se usa delante de mil/millón)."""
    if texto.endswith('veintiuno'):
        return texto[:-len('veintiuno')] + 'veintiún'
    if texto.endswith('uno'):
        return texto[:-3] + 'un'
    return texto


def numero_a_letras(n):
    n = int(n)
    if n == 0:
        return 'cero'
    if n < 0:
        return 'menos ' + numero_a_letras(-n)
    millones, resto = divmod(n, 1_000_000)
    miles, unidades = divmod(resto, 1000)
    partes = []
    if millones:
        partes.append('un millón' if millones == 1 else f'{_apocope(_miles_de(millones))} millones')
    if miles:
        partes.append('mil' if miles == 1 else f'{_apocope(_hasta_999(miles))} mil')
    if unidades:
        partes.append(_hasta_999(unidades))
    return ' '.join(partes)


def _miles_de(n):
    """Para los millones (hasta 999.999 millones)."""
    miles, unidades = divmod(n, 1000)
    partes = []
    if miles:
        partes.append('mil' if miles == 1 else f'{_apocope(_hasta_999(miles))} mil')
    if unidades:
        partes.append(_hasta_999(unidades))
    return ' '.join(partes)


def pesos_en_letras(importe):
    """'PESOS UN MILLÓN OCHOCIENTOS SETENTA Y OCHO MIL QUINIENTOS CON 00/100'"""
    entero = int(importe)
    centavos = round((importe - entero) * 100)
    return f'PESOS {numero_a_letras(entero).upper()} CON {centavos:02d}/100'
