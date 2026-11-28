"""Tolerancias y medidas de parada en las unidades propias de cada criterio."""

from fractions import Fraction
from math import inf, isfinite, nextafter
import re
from sys import float_info

from .funciones_reales import SIGNOS_MATEMATICOS, normalizar_potencias
from .seguridad_numerica import validar_literal_numerico

ABSOLUTO, RELATIVO, PORCENTUAL = "absoluto", "relativo", "porcentual"
CRITERIOS = (ABSOLUTO, RELATIVO, PORCENTUAL)
_NO_EVALUABLE = ("criterio_indefinido",
                "Se obtuvo un cero de máquina, pero el criterio relativo queda indefinido "
                "con una aproximación nula o subnormal. Elige el criterio absoluto.")
_DIGITOS = r"[0-9](?:_?[0-9])*"
_NUMERO = re.compile(rf"[+]?(?:{_DIGITOS}(?:\.(?:{_DIGITOS})?)?|\.{_DIGITOS})(?:[eE]([+-]?[0-9]{{1,4}}))?")
_POTENCIA_DIEZ = re.compile(r"10\s*\*\*\s*(?:\(\s*([+-]?[0-9]{1,4})\s*\)|([+-]?[0-9]{1,4}))")
_FRACCION = re.compile(rf"[+]?{_DIGITOS}\s*/\s*{_DIGITOS}")


def validar_criterio(criterio):
    if criterio not in CRITERIOS:
        raise ValueError("Elige un criterio de tolerancia válido.")


def leer_tolerancia(texto, criterio=ABSOLUTO, *, predeterminada, admitir_fraccion=False):
    """Devuelve (umbral exacto, criterio). El porcentaje se compara como proporción."""
    validar_criterio(criterio)
    if not texto.strip():
        return Fraction(str(predeterminada)), criterio
    if len(texto) > 210:
        raise ValueError("La tolerancia es demasiado larga.")
    literal = texto.strip().translate(SIGNOS_MATEMATICOS).replace(",", ".")
    if literal.endswith("%"):
        literal = literal[:-1].strip()
        criterio = PORCENTUAL
    literal = normalizar_potencias(literal)
    numero = _NUMERO.fullmatch(literal)
    potencia = _POTENCIA_DIEZ.fullmatch(literal)
    try:
        if potencia:
            exponente = int(potencia[1] or potencia[2])
            if abs(exponente) > 400:
                raise ValueError
            valor = Fraction(10) ** exponente
        elif numero and abs(int(numero[1] or 0)) <= 400:
            if admitir_fraccion and not numero[1]:
                validar_literal_numerico(literal)
            valor = Fraction(literal)
        elif admitir_fraccion and _FRACCION.fullmatch(literal):
            validar_literal_numerico(literal)
            valor = Fraction(re.sub(r"\s+", "", literal))
        else:
            raise ValueError
        if criterio == PORCENTUAL:
            if not isfinite(float(valor)):
                raise ValueError
            valor /= 100
        if not 0 < float(valor) < inf:
            raise ValueError
    except (ValueError, ZeroDivisionError, OverflowError):
        raise ValueError("La tolerancia debe ser positiva y representable. Escribe, por ejemplo, 0.01%, 1e-6 o 10⁻⁶.") from None
    return valor, criterio


def medida_relativa(cambio, escala):
    """Divide por una escala normal; una escala pequeña representable sigue siendo válida."""
    if cambio is None or abs(escala) < float_info.min:
        return None
    razon = cambio / abs(escala)
    return razon if razon <= float_info.max and isfinite(razon) else None


def cota_relativa_intervalo(a, b, aproximacion):
    """Acota la distancia relativa a cualquier raíz del intervalo que excluye cero."""
    if a <= 0 <= b or min(abs(a), abs(b)) < float_info.min:
        return None
    a, b, aproximacion = map(Fraction, (a, b, aproximacion))
    cota = max(abs(aproximacion - a), abs(aproximacion - b)) / min(abs(a), abs(b))
    if cota > float_info.max:
        return None
    valor = float(cota)
    return nextafter(valor, inf) if valor < cota else valor


def motivo_cero(criterio, punto, mensaje):
    if criterio != ABSOLUTO and abs(punto) < float_info.min:
        return _NO_EVALUABLE
    return "exacta", mensaje
