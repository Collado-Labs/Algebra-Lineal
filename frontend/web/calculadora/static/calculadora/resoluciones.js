/* Cuaderno de resoluciones. Solo mejora lo que ya funciona sin JavaScript:
   - en una herramienta, coloca el aviso del cuaderno bajo el encabezado del resultado;
   - en el menú de proyectos abiertos, busca ejercicios por número o título;
   - en el cuaderno, envía las acciones sin recargar y conserva desplazamiento, foco, lo
     desplegado y la selección; confirma en un diálogo; cuenta lo marcado; Organizar muestra
     qué ejercicios elige un rango mientras se escribe; Mayús + clic marca un tramo; las asas
     ordenan arrastrando (con desplazamiento automático) o con ↑ ↓ Inicio Fin. */
(() => {
    "use strict";

    const aviso = document.getElementById("resolucion-aviso");
    const encabezado = document.querySelector("[data-resultado] .results-heading");
    if (aviso && encabezado) encabezado.after(aviso);

    const normalizar = texto => texto.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();

    // ---- Menú de proyectos abiertos: buscar ejercicio ----
    function iniciarMenu(raiz) {
        const menu = raiz.querySelector("[data-proyecto-activo]");
        const buscar = menu?.querySelector("[data-buscar-ejercicio]");
        if (!buscar) return;
        const campo = buscar.querySelector("input");
        const opciones = [...menu.querySelectorAll("[data-lista-ejercicios] button")];
        const vacio = menu.querySelector("[data-sin-coincidencias]");
        buscar.hidden = opciones.length < 8;
        campo.addEventListener("input", () => {
            const consulta = normalizar(campo.value);
            const numero = /^\d+[a-z]?$/.test(consulta) ? new RegExp(`(^|[^\\d])${consulta}([^\\d]|$)`) : null;
            let visibles = 0;
            opciones.forEach(opcion => {
                const texto = normalizar(opcion.dataset.texto || opcion.textContent);
                const coincide = !consulta || (numero ? numero.test(texto) : consulta.split(/\s+/).every(t => texto.includes(t)));
                opcion.parentElement.hidden = !coincide;
                visibles += coincide;
            });
            vacio.hidden = visibles > 0;
        });
        campo.addEventListener("keydown", evento => {
            if (evento.key !== "Enter") return;
            evento.preventDefault();
            opciones.find(o => !o.parentElement.hidden)?.click();
        });
        menu.addEventListener("toggle", () => {
            if (!menu.open) return;
            menu.querySelector('[data-lista-ejercicios] [aria-current="true"]')?.scrollIntoView({ block: "nearest" });
            if (!buscar.hidden) campo.focus({ preventScroll: true });
        });
    }
    if (!document.body.hasAttribute("data-cuaderno")) {
        iniciarMenu(document);
        return;
    }
    const principal = document.getElementById("contenido");
    const anuncio = Object.assign(document.createElement("p"), { className: "cuaderno-anuncio", role: "status" });
    anuncio.setAttribute("aria-live", "polite");
    document.body.append(anuncio);

    // ---- Envío sin recarga con restauración del contexto ----
    const MENUS = "details.menu-panel, details.proyecto-activo, details.resolucion-agrupar";
    let ocupado = false;
    let pendiente = null;  // Contexto de la acción que abrió un diálogo de confirmación.

    function claveDetalles(detalles) {
        if (detalles.id) return detalles.id;
        const dueno = detalles.parentElement.closest("[id]");
        const hermanos = [...dueno.querySelectorAll("details")].filter(d => d.parentElement.closest("[id]") === dueno);
        return `${dueno.id}|${hermanos.indexOf(detalles)}`;
    }

    function buscarDetalles(clave) {
        if (!clave.includes("|")) return document.getElementById(clave);
        const [id, indice] = clave.split("|");
        const dueno = document.getElementById(id);
        return dueno && [...dueno.querySelectorAll("details")].filter(d => d.parentElement.closest("[id]") === dueno)[indice];
    }

    function capturar(origen, limpiar) {
        const ancla = origen?.closest?.("[data-orden], .proyecto-grupo[id], [id].hoja, [id].hoja-entrada, [id].proyecto-panel, [id]");
        const lote = principal.querySelector("[data-lote]");
        return {
            ancla: ancla?.id, alto: ancla?.getBoundingClientRect().top, desplazamiento: scrollY,
            // El menú desde el que se actuó se cierra; lo demás desplegado sigue igual.
            abiertos: [...principal.querySelectorAll("details[open]")].filter(d => !(d.matches(MENUS) && d.contains(origen))).map(claveDetalles),
            cerrado: origen?.closest?.(MENUS) ? claveDetalles(origen.closest(MENUS)) : null,
            foco: (document.activeElement?.closest("[data-clave]") || origen?.closest?.("[data-clave]"))?.dataset.clave,
            marcados: limpiar ? [] : [...principal.querySelectorAll("[data-marca-ejercicio]:checked, input[name=ids]:checked")].map(m => `${m.name}=${m.value}`),
            numeros: limpiar ? "" : lote?.elements.numeros.value,
        };
    }

    function restaurar(estado) {
        estado.abiertos.forEach(clave => { const d = buscarDetalles(clave); if (d) d.open = true; });
        principal.querySelectorAll("[data-marca-ejercicio], input[name=ids]").forEach(m => {
            m.checked = estado.marcados.includes(`${m.name}=${m.value}`);
        });
        const lote = principal.querySelector("[data-lote]");
        if (lote && estado.numeros !== undefined && !lote.querySelector("[data-confirmacion]")) lote.elements.numeros.value = estado.numeros;
        const ancla = estado.ancla && document.getElementById(estado.ancla);
        if (ancla && estado.alto !== undefined) scrollBy(0, ancla.getBoundingClientRect().top - estado.alto);
        else scrollTo(0, estado.desplazamiento);
        const foco = (estado.foco && principal.querySelector(`[data-clave="${CSS.escape(estado.foco)}"]`))
            || (estado.cerrado && buscarDetalles(estado.cerrado)?.querySelector("summary"));
        foco?.focus({ preventScroll: true });
    }

    function anunciar(texto) {
        if (!texto) return;
        anuncio.textContent = texto;
        anuncio.toggleAttribute("data-visible", true);
        clearTimeout(anunciar.temporizador);
        anunciar.temporizador = setTimeout(() => anuncio.removeAttribute("data-visible"), 4500);
    }

    async function enviar(form, boton, extra = {}, limpiar = false) {
        if (ocupado) return;
        const datos = new FormData(form, boton || undefined);
        Object.entries(extra).forEach(([clave, valor]) => datos.set(clave, valor));
        const estado = pendiente || capturar(boton || form, limpiar);
        ocupado = true;
        principal.setAttribute("aria-busy", "true");
        try {
            const respuesta = await fetch(form.action, { method: "POST", body: datos, credentials: "same-origin" });
            const destino = new URL(respuesta.url);
            if (destino.pathname !== location.pathname) { location.assign(respuesta.url); return; }
            const documento = new DOMParser().parseFromString(await respuesta.text(), "text/html");
            const nuevo = documento.getElementById("contenido");
            if (!nuevo) throw new Error("respuesta sin contenido");
            document.querySelector("dialog.cuaderno-dialogo")?.remove();
            principal.replaceChildren(...nuevo.childNodes);
            document.title = documento.title;
            ["hecho", "n", "ejercicio", "e"].forEach(clave => destino.searchParams.delete(clave));
            history.replaceState(null, "", destino.pathname + destino.search);
            pendiente = null;
            iniciar();
            restaurar(estado);
            const hecho = principal.querySelector("[data-hecho]");
            if (hecho) { anunciar(hecho.textContent); hecho.remove(); }
            const confirmacion = principal.querySelector("[data-confirmacion]");
            if (confirmacion) { pendiente = estado; dialogo(confirmacion); }
            principal.dispatchEvent(new CustomEvent("cuaderno:actualizado"));
        } catch (error) {
            // Una respuesta inesperada: el envío normal (sin JavaScript) sigue funcionando.
            console.warn("Cuaderno: envío normal", error);
            const campos = { ...(boton?.name ? { [boton.name]: boton.value } : {}), ...extra };
            Object.entries(campos).forEach(([name, value]) => form.append(Object.assign(document.createElement("input"), { type: "hidden", name, value })));
            HTMLFormElement.prototype.submit.call(form);
        } finally {
            ocupado = false;
            principal.removeAttribute("aria-busy");
        }
    }

    function dialogo(formulario) {
        const ventana = document.createElement("dialog");
        ventana.className = "cuaderno-dialogo";
        ventana.setAttribute("aria-labelledby", formulario.getAttribute("aria-labelledby"));
        ventana.append(formulario);
        document.body.append(ventana);
        ventana.addEventListener("close", () => { ventana.remove(); pendiente = null; });
        formulario.querySelector("[data-cancelar]")?.addEventListener("click", evento => {
            evento.preventDefault();
            ventana.close();
        });
        ventana.showModal();
    }

    document.addEventListener("submit", evento => {
        const form = evento.target;
        if (form.method !== "post" || evento.defaultPrevented) return;
        evento.preventDefault();
        const boton = evento.submitter;
        const lote = form.matches("[data-lote], .proyecto-lote") || boton?.form?.id?.endsWith("-lote");
        enviar(form, boton, {}, lote);
    });

    // ---- Selección de resoluciones en el cuaderno ----
    function iniciarSeleccion() {
        const form = document.getElementById("cuaderno-seleccion");
        const barra = form?.querySelector("[data-seleccion]");
        if (!form || !barra) return;
        form.setAttribute("data-mejorado", "");
        const cuenta = barra.querySelector("[data-seleccion-cuenta]");
        const marcas = () => [...form.querySelectorAll('input[name="ids"]')];
        const actualizar = () => {
            const n = marcas().filter(m => m.checked).length;
            barra.toggleAttribute("data-activa", n > 0);
            cuenta.textContent = n ? `${n} marcada${n === 1 ? "" : "s"}:` : "Marca resoluciones para añadirlas a un ejercicio o eliminarlas.";
            barra.querySelectorAll("[data-requiere-seleccion]").forEach(b => b.setAttribute("aria-disabled", String(n === 0)));
            form.querySelectorAll("[data-grupo]").forEach(grupo => {
                const propias = [...grupo.querySelectorAll('input[name="ids"]')];
                const todas = grupo.querySelector("[data-marcar-grupo]");
                if (!todas || !propias.length) return;
                const marcadas = propias.filter(m => m.checked).length;
                todas.checked = marcadas === propias.length;
                todas.indeterminate = marcadas > 0 && marcadas < propias.length;
            });
        };
        form.querySelectorAll("[data-marcar-grupo]").forEach(todas => {
            todas.hidden = !todas.closest("[data-grupo]").querySelector('input[name="ids"]');
            todas.addEventListener("change", () => {
                todas.closest("[data-grupo]").querySelectorAll('input[name="ids"]').forEach(m => { m.checked = todas.checked; });
                actualizar();
            });
        });
        form.addEventListener("change", actualizar);
        form.addEventListener("submit", evento => {
            if (evento.submitter?.hasAttribute("data-requiere-seleccion") && !marcas().some(m => m.checked)) {
                evento.preventDefault();
                cuenta.textContent = "Primero marca al menos una resolución.";
                marcas()[0]?.focus();
            }
        }, true);
        actualizar();
    }

    // ---- Organizar: vista previa de números y rangos, casillas y Mayús + clic ----
    let loteActual = null;
    let ultimaMarca = null;
    principal.addEventListener("click", evento => {
        const marca = evento.target.closest?.("[data-marca-ejercicio]");
        if (!marca || !loteActual) return;
        if (evento.shiftKey && ultimaMarca && ultimaMarca !== marca && ultimaMarca.isConnected) {
            const visibles = loteActual.marcas().filter(m => m.offsetParent !== null);
            const [a, b] = [visibles.indexOf(ultimaMarca), visibles.indexOf(marca)].sort((x, y) => x - y);
            visibles.slice(a, b + 1).forEach(m => { m.checked = marca.checked; });
        }
        ultimaMarca = marca;
        loteActual.pintar();
    });

    /* «20, 21, …, 29, 35, 3a» → «20-29, 35, 3a»: los enteros en tramos; el resto, tal cual. */
    function compactar(numeros) {
        const enteros = [...new Set(numeros.filter(n => /^\d+$/.test(n)).map(Number))].sort((a, b) => a - b);
        const tramos = [];
        enteros.forEach((n, i) => {
            if (i && n === enteros[i - 1] + 1) tramos[tramos.length - 1][1] = n;
            else tramos.push([n, n]);
        });
        const otros = numeros.filter(n => !/^\d+$/.test(n) && n !== "·");
        const partes = [...tramos.map(([a, b]) => (a === b ? `${a}` : `${a}-${b}`)), ...otros];
        return partes.length > 12 ? `${partes.slice(0, 11).join(", ")}, …` : partes.join(", ");
    }

    function iniciarLote() {
        loteActual = null;
        const form = principal.querySelector("[data-lote]");
        if (!form) return;
        const vista = form.querySelector("[data-lote-vista]");
        const aplicar = form.querySelector("[data-aplicar]");
        const operacion = form.elements.operacion;
        const marcas = () => [...principal.querySelectorAll("[data-marca-ejercicio]")];
        let porNumero = { ids: [], errores: [], avisos: [] };
        let peticion = 0;
        let temporizador;

        const destinos = () => {
            form.querySelectorAll("[data-para]").forEach(campo => { campo.hidden = campo.dataset.para !== operacion.value; });
            const nueva = form.querySelector("[data-solo-nueva]");
            if (nueva) nueva.hidden = operacion.value !== "seccion" || form.elements.destino_seccion.value !== "nueva";
        };
        const elegidos = () => {
            const ids = new Set(porNumero.ids.map(String));
            marcas().forEach(m => { if (m.checked) ids.add(m.value); });
            return ids;
        };
        const pintar = () => {
            const ids = elegidos();
            principal.querySelectorAll("[data-orden=ejercicios]").forEach(f => f.toggleAttribute("data-elegido", ids.has(f.dataset.id)));
            principal.querySelectorAll("[data-mapa]").forEach(c => c.toggleAttribute("data-elegido", ids.has(c.dataset.mapa)));
            const etiquetas = [...principal.querySelectorAll("[data-orden=ejercicios][data-elegido] .ejercicio-numero")].map(n => n.textContent.trim());
            vista.replaceChildren();
            vista.classList.toggle("proyecto-organizar-error", porNumero.errores.length > 0);
            if (porNumero.errores.length) {
                vista.textContent = porNumero.errores.join(" ");
            } else if (ids.size) {
                const fuera = ids.size - etiquetas.length;
                const lista = compactar(etiquetas);
                vista.textContent = `${ids.size} ejercicio${ids.size === 1 ? "" : "s"}${lista ? `: ${lista}` : ""}${fuera > 0 ? ` (${fuera} oculto${fuera === 1 ? "" : "s"} por la vista)` : ""}.`;
                if (porNumero.avisos.length) vista.append(Object.assign(document.createElement("span"), { className: "proyecto-organizar-aviso", textContent: ` ${porNumero.avisos.join(" ")}` }));
            } else {
                vista.textContent = "Escribe números o rangos, o marca ejercicios en la lista (Mayús + clic marca un tramo).";
            }
            aplicar.textContent = ids.size && !porNumero.errores.length ? `Aplicar a ${ids.size}` : "Aplicar";
            aplicar.setAttribute("aria-disabled", String(!ids.size || porNumero.errores.length > 0));
        };
        const consultar = async () => {
            const texto = form.elements.numeros.value.trim();
            const numero = ++peticion;
            if (!texto) { porNumero = { ids: [], errores: [], avisos: [] }; pintar(); return; }
            try {
                const respuesta = await fetch(`${form.dataset.seleccionUrl}?${new URLSearchParams({ numeros: texto })}`, { credentials: "same-origin" });
                const datos = await respuesta.json();
                if (numero === peticion) { porNumero = datos; pintar(); }
            } catch { /* Sin vista previa: Aplicar la mostrará antes de cambiar nada. */ }
        };
        form.elements.numeros.addEventListener("input", () => { clearTimeout(temporizador); temporizador = setTimeout(consultar, 180); });
        form.addEventListener("change", evento => { if (evento.target !== form.elements.numeros) destinos(); });
        loteActual = { marcas, pintar };
        form.addEventListener("submit", evento => {
            if (aplicar.getAttribute("aria-disabled") === "true") {
                evento.preventDefault();
                evento.stopImmediatePropagation();
                vista.textContent = porNumero.errores.length ? porNumero.errores.join(" ") : "Primero elige ejercicios: escribe números como 3-22 o márcalos en la lista.";
                form.elements.numeros.focus();
                return;
            }
            // La vista previa ya está a la vista; eliminar se confirma siempre en un diálogo.
            form.querySelector("[data-confirmado]").value = operacion.value === "eliminar" ? "" : "1";
        }, true);
        destinos();
        if (form.elements.numeros.value.trim()) consultar(); else pintar();
    }

    // ---- Formularios auxiliares: sección nueva y envío al elegir ----
    function iniciarFormularios() {
        principal.querySelectorAll("form [data-con-nueva]").forEach(select => {
            const nueva = select.form?.querySelector("[data-solo-nueva]") || select.closest("form")?.querySelector("[data-solo-nueva]");
            if (!nueva || select.form?.matches("[data-lote]")) return;
            const ajustar = () => { nueva.hidden = select.value !== "nueva"; };
            select.addEventListener("change", ajustar);
            ajustar();
        });
        principal.querySelectorAll("form[data-autoenviar]").forEach(form => {
            form.querySelectorAll("[data-sin-js]").forEach(b => { b.hidden = true; });
            form.addEventListener("change", () => form.requestSubmit());
        });
    }

    // ---- Ordenar: arrastrar o mover con el teclado ----
    function hermanos(elemento) {
        return [...elemento.parentElement.children].filter(h => h.dataset.orden === elemento.dataset.orden && !h.hidden);
    }

    function colocar(elemento, opciones, limpiarFoco) {
        const form = document.getElementById("op");
        const datos = { accion: "colocar", tabla: elemento.dataset.orden, id: elemento.dataset.id };
        const siguiente = elemento.nextElementSibling?.closest(`[data-orden="${elemento.dataset.orden}"]`);
        const anterior = elemento.previousElementSibling?.closest(`[data-orden="${elemento.dataset.orden}"]`);
        if (opciones) Object.assign(datos, opciones);
        else if (siguiente) datos.antes = siguiente.dataset.id;
        else if (anterior) datos.despues = anterior.dataset.id;
        else datos.seccion = elemento.parentElement.dataset.seccion ?? "";
        pendiente = null;
        const estado = capturar(elemento.querySelector("[data-asa]"));
        if (!limpiarFoco) estado.foco = `asa-${datos.tabla}-${datos.id}`;
        pendiente = estado;
        enviar(form, null, datos);
    }

    function iniciarAsas() {
        principal.querySelectorAll("[data-asa]").forEach(asa => {
            asa.hidden = false;
            asa.dataset.clave = `asa-${asa.dataset.asa}-${asa.dataset.id}`;
        });
    }

    principal.addEventListener("keydown", evento => {
        const asa = evento.target.closest?.("[data-asa]");
        if (!asa || !["ArrowUp", "ArrowDown", "Home", "End"].includes(evento.key)) return;
        evento.preventDefault();
        const elemento = asa.closest("[data-orden]");
        const lista = hermanos(elemento);
        const actual = lista.indexOf(elemento);
        const destino = { ArrowUp: actual - 1, ArrowDown: actual + 1, Home: 0, End: lista.length - 1 }[evento.key];
        if (destino < 0 || destino >= lista.length || destino === actual) return;
        const vecino = lista[destino];
        colocar(elemento, destino < actual ? { antes: vecino.dataset.id } : { despues: vecino.dataset.id });
        anunciar(`Movido a la posición ${destino + 1} de ${lista.length}.`);
    });

    principal.addEventListener("pointerdown", evento => {
        const asa = evento.target.closest?.("[data-asa]");
        if (!asa || evento.button !== 0 || ocupado) return;
        const elemento = asa.closest("[data-orden]");
        const tabla = elemento.dataset.orden;
        const origen = { padre: elemento.parentElement, siguiente: elemento.nextSibling };
        const inicio = evento.clientY;
        let arrastrando = false;
        let ultimaY = evento.clientY;
        let ultimaX = evento.clientX;
        let cuadro = 0;
        try { asa.setPointerCapture(evento.pointerId); } catch { /* puntero sintético (pruebas) */ }

        const permitido = lista => tabla === "ejercicios" ? lista.matches('[data-orden-lista="ejercicios"]')
            : tabla === "referencias" ? lista === origen.padre : lista.matches("[data-orden-raiz]");
        const ubicar = () => {
            const debajo = document.elementFromPoint(ultimaX, ultimaY);
            const objetivo = debajo?.closest(`[data-orden="${tabla}"]`);
            if (objetivo && objetivo !== elemento && permitido(objetivo.parentElement)) {
                const caja = objetivo.getBoundingClientRect();
                const antes = ultimaY < caja.top + caja.height / 2;
                objetivo.parentElement.insertBefore(elemento, antes ? objetivo : objetivo.nextSibling);
                return;
            }
            const lista = tabla === "ejercicios" && debajo?.closest(".proyecto-grupo")?.querySelector('[data-orden-lista="ejercicios"]');
            if (lista && permitido(lista) && !lista.contains(elemento) && !hermanos(elemento).length) lista.append(elemento);
            else if (lista && permitido(lista) && !lista.children.length) lista.append(elemento);
        };
        const desplazar = () => {
            const margen = 70;
            const velocidad = ultimaY < margen ? -(margen - ultimaY) / 3 : ultimaY > innerHeight - margen ? (ultimaY - innerHeight + margen) / 3 : 0;
            if (velocidad) { scrollBy(0, velocidad); ubicar(); }
            cuadro = requestAnimationFrame(desplazar);
        };
        const mover = e => {
            ultimaY = e.clientY;
            ultimaX = e.clientX;
            if (!arrastrando && Math.abs(ultimaY - inicio) < 5) return;
            if (!arrastrando) {
                arrastrando = true;
                elemento.setAttribute("data-arrastrando", "");
                principal.setAttribute("data-arrastre", tabla);
                cuadro = requestAnimationFrame(desplazar);
            }
            ubicar();
        };
        const terminar = cancelar => {
            asa.removeEventListener("pointermove", mover);
            asa.removeEventListener("pointerup", soltar);
            asa.removeEventListener("pointercancel", anular);
            document.removeEventListener("keydown", escape);
            cancelAnimationFrame(cuadro);
            elemento.removeAttribute("data-arrastrando");
            principal.removeAttribute("data-arrastre");
            const cambio = elemento.parentElement !== origen.padre || elemento.nextSibling !== origen.siguiente;
            if (cancelar || !arrastrando) {
                if (cambio) origen.padre.insertBefore(elemento, origen.siguiente);
                return;
            }
            if (cambio) colocar(elemento);
        };
        const soltar = () => terminar(false);
        const anular = () => terminar(true);
        const escape = e => { if (e.key === "Escape") terminar(true); };
        asa.addEventListener("pointermove", mover);
        asa.addEventListener("pointerup", soltar);
        asa.addEventListener("pointercancel", anular);
        document.addEventListener("keydown", escape);
    });

    function iniciar() {
        iniciarMenu(principal);
        iniciarSeleccion();
        iniciarLote();
        iniciarFormularios();
        iniciarAsas();
    }
    iniciar();
    const hecho = principal.querySelector("[data-hecho]");
    if (hecho) { anunciar(hecho.textContent); hecho.remove(); }
    const confirmacion = principal.querySelector("[data-confirmacion]");
    if (confirmacion) dialogo(confirmacion);
})();
