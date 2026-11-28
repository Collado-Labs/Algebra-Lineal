"""Función, intervalo o puntos iniciales y ajustes que comparten los métodos de raíces."""

from django import forms
from backend.tolerancias import ABSOLUTO, PORCENTUAL, RELATIVO, leer_tolerancia
from backend.metodos_cerrados import MAX_ITERACIONES, TOLERANCIA, validar_tolerancia_raices
from backend.funciones_reales import FuncionReal
from .forms_feedback import FormularioConErrores


OPCIONES_CRITERIO = (
    (ABSOLUTO, "Cambio absoluto"),
    (RELATIVO, "Cambio relativo"),
    (PORCENTUAL, "Cambio relativo porcentual"),
)


def campo_criterio(opciones=OPCIONES_CRITERIO):
    return forms.ChoiceField(label="Criterio de parada", choices=opciones, initial=ABSOLUTO,
                             required=False, widget=forms.Select(attrs={"class": "field-input", "data-criterio-tolerancia": ""}))


class RaicesForm(FormularioConErrores):
    # Cada método nombra qué mide su tolerancia; el campo HTTP se llama igual en todos.
    magnitud, etiqueta = "tolerancia", "Tolerancia"

    def __init__(self, *args, explorar=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.explorar = explorar
        self.fields["precision"].label = self.etiqueta
        if explorar:
            self.fields["a"].required = self.fields["b"].required = False

    funcion = forms.CharField(label="Función o ecuación", max_length=512, strip=False,
                              widget=forms.TextInput(attrs={"class": "field-input", "spellcheck": "false",
                                                            "aria-describedby": "funcion-ayuda"}))
    a = forms.FloatField(label="Extremo a",
                         widget=forms.NumberInput(attrs={"class": "field-input", "step": "any"}))
    b = forms.FloatField(label="Extremo b",
                         widget=forms.NumberInput(attrs={"class": "field-input", "step": "any"}))
    precision = forms.CharField(initial=str(TOLERANCIA), required=False, max_length=210, strip=False,
                                widget=forms.TextInput(attrs={"class": "field-input", "data-tolerancia": "",
                                                               "aria-describedby": "precision-ayuda"}))
    criterio = campo_criterio()
    max_iteraciones = forms.IntegerField(label="Máximo de iteraciones", initial=MAX_ITERACIONES,
                                         min_value=1, max_value=1000, required=False,
                                         widget=forms.NumberInput(attrs={"class": "field-input"}))

    def clean_funcion(self):
        texto = self.cleaned_data["funcion"]
        try:
            self.funcion_real = FuncionReal(texto)
        except ValueError as error:
            raise forms.ValidationError(str(error)) from error
        return texto

    def clean(self):
        datos = super().clean()
        if self.explorar:
            for nombre, valor in (("a", -10.), ("b", 10.)):
                if datos.get(nombre) is None:
                    datos[nombre] = valor
        permitidos = {"csrfmiddlewaretoken", *self.fields}
        if set(self.data) - permitidos:
            self.add_error(None, "El envío incluye campos que no forman parte del formulario.")
        if hasattr(self.data, "getlist") and any(len(self.data.getlist(n)) > 1 for n in self.data):
            self.add_error(None, "Envía un único valor por campo; hay campos repetidos.")
        if "precision" in datos and "criterio" in datos:
            texto = datos["precision"]
            try:
                valor, criterio = leer_tolerancia(texto, datos["criterio"] or ABSOLUTO, predeterminada=TOLERANCIA)
                precision = validar_tolerancia_raices(valor, criterio, self.magnitud)
                datos.update(precision=precision, criterio=criterio, tolerancia_original=texto)
            except ValueError as error:
                self.add_error("precision", str(error))
        if datos.get("max_iteraciones") is None:
            datos["max_iteraciones"] = MAX_ITERACIONES
        if "a" in datos and "b" in datos and datos["a"] >= datos["b"]:
            self.add_error("b", "El extremo b debe ser mayor que a.")
        return datos


class BiseccionForm(RaicesForm):
    magnitud, etiqueta = "precisión", "Precisión del intervalo"
    criterio = campo_criterio(((ABSOLUTO, "Longitud del intervalo"),
                               (RELATIVO, "Cota del error relativo"),
                               (PORCENTUAL, "Cota del error relativo porcentual")))


class ReglaFalsaForm(RaicesForm):
    magnitud, etiqueta = "tolerancia", "Tolerancia"


class NewtonRaphsonForm(RaicesForm):
    a = b = None
    etiqueta = "Tolerancia"
    x0 = forms.FloatField(label="Aproximación inicial x₀",
        widget=forms.NumberInput(attrs={"class": "field-input", "step": "any"}))


class SecanteForm(NewtonRaphsonForm):
    x1 = forms.FloatField(label="Aproximación inicial x₁",
        widget=forms.NumberInput(attrs={"class": "field-input", "step": "any"}))

    def clean(self):
        datos = super().clean()
        # Sin orden ni cambio de signo: solo hacen falta dos puntos distintos para trazar la recta.
        if datos.get("x0") is not None and datos.get("x0") == datos.get("x1"):
            self.add_error("x1", "x₁ debe ser distinto de x₀: la secante necesita dos puntos.")
        return datos
