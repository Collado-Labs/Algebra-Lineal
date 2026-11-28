"""Valores de máquina para lectura; los datos matemáticos nunca se modifican."""

from decimal import Decimal
from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from backend.funciones_reales import FuncionReal
from ..notacion_raices import vista_matematica

register = template.Library()


@register.filter
def numero_raices(valor, tipo=""):
    """Decimal llano del valor almacenado (sin notación científica).

    `tipo` agrupa magnitudes comparables (x, f, error…): en el navegador, las protecciones contra
    valores distintos que parecen iguales solo comparan números del mismo tipo y grupo.
    """
    completo = repr(float(valor))
    texto = format(Decimal(completo), "f")
    if tipo:
        return format_html('<span data-raices-numero="{}" data-raices-tipo="{}" title="Valor almacenado: {}">{}</span>',
                           completo, tipo, texto, texto)
    return format_html('<span data-raices-numero="{}" title="Valor almacenado: {}">{}</span>', completo, texto, texto)


@register.filter
def valor_criterio(valor, criterio):
    if valor is None:
        return "No evaluable"
    if criterio == "porcentual":
        escala = float(Decimal(str(valor)) * 100)
        if escala == float("inf"):
            return format_html("{}%", f"{Decimal(str(valor)) * 100:.6E}")
        return format_html("{}%", numero_raices(escala, "criterio"))
    return numero_raices(valor, "criterio")


@register.filter
def vista_funcion(datos):
    # Al reabrir una resolución, renderizar solo desde una expresión validada.
    try:
        funcion = FuncionReal(datos.get("funcion_original") or datos.get("funcion"))
    except ValueError:
        return ""
    return mark_safe(vista_matematica(funcion)["mathml"])
