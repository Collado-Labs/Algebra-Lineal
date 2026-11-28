"""Proyectos del cuaderno listos para mostrar: árbol, progreso, documento, selección y destino.

Solo lee el almacén (metadatos y resúmenes, nunca documentos enteros). La futura exportación a
PDF recorrerá ``documento(...)``, el mismo árbol que muestra el borrador, y leerá cada documento
por el id de su resolución.
"""

import re
from datetime import datetime

from .. import catalogo
from . import registro
from .almacen import AlmacenNoDisponible, almacen, clave_numero


MAX_SELECCION = 500
MAX_PREPARAR = 200


def fecha(texto):
    try:
        return datetime.fromisoformat(texto)
    except (TypeError, ValueError):
        return None


def etiqueta(ejercicio):
    """«Ejercicio 12 · Inversa de A», «Ejercicio 12» o el título solo."""
    numero, titulo = ejercicio.get("numero"), ejercicio.get("nombre") or ""
    if numero:
        return f"Ejercicio {numero} · {titulo}" if titulo else f"Ejercicio {numero}"
    return titulo or "Ejercicio sin título"


def corta(ejercicio):
    """Lo mínimo para un control estrecho: «Ej. 12» o el título."""
    return f"Ej. {ejercicio['numero']}" if ejercicio.get("numero") else (ejercicio.get("nombre") or "Ejercicio")


def preparar_resoluciones(filas):
    """Metadatos de cada resolución (o referencia) listos para la plantilla: fecha, herramienta, enlace y estado."""
    from .servicio import url_reabrir

    adaptadores = registro.ADAPTADORES
    for fila in filas:
        herramienta = catalogo.herramienta_por_id(fila["herramienta"])
        fila["fecha"] = fecha(fila["creado"])
        fila["herramienta_nombre"] = herramienta.nombre if herramienta else fila["herramienta"]
        fila["chip"] = herramienta.categoria.chip if herramienta else ""
        # El nombre por defecto ya empieza por la herramienta o su método: no se repite encima.
        fila["mostrar_herramienta"] = not fila["nombre"].startswith(fila["herramienta_nombre"])
        if fila["estado"] == "ok" and fila["ruta"] not in adaptadores:
            fila["estado"] = "sin_herramienta"
        elif fila["estado"] == "ok" and not adaptadores[fila["ruta"]].lee(fila["esquema"]):
            fila["estado"] = "antiguo"
        fila["url"] = url_reabrir(fila["ruta"], fila["id"]) if fila["estado"] in ("ok", "antiguo") else None
        # Id del renglón: una misma resolución puede aparecer en varios ejercicios de la página.
        fila["clave"] = f"ref-{fila['ref']}" if fila.get("ref") else f"resolucion-{fila['id']}"
    return filas


def arbol(proyecto, ejercicios, secciones, referencias, solo_incluidos=False):
    """Secciones (la primera, sin sección) con sus ejercicios y las referencias de cada uno, en orden.

    Con ``solo_incluidos`` es el documento: secciones, ejercicios y referencias incluidos; si el
    proyecto lo prefiere, solo los ejercicios que conservan alguna resolución incluida.
    """
    por_ejercicio = {}
    for fila in sorted(referencias, key=lambda r: (r["posicion"], r["ref"])):
        por_ejercicio.setdefault(fila["ejercicio"], []).append(fila)
    grupos = [{"seccion": None, "ejercicios": []}] + [{"seccion": s, "ejercicios": []} for s in secciones]
    indice = {s["id"]: grupo for s, grupo in zip(secciones, grupos[1:])}
    for ejercicio in ejercicios:
        propias = por_ejercicio.get(ejercicio["id"], [])
        incluidas = [r for r in propias if r["incluir"]]
        ejercicio = ejercicio | {
            "etiqueta": etiqueta(ejercicio), "corta": corta(ejercicio),
            "resoluciones": incluidas if solo_incluidos else propias,
            "resuelto": bool(propias), "incluidas": len(incluidas),
        }
        grupo = indice.get(ejercicio["seccion"], grupos[0])
        if solo_incluidos and not (ejercicio["incluir"] and (grupo["seccion"] is None or grupo["seccion"]["incluir"])
                                   and (incluidas or not proyecto.get("solo_con_resolucion"))):
            continue
        grupo["ejercicios"].append(ejercicio)
    secciones_visibles = grupos[1:]
    for posicion, grupo in enumerate(secciones_visibles):
        grupo["primera"], grupo["ultima"] = posicion == 0, posicion == len(secciones_visibles) - 1
    if solo_incluidos:
        return [g for g in grupos if g["ejercicios"]]
    return [g for g in grupos if g["seccion"] is not None or g["ejercicios"]]


def documento(proyecto, ejercicios, secciones, referencias):
    """Lo que el borrador muestra y el PDF exportará, en ese orden y con esa selección."""
    return arbol(proyecto, ejercicios, secciones, referencias, solo_incluidos=True)


def progreso(ejercicios, objetivo):
    """Ejercicios con alguna resolución sobre el total previsto (tener una no es estar completo)."""
    resueltos = sum(1 for e in ejercicios if e["resuelto"])
    total = max(objetivo or 0, len(ejercicios))
    return {"resueltos": resueltos, "total": total, "creados": len(ejercicios), "objetivo": objetivo,
            "porcentaje": round(100 * resueltos / total) if total else 0,
            "pendientes_por_crear": max((objetivo or 0) - len(ejercicios), 0)}


def borrador(grupos):
    """Las cifras del documento (el árbol de ``documento``)."""
    ejercicios = [e for g in grupos for e in g["ejercicios"]]
    return {"ejercicios": len(ejercicios), "resoluciones": sum(len(e["resoluciones"]) for e in ejercicios),
            "sin_resolver": sum(1 for e in ejercicios if not e["resoluciones"])}


def destinos(ejercicios, proyectos):
    """Ejercicios a los que añadir una resolución, agrupados: independientes y luego cada proyecto."""
    grupos = [("Ejercicios independientes", [e for e in ejercicios if e["proyecto"] is None])]
    grupos += [(p["nombre"], [e for e in ejercicios if e["proyecto"] == p["id"]]) for p in proyectos]
    for _, opciones in grupos:
        for ejercicio in opciones:
            ejercicio.setdefault("etiqueta", etiqueta(ejercicio))
    return [(nombre, opciones) for nombre, opciones in grupos if opciones]


def activo():
    """Proyectos abiertos (cada uno con su ejercicio activo) y el destino de los nuevos cálculos."""
    try:
        trabajo = almacen().trabajo_activo()
    except AlmacenNoDisponible:
        return None
    if trabajo is None:
        return None
    for abierto in trabajo["abiertos"]:
        recordado = {"numero": abierto["numero"], "nombre": abierto["titulo"]}
        abierto["corta"] = corta(recordado) if abierto["ejercicio"] else None
    for opcion in trabajo["ejercicios"]:
        opcion["etiqueta"], opcion["corta"] = etiqueta(opcion), corta(opcion)
    proyecto = trabajo["proyecto"]
    trabajo["ejercicio"] = proyecto and next((e for e in trabajo["ejercicios"] if e["id"] == proyecto["ejercicio"]), None)
    return trabajo


# ---- Selección por números y rangos ----

_GUIONES = re.compile(r"\s*[-‐‑‒–—−]\s*")
_SEPARADORES = re.compile(r"[\s,;]+")


def _tokens(texto):
    return [t for t in _SEPARADORES.split(_GUIONES.sub("-", texto.strip())) if t]


def _compacto(numeros):
    """[1, 2, 3, 5] → «1-3, 5»."""
    tramos, inicio = [], None
    for actual, siguiente in zip(numeros, [*numeros[1:], None]):
        inicio = actual if inicio is None else inicio
        if siguiente != actual + 1:
            tramos.append(str(inicio) if inicio == actual else f"{inicio}-{actual}")
            inicio = None
    return ", ".join(tramos)


def seleccionar(texto, ejercicios):
    """Ejercicios de un proyecto elegidos por número: «4», «3-22», «20-29, 35, 40-44».

    Un número es exacto (también «3a» o «4.1»); un rango incluye, en orden natural, los números
    entre sus extremos (3-22 incluye 3a, no 22a). Devuelve los ids en el orden del documento,
    los ``errores`` que impiden aplicar (número inexistente, rango inválido o invertido) y los
    ``avisos`` que no (huecos de un rango, números repetidos en el proyecto).
    """
    if len(texto) > MAX_SELECCION:
        return {"ids": [], "errores": ["La selección es demasiado larga."], "avisos": [], "cuenta": 0}
    errores, avisos, elegidos, por_numero = [], [], set(), {}
    for ejercicio in ejercicios:
        if ejercicio.get("numero"):
            por_numero.setdefault(ejercicio["numero"].casefold(), []).append(ejercicio)
    for token in _tokens(texto):
        exactos = por_numero.get(token.casefold())
        partes = token.split("-")
        if exactos:
            elegidos.update(e["id"] for e in exactos)
            if len(exactos) > 1:
                avisos.append(f"El número {token} está en {len(exactos)} ejercicios; se eligen todos.")
            if len(partes) == 2:
                avisos.append(f"«{token}» es el número de un ejercicio: se tomó como ese número, no como rango.")
            continue
        if len(partes) != 2 or not all(partes):
            errores.append(f"«{token}» no es un número de ejercicio ni un rango como 3-22."
                           if len(partes) > 1 else f"No hay ningún ejercicio {token} en este proyecto.")
            continue
        desde, hasta = clave_numero(partes[0]), clave_numero(partes[1])
        if desde > hasta:
            errores.append(f"El rango {token} está al revés: escribe {partes[1]}-{partes[0]}.")
            continue
        dentro = [e for numero, grupo in por_numero.items() for e in grupo if desde <= clave_numero(numero) <= hasta]
        if not dentro:
            errores.append(f"No hay ejercicios entre el {partes[0]} y el {partes[1]}.")
            continue
        elegidos.update(e["id"] for e in dentro)
        if partes[0].isdigit() and partes[1].isdigit() and int(partes[1]) - int(partes[0]) <= 1000:
            faltan = [n for n in range(int(partes[0]), int(partes[1]) + 1) if str(n) not in por_numero]
            if faltan:
                avisos.append(f"En {token} no existen: {_compacto(faltan)}.")
    ids = [e["id"] for e in ejercicios if e["id"] in elegidos]
    return {"ids": ids, "errores": errores, "avisos": avisos, "cuenta": len(ids)}


def numeros_para_preparar(texto):
    """(números, error) de «1-20» o «21-25, 26a, 30»: los rangos de enteros se desarrollan."""
    numeros = []
    for token in _tokens(texto):
        partes = token.split("-")
        if len(partes) == 2 and all(p.isdigit() for p in partes):
            desde, hasta = int(partes[0]), int(partes[1])
            if desde > hasta:
                return [], f"El rango {token} está al revés: escribe {hasta}-{desde}."
            if hasta - desde >= MAX_PREPARAR:
                return [], f"Prepara hasta {MAX_PREPARAR} ejercicios de una vez."
            numeros += [str(n) for n in range(desde, hasta + 1)]
        elif len(partes) == 1 and len(token) <= 20:
            numeros.append(token)
        else:
            return [], f"«{token}» no es un número ni un rango de enteros como 1-20."
        if len(numeros) > MAX_PREPARAR:
            return [], f"Prepara hasta {MAX_PREPARAR} ejercicios de una vez."
    if not numeros:
        return [], "Escribe los números que quieres preparar, como 1-20."
    return list(dict.fromkeys(numeros)), None
