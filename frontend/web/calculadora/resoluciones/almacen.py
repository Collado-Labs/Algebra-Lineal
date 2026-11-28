"""Almacén local de resoluciones y ejercicios en SQLite (biblioteca estándar).

Cada operación abre su propia conexión: Waitress atiende en varios hilos y dos ventanas
de la app pueden compartir el archivo; SQLite coordina los bloqueos entre procesos.

Errores, de menor a mayor gravedad:

- Bloqueo, permisos o disco (``AlmacenNoDisponible``): temporal. No se toca el archivo;
  la página lo explica y la próxima operación lo vuelve a intentar.
- Fila con un documento ilegible: se lista como «no se puede abrir» y puede eliminarse;
  el resto del cuaderno sigue intacto.
- Archivo dañado (SQLite informa SQLITE_CORRUPT o SQLITE_NOTADB, o ``quick_check`` falla):
  se aparta con otro nombre, nunca se borra, y se empieza un archivo nuevo.

Organización (versión 3 de la base): Proyecto → Sección (opcional) → Ejercicio → Referencias.
Una resolución es el documento histórico (inmutable salvo su nombre); una referencia la coloca en
un ejercicio con su propia posición e inclusión en el documento, así que una misma resolución
puede servir en varios ejercicios o proyectos sin copiarse. Sin referencias, queda «suelta».
Excluir algo del documento nunca lo borra. Quitar un proyecto, una sección o un ejercicio deja las
resoluciones en el cuaderno. Los proyectos abiertos y el ejercicio activo de cada uno viven en
``proyectos``; el destino de los nuevos cálculos, en ``ajustes``.
"""

import re
import sqlite3
import threading
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from . import contrato


VERSION_BASE = 3
MAX_DOCUMENTO = 4 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_NOMBRE = 120
# Códigos primarios de SQLite que significan un archivo dañado, no un problema de acceso.
_CORRUPCION = {11, 26}  # SQLITE_CORRUPT, SQLITE_NOTADB

_TABLAS = """
CREATE TABLE IF NOT EXISTS ejercicios (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    creado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resoluciones (
    id INTEGER PRIMARY KEY,
    huella TEXT NOT NULL UNIQUE,
    ruta TEXT NOT NULL,
    herramienta TEXT NOT NULL,
    nombre TEXT NOT NULL,
    ejercicio INTEGER REFERENCES ejercicios(id) ON DELETE SET NULL,
    creado TEXT NOT NULL,
    usado TEXT NOT NULL,
    documento TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS resoluciones_ejercicio ON resoluciones(ejercicio);
"""

# v1 → v2: proyectos, secciones, numeración, orden y selección para exportar. Solo añade.
_MIGRACION_2 = """
CREATE TABLE proyectos (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    objetivo INTEGER,
    creado TEXT NOT NULL
);
CREATE TABLE secciones (
    id INTEGER PRIMARY KEY,
    proyecto INTEGER NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
    titulo TEXT NOT NULL,
    posicion INTEGER NOT NULL DEFAULT 0,
    incluir INTEGER NOT NULL DEFAULT 1
);
ALTER TABLE ejercicios ADD COLUMN proyecto INTEGER REFERENCES proyectos(id) ON DELETE SET NULL;
ALTER TABLE ejercicios ADD COLUMN seccion INTEGER REFERENCES secciones(id) ON DELETE SET NULL;
ALTER TABLE ejercicios ADD COLUMN numero TEXT;
ALTER TABLE ejercicios ADD COLUMN enunciado TEXT;
ALTER TABLE ejercicios ADD COLUMN posicion INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ejercicios ADD COLUMN incluir INTEGER NOT NULL DEFAULT 1;
ALTER TABLE resoluciones ADD COLUMN posicion INTEGER NOT NULL DEFAULT 0;
ALTER TABLE resoluciones ADD COLUMN incluir INTEGER NOT NULL DEFAULT 1;
UPDATE ejercicios SET posicion = id;
UPDATE resoluciones SET posicion = id;
CREATE TABLE ajustes (clave TEXT PRIMARY KEY, valor TEXT NOT NULL);
CREATE INDEX ejercicios_proyecto ON ejercicios(proyecto, seccion, posicion);
CREATE INDEX secciones_proyecto ON secciones(proyecto, posicion);
"""
# v2 → v3: la organización sale de la tabla de resoluciones a «referencias» (una por ejercicio que
# usa la resolución); proyectos abiertos, ejercicio activo de cada uno y preferencia del borrador.
# La tabla se reconstruye (SQLite no quita columnas con REFERENCES) y la nueva se renombra después de
# borrar la antigua: nada apunta a la antigua, así que DROP TABLE no dispara borrados en cascada.
_MIGRACION_3 = """
CREATE TABLE resoluciones_v3 (
    id INTEGER PRIMARY KEY,
    huella TEXT NOT NULL UNIQUE,
    ruta TEXT NOT NULL,
    herramienta TEXT NOT NULL,
    nombre TEXT NOT NULL,
    creado TEXT NOT NULL,
    usado TEXT NOT NULL,
    documento TEXT NOT NULL
);
INSERT INTO resoluciones_v3 (id, huella, ruta, herramienta, nombre, creado, usado, documento)
    SELECT id, huella, ruta, herramienta, nombre, creado, usado, documento FROM resoluciones;
CREATE TABLE referencias (
    id INTEGER PRIMARY KEY,
    resolucion INTEGER NOT NULL REFERENCES resoluciones_v3(id) ON DELETE CASCADE,
    ejercicio INTEGER NOT NULL REFERENCES ejercicios(id) ON DELETE CASCADE,
    posicion INTEGER NOT NULL DEFAULT 0,
    incluir INTEGER NOT NULL DEFAULT 1,
    creado TEXT NOT NULL,
    UNIQUE (ejercicio, resolucion)
);
INSERT INTO referencias (resolucion, ejercicio, posicion, incluir, creado)
    SELECT id, ejercicio, posicion, incluir, usado FROM resoluciones
    WHERE ejercicio IN (SELECT id FROM ejercicios) ORDER BY ejercicio, posicion, id;
DROP TABLE resoluciones;
ALTER TABLE resoluciones_v3 RENAME TO resoluciones;
CREATE INDEX referencias_resolucion ON referencias(resolucion);
ALTER TABLE proyectos ADD COLUMN abierto TEXT;
ALTER TABLE proyectos ADD COLUMN ejercicio_activo INTEGER REFERENCES ejercicios(id) ON DELETE SET NULL;
ALTER TABLE proyectos ADD COLUMN solo_con_resolucion INTEGER NOT NULL DEFAULT 0;
UPDATE proyectos SET abierto = creado,
    ejercicio_activo = (SELECT e.id FROM ejercicios e JOIN ajustes a ON a.clave = 'activo_ejercicio'
                        WHERE e.proyecto = proyectos.id AND CAST(a.valor AS INTEGER) = e.id)
    WHERE id = (SELECT CAST(valor AS INTEGER) FROM ajustes WHERE clave = 'activo_proyecto');
DELETE FROM ajustes WHERE clave = 'activo_ejercicio';
"""
MIGRACIONES = {1: _TABLAS, 2: _MIGRACION_2, 3: _MIGRACION_3}
# Contenedor de cada elemento ordenable: se reordena solo entre sus hermanos.
_HERMANOS = {"ejercicios": ("proyecto", "seccion"), "referencias": ("ejercicio",), "secciones": ("proyecto",)}

# Estado legible sin decodificar documentos enteros: JSON válido, contrato y versión.
_ESTADO = f"""
    CASE
        WHEN NOT json_valid(documento) THEN 'danado'
        WHEN json_extract(documento, '$.contrato') IS NOT '{contrato.CONTRATO}' THEN 'danado'
        WHEN json_type(documento, '$.version') IS NOT 'integer' THEN 'danado'
        WHEN json_extract(documento, '$.version') > {contrato.VERSION} THEN 'futuro'
        ELSE 'ok'
    END
"""
_COLUMNAS = f"""
    id, ruta, herramienta, nombre, creado, usado, {_ESTADO} AS estado,
    CASE WHEN json_valid(documento) THEN json_extract(documento, '$.herramienta.esquema') END AS esquema,
    CASE WHEN json_valid(documento) THEN json_extract(documento, '$.resumen') END AS resumen
"""


class AlmacenNoDisponible(Exception):
    """Bloqueo, permisos o disco: los datos siguen a salvo, el acceso falló esta vez."""


class AlmacenFuturo(AlmacenNoDisponible):
    """Una versión más reciente de PyGebra cambió el archivo: esta no lo modifica."""


class Conflicto(ValueError):
    """La operación chocaría con la integridad del cuaderno (p. ej. un ejercicio que ya no existe)."""


class CuadernoLleno(Exception):
    """Guardar superaría el tamaño máximo del cuaderno o del documento."""


class _Corrupto(sqlite3.DatabaseError):
    pass


def _es_corrupcion(error):
    if isinstance(error, _Corrupto):
        return True
    codigo = getattr(error, "sqlite_errorcode", None)
    return codigo is not None and codigo & 0xFF in _CORRUPCION


def clave_numero(numero):
    """Orden natural de números de ejercicio: 2 < 10, 3a < 3b, 4.1 < 4.10; sin número, al final."""
    if not numero:
        return (1, ())
    return (0, tuple((0, int(parte), "") if parte.isdigit() else (1, 0, parte.casefold())
                     for parte in re.findall(r"\d+|\D+", numero)))


def ahora():
    """Fecha local con zona: la del ajuste TIME_ZONE de Django, como el resto de la app."""
    return timezone.localtime().isoformat(timespec="seconds")


class Almacen:
    def __init__(self, archivo, espera=5):
        self.archivo = Path(archivo)
        # Segundos que SQLite espera a que otra ventana suelte el archivo antes de rendirse.
        self.espera = espera
        # Archivo dañado que este proceso apartó; el cuaderno lo informa.
        self.apartado = None
        self._verificado = False
        self._candado = threading.Lock()

    # ---- Conexión y recuperación ----

    def _abrir(self):
        self.archivo.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.archivo, timeout=self.espera)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            with self._candado:
                if not self._verificado:
                    # Una vez por proceso: detecta un archivo dañado antes de escribir en él.
                    if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise _Corrupto("quick_check")
                    self._migrar(db)
                    self._verificado = True
        except BaseException:
            db.close()
            raise
        return db

    def _migrar(self, db):
        """Aplica las migraciones pendientes, cada una en su transacción, con respaldo previo."""
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > VERSION_BASE:
            raise AlmacenFuturo("El cuaderno lo creó una versión más reciente de PyGebra.")
        if 0 < version < VERSION_BASE:
            # Una copia íntegra antes de tocar un cuaderno con datos; se conserva la primera.
            respaldo = self.archivo.with_name(f"{self.archivo.stem}.v{version}-respaldo{self.archivo.suffix}")
            if not respaldo.exists():
                with closing(sqlite3.connect(respaldo)) as copia:
                    db.backup(copia)
        for numero in range(version + 1, VERSION_BASE + 1):
            # executescript confirma lo pendiente; el BEGIN propio hace atómica cada migración.
            db.executescript(f"BEGIN;\n{MIGRACIONES[numero]}\nPRAGMA user_version = {numero};\nCOMMIT;")

    def _apartar(self):
        """Renombra el archivo dañado (y sus diarios) para empezar uno nuevo sin perderlo."""
        marca = datetime.now().strftime("%Y%m%d-%H%M%S")
        destino = self.archivo.with_name(f"{self.archivo.stem}.apartado-{marca}{self.archivo.suffix}")
        try:
            self.archivo.replace(destino)
        except OSError:
            # Otro proceso lo tiene abierto (Windows) o no hay permiso: mejor no tocar nada.
            return False
        for sufijo in ("-wal", "-shm", "-journal"):
            diario = self.archivo.with_name(self.archivo.name + sufijo)
            try:
                diario.replace(destino.with_name(destino.name + sufijo))
            except FileNotFoundError:
                pass
            except OSError:
                pass  # El diario se queda; SQLite no lo usará con un archivo nuevo.
        self.apartado = destino
        self._verificado = False
        return True

    @contextmanager
    def conexion(self):
        """Transacción sobre el cuaderno; traduce los errores de SQLite a los de este módulo."""
        for intento in (1, 2):
            try:
                db = self._abrir()
                break
            except AlmacenNoDisponible:
                raise
            except sqlite3.DatabaseError as error:
                if intento == 1 and _es_corrupcion(error) and self._apartar():
                    continue
                raise AlmacenNoDisponible(str(error)) from error
            except OSError as error:
                raise AlmacenNoDisponible(str(error)) from error
        try:
            with closing(db), db:
                yield db
        except sqlite3.IntegrityError as error:
            # Una clave que ya no existe o una ubicación repetida: nada cambió (la transacción se revierte).
            raise Conflicto(str(error)) from error
        except sqlite3.DatabaseError as error:
            if _es_corrupcion(error):
                # Se confirma con quick_check en la próxima apertura antes de apartar nada.
                self._verificado = False
            raise AlmacenNoDisponible(str(error)) from error
        except OSError as error:
            raise AlmacenNoDisponible(str(error)) from error

    # ---- Resoluciones ----

    def guardar(self, *, huella, ruta, herramienta, nombre, documento):
        """(id, nueva). Una huella repetida no duplica ni sobrescribe: solo se marca como usada."""
        tamano = len(documento.encode("utf-8"))
        if tamano > MAX_DOCUMENTO:
            raise CuadernoLleno("Esta resolución es demasiado grande para guardarla.")
        momento = ahora()
        with self.conexion() as db:
            # Reserva la escritura antes de comprobar: otra ventana no puede colar la misma huella.
            db.execute("BEGIN IMMEDIATE")
            existente = db.execute("SELECT id FROM resoluciones WHERE huella = ?", (huella,)).fetchone()
            if existente:
                db.execute("UPDATE resoluciones SET usado = ? WHERE id = ?", (momento, existente["id"]))
                return existente["id"], False
            total = db.execute("SELECT COALESCE(SUM(length(CAST(documento AS BLOB))), 0) FROM resoluciones").fetchone()[0]
            if total + tamano > MAX_TOTAL:
                raise CuadernoLleno("El cuaderno está lleno: elimina resoluciones que ya no necesites.")
            cursor = db.execute(
                "INSERT INTO resoluciones (huella, ruta, herramienta, nombre, creado, usado, documento)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (huella, ruta, herramienta, nombre[:MAX_NOMBRE], momento, momento, documento),
            )
            return cursor.lastrowid, True

    def listar(self):
        with self.conexion() as db:
            return [dict(f) for f in db.execute(f"SELECT {_COLUMNAS} FROM resoluciones ORDER BY usado DESC, id DESC")]

    def obtener(self, identificador, documento=True):
        """(metadatos, texto del documento), solo los metadatos con documento=False, o None."""
        columnas = f"{_COLUMNAS}, documento" if documento else _COLUMNAS
        with self.conexion() as db:
            fila = db.execute(f"SELECT {columnas} FROM resoluciones WHERE id = ?", (identificador,)).fetchone()
        if fila is None:
            return None
        datos = dict(fila)
        return (datos, datos.pop("documento")) if documento else datos

    def renombrar(self, identificador, nombre):
        with self.conexion() as db:
            return db.execute("UPDATE resoluciones SET nombre = ? WHERE id = ?",
                              (nombre[:MAX_NOMBRE], identificador)).rowcount

    def eliminar(self, identificadores):
        with self.conexion() as db:
            return db.executemany("DELETE FROM resoluciones WHERE id = ?", [(i,) for i in identificadores]).rowcount

    # ---- Referencias: dónde se usa cada resolución ----

    def referencias(self, proyecto=..., resoluciones=None):
        """Referencias con los metadatos de su resolución (``id`` es la resolución; ``ref``, la
        referencia): todas, las de un proyecto (None: ejercicios independientes) o las de ciertas
        resoluciones. En el orden de cada ejercicio."""
        consulta = (f"SELECT f.id AS ref, f.ejercicio, f.posicion, f.incluir, r.* FROM referencias f "
                    f"JOIN (SELECT {_COLUMNAS} FROM resoluciones) r ON r.id = f.resolucion")
        parametros = ()
        if resoluciones is not None:
            consulta += f" WHERE f.resolucion IN ({','.join('?' * len(resoluciones))})"
            parametros = tuple(resoluciones)
        elif proyecto is not ...:
            consulta += " WHERE f.ejercicio IN (SELECT id FROM ejercicios WHERE proyecto IS ?)"
            parametros = (proyecto,)
        with self.conexion() as db:
            return [dict(f) for f in db.execute(f"{consulta} ORDER BY f.ejercicio, f.posicion, f.id", parametros)]

    def anadir(self, resoluciones, ejercicio):
        """Una referencia nueva al final del ejercicio por resolución; si ya estaba allí, no se repite."""
        momento = ahora()
        with self.conexion() as db:
            nuevas = 0
            for resolucion in resoluciones:
                nuevas += db.execute(
                    "INSERT OR IGNORE INTO referencias (resolucion, ejercicio, posicion, creado)"
                    " SELECT ?, ?, ?, ? WHERE EXISTS (SELECT 1 FROM resoluciones WHERE id = ?)",
                    (resolucion, ejercicio, self._siguiente(db, "referencias", {"ejercicio": ejercicio}), momento,
                     resolucion)).rowcount
            return nuevas

    def mover_referencias(self, referencias, ejercicio):
        """(movidas, unidas). Lleva cada referencia al final de otro ejercicio con su inclusión. Si
        allí ya estaba la misma resolución, se conserva esa y la movida se retira: nunca hay dos."""
        movidas = unidas = 0
        with self.conexion() as db:
            for referencia in referencias:
                fila = db.execute("SELECT resolucion, ejercicio FROM referencias WHERE id = ?", (referencia,)).fetchone()
                if fila is None or fila["ejercicio"] == ejercicio:
                    continue
                if db.execute("SELECT 1 FROM referencias WHERE ejercicio = ? AND resolucion = ?",
                              (ejercicio, fila["resolucion"])).fetchone():
                    db.execute("DELETE FROM referencias WHERE id = ?", (referencia,))
                    unidas += 1
                else:
                    db.execute("UPDATE referencias SET ejercicio = ?, posicion = ? WHERE id = ?",
                               (ejercicio, self._siguiente(db, "referencias", {"ejercicio": ejercicio}), referencia))
                    movidas += 1
        return movidas, unidas

    def desvincular(self, referencias):
        """Quita referencias; la resolución sigue en el cuaderno y en sus demás ubicaciones."""
        with self.conexion() as db:
            return db.executemany("DELETE FROM referencias WHERE id = ?", [(r,) for r in referencias]).rowcount

    # ---- Orden, selección y ajustes ----

    @staticmethod
    def _siguiente(db, tabla, contenedor):
        condicion = " AND ".join(f"{campo} IS ?" for campo in contenedor)
        return db.execute(f"SELECT COALESCE(MAX(posicion), 0) + 1 FROM {tabla} WHERE {condicion}",
                          tuple(contenedor.values())).fetchone()[0]

    @staticmethod
    def _renumerar(db, tabla, ids):
        db.executemany(f"UPDATE {tabla} SET posicion = ? WHERE id = ?", [(i, ident) for i, ident in enumerate(ids, 1)])

    def mover(self, tabla, identificador, desplazamiento):
        """Sube (−1) o baja (+1) un elemento entre sus hermanos; los demás conservan su orden relativo."""
        campos = _HERMANOS[tabla]
        with self.conexion() as db:
            fila = db.execute(f"SELECT {', '.join(campos)} FROM {tabla} WHERE id = ?", (identificador,)).fetchone()
            if fila is None:
                return False
            condicion = " AND ".join(f"{campo} IS ?" for campo in campos)
            ids = [f[0] for f in db.execute(f"SELECT id FROM {tabla} WHERE {condicion} ORDER BY posicion, id", tuple(fila))]
            actual = ids.index(identificador)
            destino = min(max(actual + desplazamiento, 0), len(ids) - 1)
            ids.insert(destino, ids.pop(actual))
            self._renumerar(db, tabla, ids)
            return destino != actual

    def colocar(self, tabla, identificador, *, antes=None, despues=None, posicion=None, **contenedor):
        """Coloca un elemento justo antes o después de otro (y en su contenedor), en una posición de
        su contenedor (1 = la primera) o al final de ``contenedor`` (p. ej. ``seccion=3``).

        Los demás conservan su orden relativo, también los que la página tenga ocultos por un
        filtro: «antes de X» significa antes de X en el orden completo. Los ejercicios no cambian
        de proyecto por aquí; una referencia sí puede pasar a otro ejercicio. False si no se movió.
        """
        campos = _HERMANOS[tabla]
        vecino = antes if antes is not None else despues
        with self.conexion() as db:
            fila = db.execute(f"SELECT {', '.join(campos)} FROM {tabla} WHERE id = ?", (identificador,)).fetchone()
            if fila is None or vecino == identificador:
                return False
            actual = dict(zip(campos, fila))
            destino = actual | {campo: valor for campo, valor in contenedor.items() if campo in campos}
            if vecino is not None:
                otra = db.execute(f"SELECT {', '.join(campos)} FROM {tabla} WHERE id = ?", (vecino,)).fetchone()
                if otra is None:
                    return False
                destino = dict(zip(campos, otra))
            if tabla != "referencias" and destino[campos[0]] != actual[campos[0]]:
                return False
            condicion = " AND ".join(f"{campo} IS ?" for campo in campos)
            ids = [f[0] for f in db.execute(f"SELECT id FROM {tabla} WHERE {condicion} AND id != ? ORDER BY posicion, id",
                                            (*destino.values(), identificador))]
            if vecino is not None:
                indice = ids.index(vecino) + (antes is None)
            elif posicion is not None:
                indice = min(max(posicion - 1, 0), len(ids))
            else:
                indice = len(ids)
            ids.insert(indice, identificador)
            if destino != actual:
                db.execute(f"UPDATE {tabla} SET {', '.join(f'{c} = ?' for c in campos)} WHERE id = ?",
                           (*destino.values(), identificador))
            self._renumerar(db, tabla, ids)
            return True

    def incluir(self, tabla, identificadores, valor):
        """Marca qué entra en el borrador del documento. Excluir nunca elimina."""
        if tabla not in _HERMANOS:
            raise ValueError(tabla)
        with self.conexion() as db:
            db.executemany(f"UPDATE {tabla} SET incluir = ? WHERE id = ?", [(int(bool(valor)), i) for i in identificadores])

    # ---- Proyectos abiertos y destino de los nuevos cálculos ----

    def activo(self):
        """(proyecto, ejercicio) que reciben los nuevos cálculos, o (None, None)."""
        with self.conexion() as db:
            fila = db.execute("""
                SELECT p.id, e.id FROM ajustes a JOIN proyectos p ON p.id = CAST(a.valor AS INTEGER)
                LEFT JOIN ejercicios e ON e.id = p.ejercicio_activo AND e.proyecto = p.id
                WHERE a.clave = 'activo_proyecto'""").fetchone()
        return (fila[0], fila[1]) if fila else (None, None)

    def trabajo_activo(self):
        """En una sola conexión (se pide en cada página): los proyectos abiertos, cada uno con su
        ejercicio activo y su progreso; el destino actual y sus ejercicios. None sin abiertos."""
        with self.conexion() as db:
            fila = db.execute("SELECT CAST(valor AS INTEGER) FROM ajustes WHERE clave = 'activo_proyecto'").fetchone()
            activo = fila and fila[0]
            abiertos = [dict(f) for f in db.execute("""
                SELECT p.id, p.nombre, p.objetivo, e.id AS ejercicio, e.numero, e.nombre AS titulo,
                       (SELECT COUNT(*) FROM ejercicios x WHERE x.proyecto = p.id) AS ejercicios,
                       (SELECT COUNT(DISTINCT f.ejercicio) FROM referencias f JOIN ejercicios x ON x.id = f.ejercicio
                        WHERE x.proyecto = p.id) AS resueltos
                FROM proyectos p LEFT JOIN ejercicios e ON e.id = p.ejercicio_activo AND e.proyecto = p.id
                WHERE p.abierto IS NOT NULL OR p.id IS ? ORDER BY p.abierto, p.id""", (activo,))]
            proyecto = next((p for p in abiertos if p["id"] == activo), None)
            ejercicios = [dict(f) for f in db.execute("""
                SELECT e.id, e.nombre, e.numero, e.proyecto, e.seccion FROM ejercicios e
                LEFT JOIN secciones s ON s.id = e.seccion
                WHERE e.proyecto = ? ORDER BY s.id IS NOT NULL, s.posicion, s.id, e.posicion, e.id""",
                (proyecto["id"],))] if proyecto else []
            cerrados = [dict(f) for f in db.execute(
                "SELECT id, nombre FROM proyectos WHERE abierto IS NULL AND id IS NOT ? ORDER BY nombre, id", (activo,))]
        if not abiertos:
            return None
        return {"abiertos": abiertos, "proyecto": proyecto, "ejercicios": ejercicios, "cerrados": cerrados}

    def activar(self, proyecto, ejercicio=...):
        """Abre el proyecto y lo hace destino de los nuevos cálculos. Con ``ejercicio`` cambia su
        ejercicio activo (None: ninguno); sin él, recupera el último en el que se trabajó."""
        with self.conexion() as db:
            if not db.execute("UPDATE proyectos SET abierto = COALESCE(abierto, ?) WHERE id = ?",
                              (ahora(), proyecto)).rowcount:
                return False
            if ejercicio is not ...:
                db.execute("UPDATE proyectos SET ejercicio_activo = (SELECT id FROM ejercicios WHERE id = ? AND proyecto = ?)"
                           " WHERE id = ?", (ejercicio, proyecto, proyecto))
            db.execute("INSERT OR REPLACE INTO ajustes (clave, valor) VALUES ('activo_proyecto', ?)", (str(proyecto),))
            return True

    def cerrar(self, proyecto):
        """Lo quita de los proyectos abiertos sin eliminar nada; si era el destino, ya no hay ninguno."""
        with self.conexion() as db:
            db.execute("UPDATE proyectos SET abierto = NULL WHERE id = ?", (proyecto,))
            db.execute("DELETE FROM ajustes WHERE clave = 'activo_proyecto' AND valor = ?", (str(proyecto),))

    # ---- Proyectos y secciones ----

    def proyectos(self):
        """Cada proyecto con sus ejercicios, cuántos tienen alguna resolución y su última actividad."""
        with self.conexion() as db:
            return [dict(f) for f in db.execute("""
                SELECT p.id, p.nombre, p.objetivo, p.creado, p.abierto, p.solo_con_resolucion,
                       COUNT(DISTINCT e.id) AS ejercicios,
                       COUNT(DISTINCT f.ejercicio) AS resueltos,
                       COALESCE(MAX(r.usado), p.creado) AS ultima
                FROM proyectos p
                LEFT JOIN ejercicios e ON e.proyecto = p.id
                LEFT JOIN referencias f ON f.ejercicio = e.id
                LEFT JOIN resoluciones r ON r.id = f.resolucion
                GROUP BY p.id ORDER BY ultima DESC, p.id DESC""")]

    def crear_proyecto(self, nombre, objetivo=None):
        with self.conexion() as db:
            return db.execute("INSERT INTO proyectos (nombre, objetivo, creado) VALUES (?, ?, ?)",
                              (nombre[:MAX_NOMBRE], objetivo, ahora())).lastrowid

    def editar_proyecto(self, identificador, nombre, objetivo):
        with self.conexion() as db:
            return db.execute("UPDATE proyectos SET nombre = ?, objetivo = ? WHERE id = ?",
                              (nombre[:MAX_NOMBRE], objetivo, identificador)).rowcount

    def preferir_documento(self, identificador, solo_con_resolucion):
        """El borrador lleva todos los ejercicios incluidos o solo los que tienen resoluciones incluidas."""
        with self.conexion() as db:
            db.execute("UPDATE proyectos SET solo_con_resolucion = ? WHERE id = ?",
                       (int(bool(solo_con_resolucion)), identificador))

    def eliminar_proyecto(self, identificador):
        """Quita el proyecto y sus secciones; sus ejercicios y resoluciones siguen en el cuaderno."""
        with self.conexion() as db:
            db.execute("UPDATE ejercicios SET proyecto = NULL, seccion = NULL WHERE proyecto = ?", (identificador,))
            db.execute("DELETE FROM ajustes WHERE clave = 'activo_proyecto' AND valor = ?", (str(identificador),))
            return db.execute("DELETE FROM proyectos WHERE id = ?", (identificador,)).rowcount

    def secciones(self, proyecto):
        with self.conexion() as db:
            return [dict(f) for f in db.execute(
                "SELECT id, proyecto, titulo, posicion, incluir FROM secciones WHERE proyecto = ? ORDER BY posicion, id",
                (proyecto,))]

    def crear_seccion(self, proyecto, titulo):
        with self.conexion() as db:
            return db.execute("INSERT INTO secciones (proyecto, titulo, posicion) VALUES (?, ?, ?)",
                              (proyecto, titulo[:MAX_NOMBRE], self._siguiente(db, "secciones", {"proyecto": proyecto}))).lastrowid

    def editar_seccion(self, identificador, titulo):
        with self.conexion() as db:
            return db.execute("UPDATE secciones SET titulo = ? WHERE id = ?", (titulo[:MAX_NOMBRE], identificador)).rowcount

    def eliminar_seccion(self, identificador):
        """Quita la sección; sus ejercicios pasan al final del proyecto, sin sección."""
        with self.conexion() as db:
            fila = db.execute("SELECT proyecto FROM secciones WHERE id = ?", (identificador,)).fetchone()
            if fila is None:
                return 0
            for (ejercicio,) in db.execute("SELECT id FROM ejercicios WHERE seccion = ? ORDER BY posicion, id",
                                           (identificador,)).fetchall():
                db.execute("UPDATE ejercicios SET seccion = NULL, posicion = ? WHERE id = ?",
                           (self._siguiente(db, "ejercicios", {"proyecto": fila[0], "seccion": None}), ejercicio))
            return db.execute("DELETE FROM secciones WHERE id = ?", (identificador,)).rowcount

    # ---- Ejercicios ----

    def ejercicios(self, proyecto=...):
        """Todos los ejercicios, o los de un proyecto (None: los independientes), en su orden."""
        consulta = "SELECT id, nombre, numero, enunciado, proyecto, seccion, posicion, incluir, creado FROM ejercicios"
        with self.conexion() as db:
            if proyecto is ...:
                filas = db.execute(f"{consulta} ORDER BY proyecto, posicion, id")
            else:
                filas = db.execute(f"{consulta} WHERE proyecto IS ? ORDER BY posicion, id", (proyecto,))
            return [dict(f) for f in filas]

    def crear_ejercicio(self, nombre, proyecto=None, seccion=None, numero=None, enunciado=None):
        with self.conexion() as db:
            posicion = self._siguiente(db, "ejercicios", {"proyecto": proyecto, "seccion": seccion})
            return db.execute(
                "INSERT INTO ejercicios (nombre, proyecto, seccion, numero, enunciado, posicion, creado)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (nombre[:MAX_NOMBRE], proyecto, seccion, numero, enunciado, posicion, ahora())).lastrowid

    def crear_ejercicios(self, proyecto, numeros, seccion=None):
        """Ejercicios vacíos numerados, preparados antes de resolverlos (p. ej. del 1 al 20)."""
        with self.conexion() as db:
            existentes = {f[0] for f in db.execute("SELECT numero FROM ejercicios WHERE proyecto = ?", (proyecto,))}
            nuevos = [n for n in dict.fromkeys(numeros) if n not in existentes]
            posicion = self._siguiente(db, "ejercicios", {"proyecto": proyecto, "seccion": seccion})
            momento = ahora()
            db.executemany(
                "INSERT INTO ejercicios (nombre, proyecto, seccion, numero, posicion, creado) VALUES ('', ?, ?, ?, ?, ?)",
                [(proyecto, seccion, numero, posicion + i, momento) for i, numero in enumerate(nuevos)])
            return len(nuevos)

    def editar_ejercicio(self, identificador, *, nombre, numero, enunciado):
        with self.conexion() as db:
            return db.execute("UPDATE ejercicios SET nombre = ?, numero = ?, enunciado = ? WHERE id = ?",
                              (nombre[:MAX_NOMBRE], numero, enunciado, identificador)).rowcount

    def ubicar_ejercicios(self, identificadores, proyecto, seccion=None):
        """Lleva ejercicios a un proyecto o sección (None: independientes), al final, en su orden
        actual y con sus referencias. Un proyecto que deja de contener su ejercicio activo lo olvida."""
        with self.conexion() as db:
            marcas = ",".join("?" * len(identificadores))
            ordenados = [f[0] for f in db.execute(
                f"SELECT id FROM ejercicios WHERE id IN ({marcas}) ORDER BY proyecto, seccion, posicion, id", identificadores)]
            for identificador in ordenados:
                db.execute("UPDATE ejercicios SET proyecto = ?, seccion = ?, posicion = ? WHERE id = ?",
                           (proyecto, seccion, self._siguiente(db, "ejercicios", {"proyecto": proyecto, "seccion": seccion}),
                            identificador))
            db.execute(f"UPDATE proyectos SET ejercicio_activo = NULL WHERE ejercicio_activo IN ({marcas}) AND id IS NOT ?",
                       (*identificadores, proyecto))
            return len(ordenados)

    def ordenar_por_numero(self, proyecto):
        """Reordena cada sección del proyecto por número natural; sin número, al final y en su orden."""
        with self.conexion() as db:
            filas = db.execute("SELECT id, seccion, numero FROM ejercicios WHERE proyecto = ? ORDER BY posicion, id",
                               (proyecto,)).fetchall()
            for seccion in {f["seccion"] for f in filas}:
                propias = [f for f in filas if f["seccion"] == seccion]
                self._renumerar(db, "ejercicios", [f["id"] for f in sorted(propias, key=lambda f: clave_numero(f["numero"]))])

    def existe_ejercicio(self, identificador):
        with self.conexion() as db:
            return db.execute("SELECT 1 FROM ejercicios WHERE id = ?", (identificador,)).fetchone() is not None

    def eliminar_ejercicios(self, identificadores):
        """Quita ejercicios (número, título y enunciado) y sus referencias. Las resoluciones siguen en
        el cuaderno: sueltas si no se usan en otro ejercicio."""
        with self.conexion() as db:
            return db.executemany("DELETE FROM ejercicios WHERE id = ?", [(i,) for i in identificadores]).rowcount


_ALMACENES = {}
_ALMACENES_CANDADO = threading.Lock()


def almacen():
    """El almacén del archivo configurado (ALGEBRA_RESOLUCIONES o la carpeta de PyGebra)."""
    ruta = str(settings.RESOLUCIONES_ARCHIVO)
    with _ALMACENES_CANDADO:
        if ruta not in _ALMACENES:
            _ALMACENES[ruta] = Almacen(ruta)
        return _ALMACENES[ruta]
