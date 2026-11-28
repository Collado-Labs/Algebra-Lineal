"""Regresiones de escritura académica con evaluaciones independientes."""
from fractions import Fraction
import math
import unittest

from backend.derivacion_real import DerivadaReal
from backend.funciones_reales import FuncionReal
from backend.parser_sistemas import analizar_sistema


class EntradaMatematicaTests(unittest.TestCase):
    def test_ecuaciones_y_formato_word(self):
        x = 2.5
        casos = (
            ("x³ − 4x − 9 = 0", x**3 - 4*x - 9),
            ("eˣ − 3x² = 0", math.exp(x) - 3*x*x),
            ("cos(x) − x·eˣ = 0", math.cos(x) - x*math.exp(x)),
            ("x·ln(x) − 1 = 0", x*math.log(x) - 1),
            ("e^(−x) + cos(x) = 0.5", math.exp(-x) + math.cos(x) - .5),
            ("ln(x)+sen(x)=1.2", math.log(x) + math.sin(x) - 1.2),
            ("e^(x/2) + sen(2x) = 3", math.exp(x/2) + math.sin(2*x) - 3),
            ("ln(x + 3) + cos(x) = x/2", math.log(x+3) + math.cos(x) - x/2),
            ("e^(1/x) + 2x / tan(x) = 2", math.exp(1/x) + 2*x/math.tan(x) - 2),
            ("ln(x + 1) ÷ (x² − 4) = −0.1", math.log(x+1)/(x*x-4) + .1),
            ("2^x = √(2x + 1)", 2**x - math.sqrt(2*x+1)),
        )
        for texto, esperado in casos:
            with self.subTest(texto=texto):
                f = FuncionReal(" " + texto + " ")
                self.assertEqual(f.original, " " + texto + " ")
                self.assertEqual(len(f.miembros), 2)
                self.assertAlmostEqual(f(x), esperado, places=13)
                self.assertEqual(FuncionReal(f.expresion).clave, f.clave)

    def test_derivada_y_dominio_de_ambos_miembros(self):
        f = FuncionReal("e^(1/x) = ln(x) − 2^x")
        self.assertAlmostEqual(DerivadaReal(f)(2), -math.exp(.5)/4 - .5 + 4*math.log(2))
        with self.assertRaises(ValueError):
            f(-1)
        with self.assertRaises(ValueError):
            f.rango(-1, 1)

    def test_igualdades_incompletas_o_ambiguas(self):
        for texto in ("x=", "=x", "x==2", "x=2 x=3", "sen(x=1)", "x)+(y=2", "senx"):
            with self.subTest(texto=texto), self.assertRaises(ValueError):
                FuncionReal(texto)

    def test_sistemas_con_fracciones_decimales_y_subindices(self):
        casos = (
            ("0.5x - 0.75y + 2z – (1)/(3)w = (181)/(60)", [Fraction(1,2), Fraction(-3,4), 2, Fraction(-1,3), Fraction(181,60)]),
            ("(1/2)x₂ + x₃ − x₄ = 3", [0, Fraction(1,2), 1, -1, 3]),
            ("−0.7x₁ + 2.2x₂ + 1.1x₄ = 2.6", [Fraction(-7,10), Fraction(11,5), 0, Fraction(11,10), Fraction(13,5)]),
            ("X1 − (1/2)x₂ + (1/4)x₃ + 2x₄ = 5", [1, Fraction(-1,2), Fraction(1,4), 2, 5]),
        )
        for texto, fila in casos:
            with self.subTest(texto=texto):
                matriz, reescritas = analizar_sistema(texto, limitar_entrada=True)
                self.assertEqual(matriz, [fila])
                if "y" in texto:
                    self.assertEqual(reescritas[0]["original"], texto)
        with self.assertRaisesRegex(ValueError, "sin mezclar"):
            analizar_sistema("x=1\nx₂=2", limitar_entrada=True)
        with self.assertRaisesRegex(ValueError, "denominador cero"):
            analizar_sistema("(1/0)x₂ = 2", limitar_entrada=True)
