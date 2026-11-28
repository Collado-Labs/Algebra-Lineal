"""Regla falsa clásica con error absoluto aproximado y confirmación por signos."""

from fractions import Fraction
import math

from .funciones_reales import finito
from .metodos_cerrados import MAX_ITERACIONES, TOLERANCIA, preparar_intervalo
from .resultados_raices import ClasificacionRaices as Clasificacion
from .tolerancias import ABSOLUTO, medida_relativa, motivo_cero


def interseccion_secante(a, b, fa, fb):
    """Corte con el eje x de la recta que une (a, f(a)) y (b, f(b))."""
    try:
        # Interpolar los floats como racionales evita desbordamiento y cancelación intermedios.
        a, b, fa, fb = map(Fraction, (a, b, fa, fb))
        return finito((a * fb - b * fa) / (fb - fa))
    except (ArithmeticError, ValueError) as error:
        raise ValueError("No se puede calcular xr: la recta secante excede el rango de los números de máquina.") from error


def confirmar_cercania(funcion, xr, fxr, a, b, tolerancia):
    """Buscar un cambio de signo a no más de una tolerancia hacia el otro extremo."""
    # Tras la sustitución xr es un extremo; la raíz quedó hacia el extremo opuesto.
    prueba = min(xr + tolerancia, b) if xr == a else max(xr - tolerancia, a)
    # La suma redondeada puede alejar el punto más de la tolerancia solicitada.
    if abs(Fraction(prueba) - Fraction(xr)) > Fraction(tolerancia):
        prueba = math.nextafter(prueba, xr)
    f_prueba = funcion(prueba)
    return prueba, f_prueba, f_prueba == 0 or (f_prueba < 0) != (fxr < 0)


def regla_falsa(funcion, a, b, tolerancia=TOLERANCIA, max_iteraciones=MAX_ITERACIONES, *, criterio=ABSOLUTO):
    """Aplica Regla falsa en [a, b] y devuelve un diccionario serializable con la tabla y su conclusión.

    Valida como `biseccion`, mediante `preparar_intervalo`. Converge con f(xr) = 0 en máquina
    ("exacta") o cuando Ea = |xrᵢ − xrᵢ₋₁| no supera la tolerancia y un cambio de signo a esa
    distancia de xr confirma una raíz ("tolerancia"); solo entonces `cota` acota |xr − raíz|.
    Sin esa confirmación sigue iterando; si se agotan las iteraciones con Ea ya pequeño, el
    estado es "estancamiento", no convergencia.
    Estados y claves de cada fila: docs/regla-falsa.md.
    """
    inicial, tolerancia, impedimento = preparar_intervalo(funcion, a, b, tolerancia, max_iteraciones, "tolerancia", criterio=criterio)
    a, b, fa, fb = (inicial[k] for k in ("a", "b", "fa", "fb"))
    filas = []

    def resultado(xr, estado, mensaje, clasificacion=None):
        fxr = funcion(xr) if xr is not None else None  # Verificación final independiente del valor guardado en la fila.
        ultima = filas[-1] if filas and filas[-1]["xr"] == xr else {}
        convergio = estado in ("exacta", "tolerancia")
        clasificacion = clasificacion or (Clasificacion.RAIZ_APROXIMADA if convergio else Clasificacion.SIN_CONVERGENCIA)
        cota = None
        if estado == "tolerancia":
            # La distancia confirmada se redondea hacia arriba para conservar la cota.
            cota = math.nextafter(abs(ultima["prueba"] - xr), math.inf)
            if criterio == ABSOLUTO:
                cota = min(tolerancia, cota)
        return {"clasificacion": clasificacion, "inicial": inicial, "max_iteraciones": max_iteraciones,
                "xr": xr, "fxr": fxr, "residuo": abs(fxr) if fxr is not None else None, "a": a, "b": b, "fa": fa, "fb": fb,
                "longitud": b - a, "tolerancia": tolerancia, "iteraciones": filas, "estado": estado,
                "convergio": convergio, "mensaje": mensaje,
                "criterio": criterio, "valor_criterio": ultima.get("valor_criterio"),
                "tolerancia_prueba": ultima.get("tolerancia_prueba"),
                "error_absoluto": ultima.get("error_absoluto"), "prueba": ultima.get("prueba"),
                "f_prueba": ultima.get("f_prueba"), "extremo_fijo": ultima.get("extremo_fijo"),
                "veces_fijo": ultima.get("veces_fijo", 0),
                "cota": cota}

    if impedimento:
        estado, clasificacion, mensaje = impedimento
        return resultado(None, estado, mensaje, clasificacion)

    if fa == 0 or fb == 0:
        xr = a if fa == 0 else b
        a = b = xr
        fa = fb = 0.
        return resultado(xr, *motivo_cero(criterio, xr, "Raíz en un extremo: f(xr) = 0."))
    anterior = fijo = None
    veces_fijo = 0
    for i in range(1, max_iteraciones + 1):
        xr = interseccion_secante(a, b, fa, fb)
        if not a < xr < b:
            # El redondeo llevó xr a un extremo: ya no hay un punto nuevo que evaluar.
            return resultado(min(max(xr, a), b), "maquina",
                             "No converge a la tolerancia pedida: se alcanzó el límite de los números de máquina.")
        try:
            fxr = funcion(xr)
        except ValueError as error:
            return resultado(anterior, "evaluacion", str(error))
        error = None if anterior is None else abs(xr - anterior)
        fila = {"i": i, "a": a, "b": b, "fa": fa, "fb": fb, "xr": xr, "fxr": fxr, "error_absoluto": error}
        filas.append(fila)
        if fxr == 0:
            sustituido = None
            a = b = xr
            fa = fb = fxr
        elif (fa < 0) == (fxr < 0):
            sustituido = "a"
            a, fa = xr, fxr
        else:
            sustituido = "b"
            b, fb = xr, fxr
        # Regla Falsa suele mover un solo extremo: se cuenta cuánto lleva quieto el otro.
        quieto = {"a": "b", "b": "a"}.get(sustituido)
        veces_fijo = 0 if quieto is None else veces_fijo + 1 if quieto == fijo else 1
        fijo = quieto
        medida = error if criterio == ABSOLUTO else medida_relativa(error, xr)
        cumple = medida is not None and medida <= tolerancia
        tolerancia_prueba = tolerancia
        if criterio != ABSOLUTO:
            # El extremo opuesto limita el radio incluso con tolerancias relativas grandes.
            tolerancia_prueba = min(b - a, Fraction(tolerancia) * abs(Fraction(xr)))
        prueba = f_prueba = None
        confirmada = False
        if cumple and fxr != 0:
            try:
                prueba, f_prueba, confirmada = confirmar_cercania(funcion, xr, fxr, a, b, tolerancia_prueba)
            except ValueError:
                # Sin una evaluación válida no se puede certificar la cercanía.
                pass
        fila.update({"sustituido": sustituido, "nuevo_a": a, "nuevo_b": b, "extremo_fijo": fijo,
                     "veces_fijo": veces_fijo, "cumple_tolerancia": cumple, "prueba": prueba,
                     "valor_criterio": medida, "tolerancia_prueba": float(tolerancia_prueba),
                     "f_prueba": f_prueba, "confirmada": confirmada})
        if fxr == 0:
            return resultado(xr, *motivo_cero(criterio, xr, "Raíz encontrada: f(xr) = 0 en aritmética de máquina."))
        if confirmada:
            return resultado(xr, "tolerancia", "Convergencia: el cambio seleccionado cumple la tolerancia y un cambio de signo confirma una raíz dentro del radio de prueba.")
        anterior = xr
    if criterio != ABSOLUTO and medida is None and len(filas) > 1:
        return resultado(xr, "criterio_indefinido", "El cambio relativo queda indefinido; revisa la escala o elige el criterio absoluto.")
    if cumple:
        return resultado(xr, "estancamiento", "No converge: el cambio cumple la tolerancia, pero ninguna raíz quedó confirmada dentro del radio de prueba. El método está estancado.")
    return resultado(xr, "limite", "No converge a la tolerancia pedida: se alcanzó el máximo de iteraciones.")
