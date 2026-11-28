"""Pruebas independientes de los criterios y del contrato HTTP."""
from fractions import Fraction
import json
import math
import os
import re
import unittest

import django
from django.template.loader import render_to_string
from django.test import Client

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "frontend.web.algebra_web.settings")
django.setup()

from backend.biseccion import biseccion
from backend.funciones_reales import FuncionReal
from backend.newton_raphson import newton_raphson
from backend.regla_falsa import regla_falsa
from backend.secante import secante
from backend.sistemas_iterativos import resolver_iterativo
from backend.tolerancias import leer_tolerancia, medida_relativa


class ToleranciasTests(unittest.TestCase):
    def test_literal_y_unidades(self):
        for texto in ("0.01%", "0,01%", "0.01 %"):
            self.assertEqual(leer_tolerancia(texto, predeterminada=.0001), (Fraction(1, 10_000), "porcentual"))
        for texto in ("0.000001", "0,000001", "1e-6", "10^-6", "10⁻⁶", "10^(−6)"):
            self.assertEqual(leer_tolerancia(texto, predeterminada=.0001), (Fraction(1, 1_000_000), "absoluto"))
        self.assertEqual(leer_tolerancia(".01", "porcentual", predeterminada=.0001)[0], Fraction(1, 10_000))
        self.assertEqual(leer_tolerancia("1/1000000", predeterminada=.0001, admitir_fraccion=True)[0],
                         Fraction(1, 1_000_000))
        for texto in ("0", "-1%", "1e", "NaN", "Infinity", "10^x", "1e-400", "1e9999", "0.01%%", "1,2.3", "1/0"):
            with self.subTest(texto=texto), self.assertRaises(ValueError):
                leer_tolerancia(texto, predeterminada=.0001, admitir_fraccion=True)

    def test_biseccion_cota_verdadera_y_absoluto_por_defecto(self):
        f = FuncionReal("x² = 2")
        for criterio in ("relativo", "porcentual"):
            r = biseccion(f, 1, 2, 1e-6, criterio=criterio)
            self.assertTrue(r["convergio"])
            raiz = math.sqrt(2)
            self.assertLessEqual(abs(r["c"]-raiz)/raiz, r["valor_criterio"])
            self.assertLess(r["valor_criterio"], 1e-6)
        r = biseccion(f, 1, 2, 1e-6)
        self.assertEqual(r["estado"], "longitud")
        self.assertLess(r["longitud"], 1e-6)

    def test_regla_falsa_conserva_la_confirmacion(self):
        r = regla_falsa(FuncionReal("x² = 2"), 1, 2, 1e-6, criterio="porcentual")
        self.assertTrue(r["convergio"], r["mensaje"])
        paso, anterior = r["iteraciones"][-1], r["iteraciones"][-2]
        self.assertAlmostEqual(paso["valor_criterio"], abs(paso["xr"] - anterior["xr"]) / abs(paso["xr"]))
        self.assertLessEqual(abs(r["xr"] - math.sqrt(2)), r["cota"])
        self.assertLessEqual(abs(paso["prueba"] - paso["xr"]), paso["tolerancia_prueba"])
        sin_raiz = regla_falsa(FuncionReal("1/x"), -1, 1, criterio="porcentual")
        self.assertFalse(sin_raiz["convergio"])

    def test_newton_y_secante_usan_el_cambio_evaluado_y_residuo_independiente(self):
        metodos = ((newton_raphson, (1.5,)), (secante, (1., 2.)))
        for metodo, inicio in metodos:
            r = metodo(FuncionReal("x² = 2"), *inicio, 1e-6, criterio="porcentual")
            self.assertTrue(r["convergio"], r["mensaje"])
            self.assertAlmostEqual(r["x"], math.sqrt(2), places=9)
            self.assertLessEqual(r["valor_criterio"], 1e-6)
            self.assertLessEqual(r["residuo"], r["tolerancia_residuo"])
            self.assertEqual(r["tolerancia_residuo"], 1e-4)

    def test_cero_casi_cero_y_escala(self):
        for metodo, inicio in ((biseccion, (-1., 1.)), (regla_falsa, (-1., 1.)),
                               (newton_raphson, (1.,)), (secante, (-1., 1.))):
            for criterio in ("relativo", "porcentual"):
                r = metodo(FuncionReal("x"), *inicio, criterio=criterio)
                self.assertFalse(r["convergio"])
                self.assertEqual(r["estado"], "criterio_indefinido")
        self.assertIsNone(medida_relativa(0., 0.))
        self.assertIsNone(medida_relativa(1., 1e-320))
        self.assertIsNone(medida_relativa(1e308, 1e-200))
        self.assertAlmostEqual(medida_relativa(1e-40, 1e-30), 1e-10)
        r = biseccion(FuncionReal("x² − 2e-40"), 1e-20, 2e-20, 1e-6, criterio="relativo")
        self.assertTrue(r["convergio"], r["mensaje"])
        self.assertLess(abs(r["c"]/1e-20 - math.sqrt(2)), 2e-6)

    def test_normas_independientes_en_jacobi_y_gauss_seidel(self):
        for metodo in ("jacobi", "gauss_seidel"):
            r = resolver_iterativo([[4, 1], [1, 3]], [6, 7], metodo, criterio="porcentual",
                                   tolerancia=Fraction(1, 1_000_000))
            self.assertEqual(r.estado, "convergio")
            actual, anterior = r.final.x, r.iteraciones[-2].x
            esperado = max(abs(a-b) for a,b in zip(actual, anterior)) / max(map(abs, actual))
            self.assertAlmostEqual(r.final.valor_criterio, esperado)
            self.assertLess(r.final.valor_criterio, r.tolerancia)
            self.assertLess(r.final.norma_residuo, r.tolerancia_residuo)
            self.assertEqual(r.tolerancia_residuo, Fraction(1, 10_000))
            cero = resolver_iterativo([[2]], [0], metodo, criterio="relativo", max_iteraciones=3)
            self.assertEqual(cero.estado, "criterio_indefinido")
            self.assertIsNone(cero.final.valor_criterio)


class ToleranciasHttpTests(unittest.TestCase):
    @staticmethod
    def datos(respuesta, id_datos):
        patron = r'<script id="' + id_datos + r'" type="application/json">(.*?)</script>'
        return json.loads(re.search(patron, respuesta.content.decode(), re.S)[1])

    def test_ecuaciones_representativas_por_metodo_en_http(self):
        casos = (
            ("metodos-cerrados/biseccion", "ln(x)+sen(x)=1.2", {"a": "1", "b": "2"}, "c",
             lambda x: math.log(x)+math.sin(x)-1.2),
            ("metodos-cerrados/regla-falsa", "e^(x/2)+sen(2x)=3", {"a": "2.5", "b": "3"}, "xr",
             lambda x: math.exp(x/2)+math.sin(2*x)-3),
            ("metodos-abiertos/newton-raphson", "x²−3sen(x)−ln(x+2)=0", {"x0": "2"}, "x",
             lambda x: x*x-3*math.sin(x)-math.log(x+2)),
            ("metodos-abiertos/secante", "ln(x+3)+cos(x)=x/2", {"x0": "1.5", "x1": "3"}, "x",
             lambda x: math.log(x+3)+math.cos(x)-x/2),
        )
        for ruta, texto, inicio, clave, evaluar in casos:
            with self.subTest(ruta=ruta):
                respuesta = Client().post("/metodos-numericos/" + ruta + "/", {
                    **inicio, "funcion": texto, "precision": "0,0001%",
                })
                datos = self.datos(respuesta, "datos-raices")
                r = datos["resultado"]
                self.assertEqual(r["criterio"], "porcentual")
                self.assertEqual(datos["tolerancia_original"], "0,0001%")
                self.assertEqual(datos["funcion_original"], texto)
                self.assertEqual(r.get("precision", r.get("tolerancia")), 1e-6)
                self.assertTrue(r["convergio"], r)
                self.assertAlmostEqual(abs(evaluar(r[clave])), r["residuo"], places=13)
                self.assertIn("<math", respuesta.content.decode())
                self.assertIn("0.0001</span>%", respuesta.content.decode())
                self.assertEqual(FuncionReal(datos["funcion_normalizada"])(r[clave]), FuncionReal(texto)(r[clave]))

    def test_iterativos_contracto_y_presentacion(self):
        texto = "4x₁ + (1/2)x₂ = 5\nx₁ + 4.0x₂ = 9"
        respuesta = Client().post("/metodos-numericos/metodos-iterativos/", {
            "metodo": "comparar_iterativos", "tipo_entrada": "sistema", "sistema": texto,
            "tolerancia_iterativa": "0.01%",
        })
        datos = self.datos(respuesta, "datos-iterativos")
        self.assertEqual(datos["sistema_original"], texto)
        self.assertEqual(datos["tolerancia_original"], "0.01%")
        r = datos["resultado"]
        self.assertEqual(r["a_exacta"], [["4", "1/2"], ["1", "4"]])
        self.assertEqual(r["tolerancia"], .0001)
        self.assertTrue(all(m["convergio"] for m in r["metodos"]))
        self.assertIn("Cambio relativo porcentual", respuesta.content.decode())


    def test_las_resoluciones_historicas_conservan_la_lectura_absoluta(self):
        cliente = Client()
        respuesta = cliente.post("/metodos-numericos/metodos-abiertos/newton-raphson/", {
            "funcion": "x^2 - 2", "x0": "1.5", "precision": "0.00001",
        })
        contexto = respuesta.context_data
        for nuevo in ("criterio", "tolerancia_residuo", "valor_criterio"):
            contexto["resultado"].pop(nuevo)
        html = render_to_string(respuesta.template_name, contexto, request=respuesta.wsgi_request)
        self.assertIn("cambio y residuo ≤ tolerancia", html)
        self.assertIn("0.00001", html)

        respuesta = cliente.post("/metodos-numericos/metodos-iterativos/", {
            "metodo": "jacobi", "tipo_entrada": "sistema", "sistema": "4x1 + x2 = 5\nx1 + 4x2 = 9",
        })
        contexto = respuesta.context_data
        r = contexto["iterativos"]
        for nuevo in ("criterio", "magnitud", "tolerancia_visible", "tolerancia_residuo"):
            r.pop(nuevo)
        for fila in r["metodos"][0]["filas"]:
            fila.pop("medida_visible")
        html = render_to_string(respuesta.template_name, contexto, request=respuesta.wsgi_request)
        self.assertIn('data-criterio="absoluto"', html)
        self.assertIn('data-tolerancia="0.0001"', html)
        self.assertIn('data-tolerancia-residuo="0.0001"', html)
        self.assertIn('<td data-valor="2.25">', html)
