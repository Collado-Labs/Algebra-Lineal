"""MathML generado exclusivamente desde el árbol matemático validado."""
import ast
import re
from xml.etree.ElementTree import Element, tostring

_OPERADORES = {ast.Add: ("+", 1), ast.Sub: ("−", 1), ast.Mult: ("·", 2)}


def _elemento(etiqueta, *hijos, texto=None, **atributos):
    nodo = Element(etiqueta, atributos)
    nodo.text = texto
    nodo.extend(hijos)
    return nodo


def _simbolo(texto):
    return _elemento("mo", texto=texto)


def _parentesis(nodo):
    return _elemento("mrow", _simbolo("("), nodo, _simbolo(")"))


def _expresion(nodo, precedencia=0):
    if isinstance(nodo, ast.Constant):
        return _elemento("mn", texto=str(nodo.value))
    if isinstance(nodo, ast.Name):
        return _elemento("mi", texto="π" if nodo.id == "pi" else nodo.id)
    if isinstance(nodo, ast.Call):
        nombre = nodo.func.id
        argumento = _expresion(nodo.args[0])
        if nombre == "sqrt":
            return _elemento("msqrt", argumento)
        if nombre == "abs":
            return _elemento("mrow", _simbolo("|"), argumento, _simbolo("|"))
        nombre = {"sin": "sen"}.get(nombre, nombre)
        return _elemento("mrow", _elemento("mi", texto=nombre, mathvariant="normal"), _parentesis(argumento))
    if isinstance(nodo, ast.UnaryOp):
        signo = "−" if isinstance(nodo.op, ast.USub) else "+"
        fila = _elemento("mrow", _simbolo(signo), _expresion(nodo.operand, 3))
        return _parentesis(fila) if precedencia > 3 else fila
    if isinstance(nodo.op, ast.Div):
        return _elemento("mfrac", _expresion(nodo.left), _expresion(nodo.right))
    if isinstance(nodo.op, ast.Pow):
        potencia = _elemento("msup", _expresion(nodo.left, 5), _expresion(nodo.right))
        return _parentesis(potencia) if precedencia > 4 else potencia
    signo, nivel = _OPERADORES[type(nodo.op)]
    fila = _elemento("mrow", _expresion(nodo.left, nivel), _simbolo(signo), _expresion(nodo.right, nivel + 1))
    return _parentesis(fila) if precedencia > nivel else fila


def vista_matematica(funcion):
    arbol = funcion.arbol
    fx = _elemento("mrow", _elemento("mi", texto="f"), _parentesis(_elemento("mi", texto="x")), _simbolo("="))
    if len(funcion.miembros) == 2:
        partes = [fx, _parentesis(_expresion(arbol.left)), _simbolo("−"), _parentesis(_expresion(arbol.right))]
    else:
        partes = [fx, _expresion(arbol)]
    return {
        "mathml": tostring(_elemento("math", *partes, xmlns="http://www.w3.org/1998/Math/MathML"), encoding="unicode"),
        "aviso_notacion": "e(…) representa un producto. Para escribir una potencia usa e^(…)."
        if re.search(r"(?<!\w)e\s*\(", funcion.texto) else "",
    }
