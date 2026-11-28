"""Cuaderno de resoluciones: proyectos, ejercicios y resoluciones; buscar, ordenar y elegir qué exportar.

Solo lee metadatos y el resumen de cada documento; abrir una resolución es ir a su herramienta
con ?resolucion=<id> (el middleware la repone sin recalcular). Todo funciona con formularios;
resoluciones.js los envía sin recargar la página y conserva el desplazamiento, el foco, lo
desplegado y la selección; añade arrastrar para ordenar y la vista previa de los rangos.

Las acciones llegan por POST a cualquiera de las dos páginas y vuelven (PRG) a ``volver`` si es
una ruta local, o a la página que corresponda, con un mensaje breve en ``?hecho=``. Una
resolución puede estar en varios ejercicios: cada lugar es una *referencia* con su orden y su
inclusión en el documento; desvincular quita un lugar, eliminar quita la resolución de todos.
"""

from collections import OrderedDict
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from django.http import Http404, HttpResponseRedirect, JsonResponse, QueryDict
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_http_methods

from . import catalogo
from .resoluciones import organizacion
from .resoluciones.almacen import MAX_NOMBRE, AlmacenFuturo, AlmacenNoDisponible, Conflicto, almacen
from .resoluciones.servicio import NO_DISPONIBLE, url_reabrir


FILTROS = ("q", "herramienta", "desde", "hasta")
VISTAS = (("todos", "Todos"), ("sin", "Sin resolución"), ("con", "Con resolución"))
MAX_ENUNCIADO = 2000
# Herramientas desde las que empezar cuando el cuaderno está en blanco: una por área.
SUGERIDAS = ("determinantes", "matriz-inversa", "metodos-cerrados", "relaciones-conjuntos")
# Acciones por lote sobre ejercicios de un proyecto (elegidos por número o marcados).
LOTE = {
    "seccion": "Mover a una sección", "proyecto": "Mover a otro proyecto",
    "independiente": "Quitar del proyecto", "incluir": "Incluir en el documento",
    "excluir": "Excluir del documento", "eliminar": "Eliminar ejercicios",
}
HECHOS = {
    "anadidas": "Añadiste {n} a «{ejercicio}».",
    "ya_estaban": "«{ejercicio}» ya tenía {n}; no se repite.",
    "movida": "Moviste la resolución a «{ejercicio}».",
    "unida": "«{ejercicio}» ya tenía esa resolución: quedó una sola.",
    "desvinculada": "Quitaste la resolución de este ejercicio; sigue en el cuaderno.",
    "eliminadas": "Eliminaste {n} del cuaderno.",
    "renombrada": "Cambiaste el nombre de la resolución.",
    "ejercicio_editado": "Guardaste los cambios del ejercicio.",
    "proyecto_creado": "Creaste el proyecto. Los nuevos cálculos podrán añadirse a él.",
    "proyecto_editado": "Guardaste los cambios del proyecto.",
    "proyecto_eliminado": "Eliminaste el proyecto; sus ejercicios y resoluciones siguen en el cuaderno.",
    "activado": "Ahora trabajas en «{ejercicio}».",
    "cerrado": "Cerraste «{ejercicio}»; sigue en tu cuaderno.",
    "ejercicio_creado": "Creaste «{ejercicio}».",
    "ejercicios_creados": "Creaste {e}.",
    "ningun_ejercicio_nuevo": "Esos números ya existían; no se creó ninguno.",
    "ordenados": "Ordenaste los ejercicios por número.",
    "seccion_creada": "Creaste la sección «{ejercicio}».",
    "seccion_eliminada": "Quitaste la sección; sus ejercicios siguen en el proyecto.",
    "documento": "El borrador lleva {e}.",
    "lote_seccion": "Moviste {e} a «{ejercicio}».",
    "lote_sin_seccion": "Moviste {e} fuera de las secciones.",
    "lote_proyecto": "Moviste {e} a «{ejercicio}».",
    "lote_independiente": "Quitaste {e} del proyecto; siguen en el cuaderno como independientes.",
    "lote_incluir": "Incluiste {e} en el documento.",
    "lote_excluir": "Dejaste {e} fuera del documento; no se borró nada.",
    "lote_eliminar": "Eliminaste {e}; sus resoluciones siguen en el cuaderno.",
    "sin_cambios": "No había nada que cambiar.",
    "sin_seleccion": "Primero marca al menos una resolución.",
    "sin_nombre": "Escribe un nombre de al menos un carácter.",
    "conflicto": "No se pudo: alguno de esos elementos ya no existe o ya estaba allí. No cambió nada.",
    "motivo": "{e}",
}


def _dia(texto):
    try:
        return date.fromisoformat(texto) if texto else None
    except ValueError:
        return None


def _rotulo_dia(dia, hoy):
    if dia == hoy:
        return "Hoy"
    if dia == hoy - timedelta(days=1):
        return "Ayer"
    return None


def _entero(valor, minimo=None):
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return None
    return numero if minimo is None or numero >= minimo else None


def _texto(valor, maximo=MAX_NOMBRE):
    return " ".join((valor or "").split())[:maximo]


def _cantidad(n):
    return "1 resolución" if n == 1 else f"{n} resoluciones"


def _ejercicios(n):
    return "1 ejercicio" if n == 1 else f"{n} ejercicios"


# ---- Filtros y búsqueda ----

def _filtros(datos):
    return {clave: datos.get(clave, "").strip()[:MAX_NOMBRE] for clave in FILTROS}


def _coincide(fila, consulta, contexto):
    if not consulta:
        return True
    textos = (fila["nombre"], fila.get("resumen") or "", fila["herramienta_nombre"], *contexto)
    return all(any(termino in catalogo.normalizar(texto) for texto in textos) for termino in consulta)


def _filtrar(filas, filtros, contexto_de):
    consulta = catalogo.normalizar(filtros["q"]).split()
    desde, hasta = _dia(filtros["desde"]), _dia(filtros["hasta"])
    for fila in filas:
        dia = fila["fecha"].date() if fila["fecha"] else None
        if filtros["herramienta"] and fila["herramienta"] != filtros["herramienta"]:
            continue
        if (desde and (dia is None or dia < desde)) or (hasta and (dia is None or dia > hasta)):
            continue
        if _coincide(fila, consulta, contexto_de(fila)):
            yield fila


# ---- Páginas ----

def _cuaderno(filtros):
    """Proyectos, ejercicios independientes y resoluciones sueltas; con filtros, la lista de coincidencias."""
    cuaderno = almacen()
    filas = organizacion.preparar_resoluciones(cuaderno.listar())
    referencias = organizacion.preparar_resoluciones(cuaderno.referencias())
    ejercicios = cuaderno.ejercicios()
    proyectos = cuaderno.proyectos()
    nombres_proyecto = {p["id"]: p["nombre"] for p in proyectos}
    por_id = {e["id"]: e for e in ejercicios}
    for ejercicio in ejercicios:
        ejercicio["etiqueta"] = organizacion.etiqueta(ejercicio)
        ejercicio["proyecto_nombre"] = nombres_proyecto.get(ejercicio["proyecto"])
    lugares = {}
    for referencia in referencias:
        ejercicio = por_id[referencia["ejercicio"]]
        lugares.setdefault(referencia["id"], []).append(
            f"{ejercicio['proyecto_nombre']} › {ejercicio['etiqueta']}" if ejercicio["proyecto_nombre"] else ejercicio["etiqueta"])
    for fila in filas:
        fila["lugares"] = lugares.get(fila["id"], [])
        fila["ubicacion"] = " · ".join(fila["lugares"])

    activo = any(filtros.values())
    contexto = {"total": len(filas), "filtrando": activo, "apartado": cuaderno.apartado,
                "herramientas": sorted({(f["herramienta"], f["herramienta_nombre"]) for f in filas}, key=lambda h: h[1]),
                "destinos": organizacion.destinos(ejercicios, proyectos), "proyectos": proyectos,
                "total_ejercicios": len(ejercicios)}
    if activo:
        coincidencias = list(_filtrar(filas, filtros, lambda fila: fila["lugares"]))
        consulta = catalogo.normalizar(filtros["q"]).split()
        return contexto | {"coincidencias": coincidencias, "visibles": len(coincidencias), "proyectos": [
            p for p in proyectos if consulta and all(t in catalogo.normalizar(p["nombre"]) for t in consulta)]}

    pasos = {}
    for referencia in sorted(referencias, key=lambda r: (r["posicion"], r["ref"])):
        pasos.setdefault(referencia["ejercicio"], []).append(referencia | {"otras": len(lugares[referencia["id"]]) - 1})
    independientes = []
    for ejercicio in ejercicios:
        if ejercicio["proyecto"] is None:
            propias = pasos.get(ejercicio["id"], [])
            fechas = [f["fecha"] for f in propias if f["fecha"]]
            independientes.append(ejercicio | {"pasos": propias, "total": len(propias),
                                               "ultima": max(fechas) if fechas else organizacion.fecha(ejercicio["creado"])})
    independientes.sort(key=lambda h: h["ultima"] or datetime.min.replace(tzinfo=timezone.get_current_timezone()),
                        reverse=True)
    hoy = timezone.localdate()
    dias = OrderedDict()
    for fila in filas:
        if not fila["lugares"]:
            dias.setdefault(fila["fecha"].date() if fila["fecha"] else None, []).append(fila)
    activo_id, _ = cuaderno.activo()
    for proyecto in proyectos:
        proyecto["progreso"] = organizacion.progreso(
            [{"resuelto": i < proyecto["resueltos"]} for i in range(proyecto["ejercicios"])], proyecto["objetivo"])
        proyecto["activo"] = proyecto["id"] == activo_id
        proyecto["fecha"] = organizacion.fecha(proyecto["ultima"])
    return contexto | {
        "ejercicios": independientes, "visibles": len(filas),
        "sueltas": [{"dia": d, "rotulo": _rotulo_dia(d, hoy), "resoluciones": g} for d, g in dias.items()],
    }


MENSAJE = ("hecho", "n", "ejercicio", "e")


def _base(request, filtros):
    # Volver aquí tras una acción, sin repetir el mensaje de la anterior.
    consulta = request.GET.copy()
    for clave in MENSAJE:
        consulta.pop(clave, None)
    volver = f"{request.path}?{consulta.urlencode()}" if consulta else request.path
    return {"filtros": filtros, "consulta_filtros": urlencode({k: v for k, v in filtros.items() if v}),
            "hecho": _hecho(request.GET), "max_nombre": MAX_NOMBRE, "pagina_resoluciones": True,
            "volver": volver, "pagina": request.path}


@require_http_methods(["GET", "POST"])
def resoluciones(request):
    # Los filtros viajan en la URL; en un POST, en un campo oculto con la consulta de la página.
    filtros = _filtros(request.GET if request.method == "GET" else QueryDict(request.POST.get("filtros", "")))
    contexto = _base(request, filtros) | {
        "sugeridas": [h for h in map(catalogo.herramienta_por_id, SUGERIDAS) if h and h.disponible],
        "migas": (catalogo.Miga("Inicio", reverse("calculadora:inicio")), catalogo.Miga("Resoluciones", actual=True)),
    }
    return _responder(request, contexto, "calculadora/pages/resoluciones.html", lambda: _cuaderno(filtros))


def _datos_proyecto(cuaderno, identificador):
    proyecto = next((p for p in cuaderno.proyectos() if p["id"] == identificador), None)
    if proyecto is None:
        raise Http404("No existe ese proyecto.")
    return proyecto, cuaderno.ejercicios(identificador), cuaderno.secciones(identificador)


def _en_orden(proyecto, ejercicios, secciones):
    """Los ejercicios del proyecto en el orden del documento (secciones incluidas)."""
    return [e for g in organizacion.arbol(proyecto, ejercicios, secciones, []) for e in g["ejercicios"]]


def _proyecto(identificador, vista):
    cuaderno = almacen()
    proyecto, ejercicios, secciones = _datos_proyecto(cuaderno, identificador)
    referencias = organizacion.preparar_resoluciones(cuaderno.referencias(proyecto=identificador))
    # Cuántos otros lugares usan cada resolución: reutilizarla nunca la copia.
    usos = {}
    for r in cuaderno.referencias(resoluciones=sorted({r["id"] for r in referencias})) if referencias else ():
        usos[r["id"]] = usos.get(r["id"], 0) + 1
    for r in referencias:
        r["otras"] = usos.get(r["id"], 1) - 1
    grupos = organizacion.arbol(proyecto, ejercicios, secciones, referencias)
    todos = [e for g in grupos for e in g["ejercicios"]]
    activo_proyecto, activo_ejercicio = cuaderno.activo()
    progreso = organizacion.progreso(todos, proyecto["objetivo"])
    documento = organizacion.documento(proyecto, ejercicios, secciones, referencias)
    en_documento = {e["id"] for g in documento for e in g["ejercicios"]}
    # El mapa sigue el orden del documento; las casillas que faltan hasta el objetivo, al final.
    mapa = [{"id": e["id"], "corta": e["numero"] or "·", "etiqueta": e["etiqueta"], "incluir": e["id"] in en_documento,
             "estado": "resuelto" if e["resuelto"] else "pendiente"} for e in todos]
    for grupo in grupos:
        for posicion, ejercicio in enumerate(grupo["ejercicios"], 1):
            ejercicio["posicion_seccion"], ejercicio["en_documento"] = posicion, ejercicio["id"] in en_documento
            ejercicio["hermanos"] = len(grupo["ejercicios"])
        if vista != "todos":
            grupo["ejercicios"] = [e for e in grupo["ejercicios"] if e["resuelto"] == (vista == "con")]
    proyectos = cuaderno.proyectos()
    return {
        "proyecto": proyecto | {"activo": activo_proyecto == identificador}, "grupos": grupos,
        "secciones": secciones, "progreso": progreso, "mapa": mapa, "vista": vista,
        "huecos": range(progreso["pendientes_por_crear"]), "vistas": VISTAS, "operaciones": LOTE,
        "borrador": organizacion.borrador(documento), "indice": documento,
        "ejercicio_activo": activo_ejercicio if activo_proyecto == identificador else None,
        "ejercicios_proyecto": todos, "proyectos": proyectos, "total": len(referencias),
        "otros_proyectos": [p for p in proyectos if p["id"] != identificador],
        "destinos": organizacion.destinos(cuaderno.ejercicios(), proyectos),
        "visibles": sum(1 for g in grupos for _ in g["ejercicios"]),
    }


@require_http_methods(["GET", "POST"])
def proyecto(request, identificador):
    vista = request.GET.get("ver") if request.GET.get("ver") in dict(VISTAS) else "todos"
    contexto = _base(request, _filtros({})) | {"vista": vista, "preparar_en": _entero(request.GET.get("preparar"))}
    respuesta = _responder(request, contexto, "calculadora/pages/proyecto.html", lambda: _proyecto(identificador, vista))
    if isinstance(respuesta, TemplateResponse) and "proyecto" in respuesta.context_data:
        nombre = respuesta.context_data["proyecto"]["nombre"]
        respuesta.context_data["migas"] = (
            catalogo.Miga("Inicio", reverse("calculadora:inicio")),
            catalogo.Miga("Resoluciones", reverse("calculadora:resoluciones")), catalogo.Miga(nombre, actual=True))
    return respuesta


@require_GET
def seleccion(request, identificador):
    """Vista previa de una selección por números (la usa resoluciones.js mientras se escribe)."""
    try:
        cuaderno = almacen()
        orden = _en_orden(*_datos_proyecto(cuaderno, identificador))
    except AlmacenNoDisponible:
        return JsonResponse({"error": NO_DISPONIBLE}, status=503)
    resultado = organizacion.seleccionar(request.GET.get("numeros", ""), orden)
    por_id = {e["id"]: e for e in orden}
    return JsonResponse(resultado | {"etiquetas": [por_id[i]["corta"] for i in resultado["ids"]]})


def _responder(request, contexto, plantilla, cargar):
    try:
        if request.method == "POST":
            resultado = _accion(request)
            if not isinstance(resultado, dict):
                return resultado
            contexto.update(resultado)
        contexto.update(cargar())
    except AlmacenNoDisponible as error:
        contexto["no_disponible"] = str(error) if isinstance(error, AlmacenFuturo) else NO_DISPONIBLE
    return TemplateResponse(request, plantilla, contexto, status=503 if "no_disponible" in contexto else 200)


# ---- Acciones ----

def _destino(request, por_defecto, **hecho):
    """Vuelve a la página de origen si es local; si no, a la que corresponda. Con el mensaje en ?hecho=."""
    volver = request.POST.get("volver", "")
    seguro = volver.startswith("/") and not volver.startswith("//") and url_has_allowed_host_and_scheme(
        volver, allowed_hosts={request.get_host()})
    destino, _, ancla = (volver if seguro else por_defecto).partition("#")
    if hecho:
        consulta = QueryDict(destino.partition("?")[2], mutable=True)
        for clave in MENSAJE:
            consulta.pop(clave, None)
        consulta.update({clave: str(valor) for clave, valor in hecho.items()})
        destino = f"{destino.partition('?')[0]}?{consulta.urlencode()}"
    return HttpResponseRedirect(f"{destino}#{ancla}" if ancla else destino)


def _cuaderno_url(filtros):
    consulta = urlencode({k: v for k, v in filtros.items() if v})
    destino = reverse("calculadora:resoluciones")
    return f"{destino}?{consulta}" if consulta else destino


def _proyecto_url(identificador, ancla=""):
    return reverse("calculadora:proyecto", args=[identificador]) + (f"#{ancla}" if ancla else "")


def _ids(datos, campo="ids"):
    return [i for i in (_entero(v) for v in datos.getlist(campo)) if i is not None]


def _ejercicio_destino(cuaderno, datos):
    """Ejercicio elegido o uno nuevo (en el proyecto indicado, si lo hay), con su número y título."""
    proyecto = _entero(datos.get("proyecto"))
    numero = _texto(datos.get("numero_destino"), 20)
    if numero and proyecto is not None:
        # «Ejercicio Nº 21» dentro del proyecto: el número que se ve, no un id.
        encontrado = next((e["id"] for e in cuaderno.ejercicios(proyecto) if (e["numero"] or "").casefold() == numero.casefold()), None)
        if encontrado is None:
            raise Conflicto(f"No hay un ejercicio {numero} en este proyecto.")
        return encontrado
    destino = _entero(datos.get("ejercicio"))
    if destino is not None and cuaderno.existe_ejercicio(destino):
        return destino
    numero = _texto(datos.get("numero"), 20) or None
    nombre = _texto(datos.get("nombre_ejercicio"))
    if not nombre and not numero:
        nombre = f"Ejercicio {len(cuaderno.ejercicios(proyecto if proyecto else None)) + 1}"
    return cuaderno.crear_ejercicio(nombre, proyecto=proyecto, numero=numero)


def _nombre_de(cuaderno, ejercicio):
    return next((organizacion.etiqueta(e) for e in cuaderno.ejercicios() if e["id"] == ejercicio), "")


def _accion(request):
    """Aplica la acción del POST; devuelve la respuesta o el contexto de una confirmación."""
    try:
        return _aplicar(request)
    except Conflicto as error:
        motivo = str(error) if str(error).startswith("No hay") else ""
        return _destino(request, reverse("calculadora:resoluciones"), **(
            {"hecho": "motivo", "e": motivo} if motivo else {"hecho": "conflicto"}))


def _aplicar(request):
    cuaderno, datos = almacen(), request.POST
    filtros = _filtros(QueryDict(datos.get("filtros", "")))
    # «accion:proyecto» deja que un botón lleve su proyecto (cambiar a otro abierto o cerrarlo).
    accion, _, objetivo = datos.get("accion", "").partition(":")
    ids, identificador = _ids(datos), _entero(datos.get("id"))
    proyecto = _entero(objetivo) if objetivo else _entero(datos.get("proyecto"))
    volver_cuaderno = _cuaderno_url(filtros)
    # Botones compactos de una sola acción: op = «mover:tabla:id:±1» o «incluir:tabla:id:0|1».
    if datos.get("op"):
        partes = datos["op"].split(":")
        if len(partes) == 4 and partes[0] in ("mover", "incluir") and _entero(partes[2]) is not None:
            tabla, objetivo, valor = partes[1], int(partes[2]), _entero(partes[3])
            if tabla in ("ejercicios", "referencias", "secciones") and valor is not None:
                if partes[0] == "mover":
                    cuaderno.mover(tabla, objetivo, -1 if valor < 0 else 1)
                else:
                    cuaderno.incluir(tabla, [objetivo], valor)
        return _destino(request, volver_cuaderno)

    # Resoluciones: añadir a un ejercicio (otra referencia, sin copiar nada) o eliminar del todo.
    if accion in ("anadir", "eliminar", "eliminar_confirmado") and not ids:
        return _destino(request, volver_cuaderno, hecho="sin_seleccion")
    if accion == "anadir":
        destino = _ejercicio_destino(cuaderno, datos)
        nuevas = cuaderno.anadir(ids, destino)
        if datos.get("volver_a") == "herramienta" and len(ids) == 1:
            ficha = cuaderno.obtener(ids[0], documento=False)
            enlace = ficha and url_reabrir(ficha["ruta"], ficha["id"])
            if enlace:
                ruta, _, ancla = enlace.partition("#")
                return HttpResponseRedirect(f"{ruta}&tras=anadida&en={destino}#{ancla}")
        return _destino(request, volver_cuaderno, hecho="anadidas" if nuevas else "ya_estaban",
                        n=nuevas or len(ids), ejercicio=_nombre_de(cuaderno, destino))
    if accion == "eliminar":
        # Primero se confirma: eliminar no se puede deshacer y quita la resolución de todos sus lugares.
        elegidas = [f for f in cuaderno.listar() if f["id"] in ids]
        lugares = {}
        nombres = {p["id"]: p["nombre"] for p in cuaderno.proyectos()}
        por_id = {e["id"]: e for e in cuaderno.ejercicios()}
        for r in cuaderno.referencias(resoluciones=ids):
            e = por_id[r["ejercicio"]]
            lugares.setdefault(r["id"], []).append(
                f"{nombres[e['proyecto']]} › {organizacion.etiqueta(e)}" if e["proyecto"] else organizacion.etiqueta(e))
        return {"confirmar": [f | {"lugares": lugares.get(f["id"], [])} for f in elegidas]}
    if accion == "eliminar_confirmado":
        cuaderno.eliminar(ids)
        return _destino(request, volver_cuaderno, hecho="eliminadas", n=len(ids))

    # Referencias: cada lugar donde se usa una resolución.
    referencias = _ids(datos, "ref")
    if accion == "mover_referencia" and referencias:
        destino = _ejercicio_destino(cuaderno, datos)
        _, unidas = cuaderno.mover_referencias(referencias, destino)
        return _destino(request, volver_cuaderno, hecho="unida" if unidas else "movida", ejercicio=_nombre_de(cuaderno, destino))
    if accion == "desvincular" and referencias:
        cuaderno.desvincular(referencias)
        return _destino(request, volver_cuaderno, hecho="desvinculada")
    if accion == "colocar":
        return _colocar(request, cuaderno, datos, volver_cuaderno)

    nombre = _texto(datos.get("nombre"))
    if accion == "renombrar" and identificador is not None:
        if not nombre:
            return _destino(request, volver_cuaderno, hecho="sin_nombre")
        cuaderno.renombrar(identificador, nombre)
        return _destino(request, volver_cuaderno, hecho="renombrada")
    marcados = _ids(datos, "sel")
    if accion == "eliminar_ejercicios" and marcados:
        return {"confirmar_ejercicios": [e | {"etiqueta": organizacion.etiqueta(e)} for e in cuaderno.ejercicios() if e["id"] in marcados]}
    if accion == "eliminar_ejercicios_confirmado" and marcados:
        cuaderno.eliminar_ejercicios(marcados)
        return _destino(request, volver_cuaderno, hecho="lote_eliminar", e=_ejercicios(len(marcados)))
    if accion == "editar_ejercicio" and identificador is not None:
        return _editar_ejercicio(request, cuaderno, datos, identificador, nombre, volver_cuaderno)

    # Proyectos
    if accion == "crear_proyecto":
        if not nombre:
            return _destino(request, volver_cuaderno, hecho="sin_nombre")
        nuevo = cuaderno.crear_proyecto(nombre, _entero(datos.get("objetivo"), 1))
        cuaderno.activar(nuevo)
        return HttpResponseRedirect(_proyecto_url(nuevo) + "?hecho=proyecto_creado")
    if accion == "editar_proyecto" and proyecto is not None:
        if not nombre:
            return _destino(request, _proyecto_url(proyecto), hecho="sin_nombre")
        cuaderno.editar_proyecto(proyecto, nombre, _entero(datos.get("objetivo"), 1))
        return _destino(request, _proyecto_url(proyecto), hecho="proyecto_editado")
    if accion == "eliminar_proyecto" and proyecto is not None:
        return {"confirmar_proyecto": next((p for p in cuaderno.proyectos() if p["id"] == proyecto), None)}
    if accion == "eliminar_proyecto_confirmado" and proyecto is not None:
        cuaderno.eliminar_proyecto(proyecto)
        return HttpResponseRedirect(reverse("calculadora:resoluciones") + "?hecho=proyecto_eliminado")
    if accion == "activar" and proyecto is not None:
        # Sin «ejercicio» en el POST se recupera el último en el que se trabajó en ese proyecto.
        ejercicio = _entero(datos.get("ejercicio")) if "ejercicio" in datos else ...
        if not cuaderno.activar(proyecto, ejercicio):
            return _destino(request, volver_cuaderno, hecho="conflicto")
        _, actual = cuaderno.activo()
        etiqueta = _nombre_de(cuaderno, actual) if actual else next(
            (p["nombre"] for p in cuaderno.proyectos() if p["id"] == proyecto), "")
        return _destino(request, _proyecto_url(proyecto), hecho="activado", ejercicio=etiqueta)
    if accion == "cerrar" and proyecto is not None:
        cuaderno.cerrar(proyecto)
        nombre_proyecto = next((p["nombre"] for p in cuaderno.proyectos() if p["id"] == proyecto), "")
        return _destino(request, volver_cuaderno, hecho="cerrado", ejercicio=nombre_proyecto)
    if accion == "preferir_documento" and proyecto is not None:
        solo = datos.get("contenido") == "con_resolucion"
        cuaderno.preferir_documento(proyecto, solo)
        return _destino(request, _proyecto_url(proyecto), hecho="documento",
                        e="solo los ejercicios con resoluciones incluidas" if solo else "todos los ejercicios incluidos")

    # Ejercicios y secciones de un proyecto
    if accion == "crear_ejercicio":
        numero = _texto(datos.get("numero"), 20) or None
        if not nombre and not numero:
            return _destino(request, _proyecto_url(proyecto) if proyecto else volver_cuaderno, hecho="sin_nombre")
        enunciado = (datos.get("enunciado") or "").strip()[:MAX_ENUNCIADO] or None
        seccion = _seccion_valida(cuaderno, proyecto, datos.get("seccion"))
        nuevo = cuaderno.crear_ejercicio(nombre, proyecto=proyecto, seccion=seccion, numero=numero, enunciado=enunciado)
        if proyecto is not None and datos.get("activar"):
            cuaderno.activar(proyecto, nuevo)
        etiqueta = organizacion.etiqueta({"numero": numero, "nombre": nombre})
        return _destino(request, _proyecto_url(proyecto, f"ejercicio-{nuevo}") if proyecto else volver_cuaderno,
                        hecho="ejercicio_creado", ejercicio=etiqueta)
    if accion == "crear_ejercicios" and proyecto is not None:
        numeros, error = organizacion.numeros_para_preparar(datos.get("numeros", ""))
        if error:
            return _destino(request, _proyecto_url(proyecto), hecho="motivo", e=error)
        seccion = _seccion_elegida(cuaderno, proyecto, datos)
        creados = cuaderno.crear_ejercicios(proyecto, numeros, seccion)
        if not creados:
            return _destino(request, _proyecto_url(proyecto), hecho="ningun_ejercicio_nuevo")
        return _destino(request, _proyecto_url(proyecto, f"seccion-{seccion}" if seccion else ""),
                        hecho="ejercicios_creados", e=_ejercicios(creados))
    if accion == "lote" and proyecto is not None:
        return _lote(request, cuaderno, datos, proyecto)
    if accion == "ordenar" and proyecto is not None:
        cuaderno.ordenar_por_numero(proyecto)
        return _destino(request, _proyecto_url(proyecto), hecho="ordenados")
    if accion == "crear_seccion" and proyecto is not None:
        if not nombre:
            return _destino(request, _proyecto_url(proyecto), hecho="sin_nombre")
        nueva = cuaderno.crear_seccion(proyecto, nombre)
        return _destino(request, _proyecto_url(proyecto, f"seccion-{nueva}"), hecho="seccion_creada", ejercicio=nombre)
    if accion == "editar_seccion" and identificador is not None and nombre:
        cuaderno.editar_seccion(identificador, nombre)
        return _destino(request, volver_cuaderno)
    if accion == "eliminar_seccion" and identificador is not None:
        cuaderno.eliminar_seccion(identificador)
        return _destino(request, volver_cuaderno, hecho="seccion_eliminada")
    return _destino(request, volver_cuaderno)


def _seccion_valida(cuaderno, proyecto, valor):
    """Una sección del proyecto, o None (sin sección) si no lo es."""
    seccion = _entero(valor)
    if proyecto is None or seccion is None:
        return None
    return seccion if any(s["id"] == seccion for s in cuaderno.secciones(proyecto)) else None


def _seccion_elegida(cuaderno, proyecto, datos):
    """La sección elegida en un formulario, o una nueva si se escribió su título («nueva»)."""
    if datos.get("seccion") == "nueva":
        titulo = _texto(datos.get("nueva_seccion"))
        return cuaderno.crear_seccion(proyecto, titulo) if titulo else None
    return _seccion_valida(cuaderno, proyecto, datos.get("seccion"))


def _editar_ejercicio(request, cuaderno, datos, identificador, nombre, volver):
    numero = _texto(datos.get("numero"), 20) or None
    if not nombre and not numero:
        return _destino(request, volver, hecho="sin_nombre")
    anterior = next((e for e in cuaderno.ejercicios() if e["id"] == identificador), None)
    if anterior is None:
        return _destino(request, volver, hecho="conflicto")
    enunciado = (datos.get("enunciado") or "").strip()[:MAX_ENUNCIADO] or None
    cuaderno.editar_ejercicio(identificador, nombre=nombre, numero=numero if "numero" in datos else anterior["numero"],
                              enunciado=enunciado if "enunciado" in datos else anterior["enunciado"])
    if datos.get("ubicacion"):
        _ubicar(cuaderno, identificador, datos["ubicacion"], anterior)
    posicion = _entero(datos.get("posicion"), 1)
    if posicion is not None and posicion != _entero(datos.get("posicion_actual")):
        cuaderno.colocar("ejercicios", identificador, posicion=posicion)
    return _destino(request, volver, hecho="ejercicio_editado")


def _ubicar(cuaderno, ejercicio, ubicacion, anterior):
    """«s:<id>» sección del proyecto, «s:» sin sección, «p:<id>» otro proyecto, «independiente»."""
    tipo, _, valor = ubicacion.partition(":")
    if tipo == "independiente":
        if anterior["proyecto"] is not None:
            cuaderno.ubicar_ejercicios([ejercicio], None)
    elif tipo == "s" and anterior["proyecto"] is not None:
        seccion = _seccion_valida(cuaderno, anterior["proyecto"], valor)
        if seccion != anterior["seccion"]:
            cuaderno.ubicar_ejercicios([ejercicio], anterior["proyecto"], seccion)
    elif tipo == "p" and _entero(valor) is not None and _entero(valor) != anterior["proyecto"]:
        if any(p["id"] == int(valor) for p in cuaderno.proyectos()):
            cuaderno.ubicar_ejercicios([ejercicio], int(valor))


def _colocar(request, cuaderno, datos, volver):
    """Arrastrar o mover con el teclado: «antes» o «después» de un hermano, o al final de una sección."""
    tabla, objetivo = datos.get("tabla"), _entero(datos.get("id"))
    if tabla not in ("ejercicios", "secciones", "referencias") or objetivo is None:
        return _destino(request, volver)
    opciones = {"antes": _entero(datos.get("antes")), "despues": _entero(datos.get("despues"))}
    if tabla == "ejercicios" and opciones["antes"] is None and opciones["despues"] is None and "seccion" in datos:
        ejercicio = next((e for e in cuaderno.ejercicios() if e["id"] == objetivo), None)
        if ejercicio is None or ejercicio["proyecto"] is None:
            return _destino(request, volver)
        opciones["seccion"] = _seccion_valida(cuaderno, ejercicio["proyecto"], datos.get("seccion"))
    cuaderno.colocar(tabla, objetivo, **opciones)
    return _destino(request, volver)


def _lote(request, cuaderno, datos, proyecto):
    """Una acción sobre los ejercicios elegidos por número («3-22, 35») o marcados en la lista.

    Sin ``confirmado`` (o con errores en los números, o para eliminar) devuelve la vista previa
    para confirmarla: qué ejercicios y cuántos. Nunca ignora un número que no entiende.
    """
    datos_proyecto, ejercicios, secciones = _datos_proyecto(cuaderno, proyecto)
    orden = _en_orden(datos_proyecto, ejercicios, secciones)
    texto = (datos.get("numeros") or "").strip()
    eleccion = organizacion.seleccionar(texto, orden)
    marcados = set(_ids(datos, "sel")) & {e["id"] for e in orden}
    ids = [e["id"] for e in orden if e["id"] in marcados or e["id"] in eleccion["ids"]]
    operacion = datos.get("operacion")
    destino = datos.get(f"destino_{operacion}", "")
    vista = {"texto": texto, "marcados": sorted(marcados), "operacion": operacion, "destino": destino,
             "nueva_seccion": _texto(datos.get("nueva_seccion")), "errores": list(eleccion["errores"]),
             "avisos": eleccion["avisos"], "elegidos": [e for e in orden if e["id"] in ids],
             "rotulo": LOTE.get(operacion, "")}
    if operacion not in LOTE:
        vista["errores"].append("Elige qué hacer con los ejercicios.")
    elif not ids and not vista["errores"]:
        vista["errores"].append("Escribe números como 3-22 o marca ejercicios en la lista.")
    seccion = proyecto_destino = None
    if operacion == "seccion":
        if destino == "nueva" and not vista["nueva_seccion"]:
            vista["errores"].append("Escribe el título de la sección nueva.")
        elif destino not in ("", "nueva") and _seccion_valida(cuaderno, proyecto, destino) is None:
            vista["errores"].append("Esa sección ya no existe.")
        vista["destino_nombre"] = (vista["nueva_seccion"] if destino == "nueva"
                                   else next((s["titulo"] for s in secciones if str(s["id"]) == destino), None))
    if operacion == "proyecto":
        proyecto_destino = next((p for p in cuaderno.proyectos() if str(p["id"]) == destino and p["id"] != proyecto), None)
        if proyecto_destino is None:
            vista["errores"].append("Elige el proyecto al que moverlos.")
        vista["destino_nombre"] = proyecto_destino and proyecto_destino["nombre"]
    if vista["errores"] or datos.get("confirmado") != "1" or operacion == "eliminar" and datos.get("confirmado_eliminar") != "1":
        return {"lote": vista}

    cantidad = _ejercicios(len(ids))
    if operacion == "seccion":
        seccion = _seccion_elegida(cuaderno, proyecto, {"seccion": destino, "nueva_seccion": datos.get("nueva_seccion")})
        cambian = [e["id"] for e in orden if e["id"] in ids and e["seccion"] != seccion]
        if cambian:
            cuaderno.ubicar_ejercicios(cambian, proyecto, seccion)
        titulo = next((s["titulo"] for s in cuaderno.secciones(proyecto) if s["id"] == seccion), "")
        return _destino(request, _proyecto_url(proyecto), hecho="lote_seccion" if seccion else "lote_sin_seccion",
                        e=_ejercicios(len(cambian)), ejercicio=titulo)
    if operacion == "proyecto":
        cuaderno.ubicar_ejercicios(ids, proyecto_destino["id"])
        return _destino(request, _proyecto_url(proyecto), hecho="lote_proyecto", e=cantidad, ejercicio=proyecto_destino["nombre"])
    if operacion == "independiente":
        cuaderno.ubicar_ejercicios(ids, None)
    elif operacion in ("incluir", "excluir"):
        cuaderno.incluir("ejercicios", ids, operacion == "incluir")
    elif operacion == "eliminar":
        cuaderno.eliminar_ejercicios(ids)
    return _destino(request, _proyecto_url(proyecto), hecho=f"lote_{operacion}", e=cantidad)


def _hecho(datos):
    plantilla = HECHOS.get(datos.get("hecho", ""))
    if plantilla is None:
        return None
    n = _entero(datos.get("n")) or 0
    return plantilla.format(n=_cantidad(n), ejercicio=datos.get("ejercicio", "")[:MAX_NOMBRE],
                            e=datos.get("e", "")[:160])
