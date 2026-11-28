/* Cuaderno de resoluciones con los scripts y formularios de producción, en iframes. */
(async () => {
    const igual = (a, b, mensaje = "") => {
        if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`${mensaje} ${JSON.stringify(a)} != ${JSON.stringify(b)}`);
    };
    const cierto = (valor, mensaje) => { if (!valor) throw new Error(mensaje); };
    const q = (w, selector) => w.document.querySelector(selector);
    const todos = (w, selector) => [...w.document.querySelectorAll(selector)];
    const texto = (w, selector) => q(w, selector)?.textContent.replace(/\s+/g, " ").trim() ?? "";
    const valor = (w, selector, v) => {
        const input = q(w, selector);
        input.value = String(v);
        input.dispatchEvent(new w.Event("input", {bubbles: true}));
    };
    const marcar = (w, selector, estado = true) => {
        const casilla = q(w, selector);
        if (casilla.checked !== estado) casilla.click();
    };
    // Espera la página siguiente del iframe tras una acción (clic, envío, enlace) o, en el cuaderno,
    // la actualización sin recarga que hace resoluciones.js (evento «cuaderno:actualizado»).
    const navegar = (frame, accion) => new Promise((resolve, reject) => {
        const limite = setTimeout(() => reject(new Error("La página no respondió")), 15000);
        const listo = () => { clearTimeout(limite); frame.onload = null; resolve(frame.contentWindow); };
        frame.onload = listo;
        frame.contentWindow.document.getElementById("contenido")?.addEventListener("cuaderno:actualizado", listo, {once: true});
        accion(frame.contentWindow);
    });
    const anuncio = w => texto(w, ".cuaderno-anuncio") || texto(w, ".cuaderno-hecho");
    const esperar = ms => new Promise(resolve => setTimeout(resolve, ms));
    const numeros = w => todos(w, ".ejercicio .ejercicio-numero").map(n => n.textContent.trim());
    const abrir = (frame, url) => navegar(frame, w => { w.location.href = url; });
    const calcularInversa = async (frame, filas) => {
        let w = await abrir(frame, "/matrices/inversa/");
        filas.forEach((fila, i) => fila.forEach((v, j) => valor(w, `[name="celda_A_${i}_${j}"]`, v)));
        return navegar(frame, w => q(w, "[data-calculo]").click());
    };
    const reiniciar = () => fetch("/__pruebas/reiniciar", {cache: "no-store"});
    // Preparar datos sin pasar por la interfaz: el mismo POST que harían los formularios.
    const enviar = async (ruta, datos) => {
        const token = document.cookie.match(/csrftoken=([^;]+)/)?.[1] ?? "";
        const cuerpo = new URLSearchParams();
        for (const [clave, v] of Object.entries(datos)) [].concat(v).forEach(x => cuerpo.append(clave, String(x)));
        return fetch(ruta, {method: "POST", body: cuerpo, headers: {"X-CSRFToken": token}, credentials: "same-origin"});
    };
    const proyectoDePrueba = async (hasta = 12) => {
        await fetch("/resoluciones/");  // cookie CSRF
        await enviar("/resoluciones/", {accion: "crear_proyecto", nombre: "Práctica de matrices", objetivo: 64});
        const id = (await (await fetch("/__pruebas/proyectos")).json())[0];
        await enviar("/resoluciones/", {accion: "crear_ejercicios", proyecto: id, numeros: `1-${hasta}`});
        return id;
    };

    const casos = [
        ["Calcular anota la resolución y el aviso queda bajo el encabezado del resultado", {}, async (w, frame) => {
            w = await calcularInversa(frame, [[2, 1], [5, 3]]);
            const aviso = q(w, "#resolucion-aviso");
            igual(aviso.dataset.estado, "guardada");
            igual(aviso.previousElementSibling, q(w, "[data-resultado] .results-heading"), "posición del aviso:");
            cierto(texto(w, "#resolucion-aviso").startsWith("Guardada en tu cuaderno."), texto(w, "#resolucion-aviso"));
            cierto(!texto(w, "#resolucion-aviso").includes("Desde tu cuaderno"), "recién guardada no es una consulta");
            w = await navegar(frame, w => q(w, "[data-calculo]").click());
            igual(q(w, "#resolucion-aviso").dataset.estado, "existente", "recalcular lo mismo:");
        }],
        ["Añadir a un ejercicio desde la herramienta vuelve a la resolución y dice dónde quedó", {}, async (w, frame) => {
            w = await calcularInversa(frame, [[1, 2], [3, 4]]);
            q(w, ".resolucion-agrupar > summary").click();
            cierto(q(w, ".resolucion-agrupar .cuaderno-nombre-nuevo").getClientRects().length, "nombre visible para un ejercicio nuevo");
            valor(w, '.resolucion-agrupar [name="nombre_ejercicio"]', "Tarea 3");
            w = await navegar(frame, w => q(w, ".resolucion-agrupar-form button").click());
            igual(new URL(w.location.href).searchParams.has("resolucion"), true);
            igual(q(w, "#resolucion-aviso").dataset.estado, "anadida");
            cierto(texto(w, "#resolucion-aviso").startsWith("Añadida a Tarea 3"), texto(w, "#resolucion-aviso"));
            igual(texto(w, ".resolucion-agrupar > summary"), "Añadir a un ejercicio", "otra referencia, no mover:");
        }],
        ["Reabrir desde el cuaderno muestra datos y resultado; editar lo marca desactualizado", {}, async (w, frame) => {
            w = await calcularInversa(frame, [[4, 7], [2, 6]]);
            w = await abrir(frame, "/resoluciones/");
            w = await navegar(frame, w => q(w, ".hoja-nombre a").click());
            igual(q(w, '[name="celda_A_0_1"]').value, "7");
            igual(q(w, "#resultado").dataset.resultado, "vigente");
            cierto(texto(w, "#resultado").includes("A es invertible"), "resultado restaurado");
            valor(w, '[name="celda_A_0_1"]', "8");
            igual(q(w, "#resultado").dataset.resultado, "desactualizado");
        }],
        ["Selección: recuento, marcar un día completo y acciones que piden algo marcado", {}, async (w, frame) => {
            await calcularInversa(frame, [[1, 1], [0, 1]]);
            await calcularInversa(frame, [[3, 1], [2, 1]]);
            w = await abrir(frame, "/resoluciones/");
            const barra = q(w, "[data-seleccion]");
            igual(barra.hasAttribute("data-activa"), false);
            w.document.querySelector('[data-requiere-seleccion][value="anadir"]').click();
            cierto(texto(w, "[data-seleccion-cuenta]").includes("Primero marca"), "aviso sin selección");
            const dia = q(w, ".hoja-dia [data-marcar-grupo]");
            igual(dia.hidden, false);
            dia.click();
            igual(texto(w, "[data-seleccion-cuenta]"), "2 marcadas:");
            igual(barra.hasAttribute("data-activa"), true);
            igual(getComputedStyle(barra).position, "sticky");
            todos(w, '.hoja-dia input[name="ids"]')[0].click();
            igual(dia.indeterminate, true);
            dia.click();
            w = await navegar(frame, w => q(w, '[data-requiere-seleccion][value="anadir"]').click());
            cierto(anuncio(w).startsWith("Añadiste 2 resoluciones a «Ejercicio 1»"), anuncio(w));
            igual(todos(w, "ol.hoja-pasos > .hoja-entrada").length, 2);
            cierto(w.getComputedStyle(q(w, "ol.hoja-pasos .hoja-nombre"), "::before").content.includes("counter(paso"), "pasos numerados");
        }],
        ["Renombrar con Enter solo envía su propio formulario", {}, async (w, frame) => {
            await calcularInversa(frame, [[5, 2], [2, 1]]);
            w = await abrir(frame, "/resoluciones/");
            q(w, ".hoja-entrada .hoja-editar > summary").click();
            const campo = q(w, '.hoja-entrada [name="nombre"]');
            valor(w, '.hoja-entrada [name="nombre"]', "Inversa de la tarea");
            w = await navegar(frame, () => campo.form.requestSubmit());
            igual(anuncio(w), "Cambiaste el nombre de la resolución.");
            igual(texto(w, ".hoja-nombre"), "Inversa de la tarea");
        }],
        ["Eliminar pide confirmación y Cancelar no borra nada", {}, async (w, frame) => {
            await calcularInversa(frame, [[6, 1], [5, 1]]);
            w = await abrir(frame, "/resoluciones/");
            marcar(w, '.hoja-entrada input[name="ids"]');
            w = await navegar(frame, w => q(w, '[data-requiere-seleccion][value="eliminar"]').click());
            const dialogo = q(w, "dialog.cuaderno-dialogo");
            cierto(dialogo?.open, "la confirmación se abre en un diálogo, sin perder el sitio");
            cierto(texto(w, ".confirmation").includes("¿Eliminar esta resolución del cuaderno?"), texto(w, ".confirmation"));
            q(w, ".confirmation [data-cancelar]").click();
            cierto(!q(w, "dialog.cuaderno-dialogo")?.open, "Cancelar cierra el diálogo");
            igual(todos(w, ".hoja-entrada").length, 1);
            marcar(w, '.hoja-entrada input[name="ids"]');
            w = await navegar(frame, w => q(w, '[data-requiere-seleccion][value="eliminar"]').click());
            w = await navegar(frame, w => q(w, '.confirmation [value="eliminar_confirmado"]').click());
            igual(anuncio(w), "Eliminaste 1 resolución del cuaderno.");
            cierto(q(w, ".cuaderno-blanco"), "vuelve el cuaderno en blanco");
        }],
        ["Sin JavaScript: la barra se ve siempre y reunir funciona con el formulario", {sinJS: true}, async (w, frame) => {
            await reiniciar();
            w = await abrir(frame, "/resoluciones/");
            cierto(q(w, ".cuaderno-blanco"), "en blanco al empezar");
            w = await abrir(frame, "/romanos/conversion/");
            valor(w, '[name="numero"]', "1963");
            w = await navegar(frame, w => q(w, 'form[action$="#resultado"] [type="submit"]:not([formnovalidate])').click());
            igual(q(w, "#resolucion-aviso").dataset.estado, "guardada");
            w = await abrir(frame, "/resoluciones/");
            igual(getComputedStyle(q(w, "[data-seleccion]")).display, "flex");
            igual(q(w, "[data-marcar-grupo]").hidden, true);
            marcar(w, '.hoja-entrada input[name="ids"]');
            w = await navegar(frame, w => q(w, '[data-requiere-seleccion][value="anadir"]').click());
            cierto(texto(w, ".cuaderno-hecho").startsWith("Añadiste 1 resolución"), texto(w, ".cuaderno-hecho"));
        }],
    ];

    // Ni las áreas ni la marca quedan debajo de los botones de la cabecera.
    const cabeceraSinSolapes = (w, contexto = "") => {
        const acciones = q(w, ".header-actions").getBoundingClientRect();
        const inicio = q(w, ".header-start").getBoundingClientRect();
        cierto(inicio.right <= acciones.left + 1, `${contexto} la marca queda bajo las acciones`);
        for (const enlace of todos(w, ".nav-areas a").filter(a => a.getClientRects().length)) {
            cierto(enlace.getBoundingClientRect().right <= acciones.left + 1,
                `${contexto} «${enlace.textContent.trim()}» queda bajo las acciones`);
        }
    };

    casos.push(["Proyecto: crear, preparar ejercicios, trabajar en uno y añadir con un clic tras calcular", {}, async (w, frame) => {
        w = await abrir(frame, "/resoluciones/");
        q(w, ".cuaderno-nuevo > summary").click();
        valor(w, '.cuaderno-nuevo-form [name="nombre"]', "Práctica de matrices");
        valor(w, '.cuaderno-nuevo-form [name="objetivo"]', 64);
        w = await navegar(frame, w => q(w, ".cuaderno-nuevo-form [type=submit]").click());
        cierto(anuncio(w).startsWith("Creaste el proyecto"), anuncio(w));
        cierto(q(w, "#proyecto-activo"), "el proyecto nuevo queda activo");
        const preparar = todos(w, ".cuaderno-nuevo").find(d => d.textContent.includes("Preparar varios"));
        igual(preparar.open, true, "en blanco, «Preparar varios» se ofrece abierto:");
        valor(w, '#preparar [name="numeros"]', "1-12");
        w = await navegar(frame, () => preparar.querySelector("form").requestSubmit());
        igual(todos(w, ".mapa-celda").length, 64, "12 creados + 52 por preparar:");
        igual(todos(w, '.mapa-celda[data-estado="por-crear"]').length, 52);
        const tercero = todos(w, ".ejercicio")[2];
        w = await navegar(frame, () => tercero.querySelector(".hoja-activar").click());
        igual(texto(w, ".proyecto-activo-ejercicio"), "Ej. 3");
        w = await calcularInversa(frame, [[3, 1], [5, 2]]);
        const anadir = q(w, ".resolucion-anadir button");
        cierto(anadir && texto(w, ".resolucion-anadir button").startsWith("Añadir a Ej. 3"), "botón de un clic");
        w = await navegar(frame, () => anadir.click());
        igual(q(w, "#resolucion-aviso").dataset.estado, "anadida");
        cierto(texto(w, "#resolucion-aviso").startsWith("Añadida a Ej. 3 · Práctica de matrices"), texto(w, "#resolucion-aviso"));
        // Cambiar de ejercicio desde el menú (buscando su número) vuelve a la misma resolución.
        q(w, ".proyecto-activo-resumen").click();
        const buscar = q(w, "[data-buscar-ejercicio] input");
        cierto(!q(w, "[data-buscar-ejercicio]").hidden, "la búsqueda aparece con muchos ejercicios");
        valor(w, "[data-buscar-ejercicio] input", "5");
        igual(todos(w, "[data-lista-ejercicios] li").filter(li => !li.hidden).map(li => li.textContent.trim()), ["Ejercicio 5"]);
        w = await navegar(frame, () => buscar.dispatchEvent(new w.KeyboardEvent("keydown", {key: "Enter", bubbles: true})));
        igual(texto(w, ".proyecto-activo-ejercicio"), "Ej. 5");
        igual(new URL(w.location.href).searchParams.has("resolucion"), true, "vuelve a la resolución:");
        w = await abrir(frame, "/resoluciones/proyectos/" + new URL(q(w, ".proyecto-activo-titulo a").href).pathname.split("/")[3] + "/");
        igual(q(w, '.mapa-celda[data-estado="resuelto"] [aria-hidden]').textContent.trim(), "3");
    }]);
    casos.push(["Proyecto: dejar fuera del documento sin borrar, reordenar con teclado y arrastre, ordenar por número", {}, async (w, frame) => {
        const id = await proyectoDePrueba(4);
        w = await abrir(frame, `/resoluciones/proyectos/${id}/`);
        igual(texto(w, ".proyecto-borrador-cifras").startsWith("4 ejercicios"), true, texto(w, ".proyecto-borrador-cifras"));
        w = await navegar(frame, w => todos(w, ".ejercicio .incluir")[1].click());
        igual(todos(w, ".ejercicio")[1].hasAttribute("data-excluida"), true);
        igual(todos(w, ".ejercicio")[1].querySelector(".incluir").getAttribute("aria-pressed"), "false");
        cierto(texto(w, ".proyecto-borrador-cifras").startsWith("3 ejercicios"), texto(w, ".proyecto-borrador-cifras"));
        igual(todos(w, ".ejercicio").length, 4, "excluir no borra:");
        // Teclado: el asa con el foco y ↓ baja un puesto; el foco sigue en su asa.
        const asa = todos(w, ".ejercicio [data-asa]")[0];
        cierto(!asa.hidden, "el asa aparece con JavaScript");
        asa.focus();
        w = await navegar(frame, () => asa.dispatchEvent(new w.KeyboardEvent("keydown", {key: "ArrowDown", bubbles: true})));
        igual(numeros(w), ["2", "1", "3", "4"]);
        igual(w.document.activeElement?.dataset.clave, todos(w, ".ejercicio [data-asa]")[1].dataset.clave, "foco en el asa movida:");
        igual(new URL(w.location.href).pathname, `/resoluciones/proyectos/${id}/`, "sigue en el proyecto:");
        // Arrastre con el puntero: el 2 se suelta bajo el 4.
        const origen = todos(w, ".ejercicio [data-asa]")[0];
        const destino = todos(w, ".ejercicio")[3].getBoundingClientRect();
        const puntero = (tipo, y) => origen.dispatchEvent(new w.PointerEvent(tipo, {bubbles: true, button: 0, pointerId: 7, clientX: destino.left + 40, clientY: y}));
        w = await navegar(frame, () => {
            puntero("pointerdown", origen.getBoundingClientRect().top + 5);
            puntero("pointermove", destino.top + 10);
            puntero("pointermove", destino.bottom - 4);
            puntero("pointerup", destino.bottom - 4);
        });
        igual(numeros(w), ["1", "3", "4", "2"]);
        w = await navegar(frame, w => q(w, '[form="ordenar-proyecto"]').click());
        igual(numeros(w), ["1", "2", "3", "4"]);
    }]);
    casos.push(["Organizar por rangos: vista previa, aplicar en una operación y confirmar al eliminar", {}, async (w, frame) => {
        const id = await proyectoDePrueba(64);
        await enviar(`/resoluciones/proyectos/${id}/`, {accion: "crear_seccion", proyecto: id, nombre: "Sistemas"});
        w = await abrir(frame, `/resoluciones/proyectos/${id}/`);
        valor(w, '#lote [name="numeros"]', "20-29, 35, 40-44");
        await esperar(700);
        igual(texto(w, "[data-lote-vista]"), "16 ejercicios: 20-29, 35, 40-44.");
        igual(todos(w, ".mapa-celda[data-elegido]").length, 16, "el mapa muestra la selección:");
        igual(texto(w, "[data-aplicar]"), "Aplicar a 16");
        valor(w, '#lote [name="numeros"]', "22-3, 99");
        await esperar(700);
        cierto(texto(w, "[data-lote-vista]").includes("al revés") && texto(w, "[data-lote-vista]").includes("99"), texto(w, "[data-lote-vista]"));
        igual(q(w, "[data-aplicar]").getAttribute("aria-disabled"), "true");
        valor(w, '#lote [name="numeros"]', "3-22");
        await esperar(700);
        // Mayús + clic suma un tramo marcado en la lista.
        const marcas = todos(w, "[data-marca-ejercicio]");
        marcas[59].click();
        marcas[61].dispatchEvent(new w.MouseEvent("click", {bubbles: true, shiftKey: true}));
        igual(marcas.slice(59, 62).map(m => m.checked), [true, true, true]);
        igual(texto(w, "[data-aplicar]"), "Aplicar a 23");
        const seccion = q(w, '#lote [name="destino_seccion"]');
        seccion.value = [...seccion.options].find(o => o.textContent === "Sistemas").value;
        w = await navegar(frame, w => q(w, "[data-aplicar]").click());
        igual(anuncio(w), "Moviste 23 ejercicios a «Sistemas».");
        igual(todos(w, "#" + q(w, ".proyecto-grupo[data-id]").id + " .ejercicio").length, 23);
        igual(q(w, '#lote [name="numeros"]').value, "", "la selección aplicada se limpia:");
        // Eliminar siempre confirma en un diálogo con los ejercicios elegidos.
        valor(w, '#lote [name="numeros"]', "63-64");
        await esperar(700);
        q(w, '#lote [name="operacion"]').value = "eliminar";
        w = await navegar(frame, w => q(w, "[data-aplicar]").click());
        cierto(q(w, "dialog.cuaderno-dialogo")?.open, "diálogo de confirmación");
        igual(texto(w, ".proyecto-lote-lista"), "Ej. 63Ej. 64");
        w = await navegar(frame, w => q(w, '.proyecto-lote [name="confirmado_eliminar"]').click());
        igual(todos(w, ".ejercicio").length, 62);
    }]);
    casos.push(["Contexto: excluir una resolución del ejercicio 56 no devuelve arriba y los controles no se mueven", {}, async (w, frame) => {
        const id = await proyectoDePrueba(64);
        await calcularInversa(frame, [[2, 1], [7, 4]]);
        w = frame.contentWindow;
        const ejercicio = (await (await fetch(`/resoluciones/proyectos/${id}/seleccion/?numeros=56`)).json()).ids[0];
        await enviar("/resoluciones/", {accion: "anadir", ids: q(w, '.resolucion-anadir [name="ids"], .resolucion-agrupar [name="ids"]').value, ejercicio});
        w = await abrir(frame, `/resoluciones/proyectos/${id}/`);
        const fila = q(w, `#ejercicio-${ejercicio}`);
        fila.querySelector("details.ejercicio-detalle").open = true;
        fila.scrollIntoView({block: "center"});
        const alto = fila.getBoundingClientRect().top;
        cierto(w.scrollY > 2000, `lejos del principio: ${w.scrollY}`);
        w = await navegar(frame, () => fila.querySelector(".hoja-entrada .incluir").click());
        const despues = q(w, `#ejercicio-${ejercicio}`);
        cierto(Math.abs(despues.getBoundingClientRect().top - alto) < 3, `misma posición: ${alto} → ${despues.getBoundingClientRect().top}`);
        igual(despues.querySelector("details.ejercicio-detalle").open, true, "sigue desplegado:");
        igual(despues.querySelector(".hoja-entrada .incluir").getAttribute("aria-pressed"), "false");
        cierto(texto(w, ".proyecto-borrador-cifras").includes("0 resoluciones"), texto(w, ".proyecto-borrador-cifras"));
        // Desplegar Editar o Preparar varios no mueve los controles de su fila ni de la barra.
        const editar = despues.querySelector(".hoja-controles > .hoja-editar > summary");
        const incluir = despues.querySelector(".hoja-controles > .incluir");
        const antes = [editar, incluir].map(e => JSON.stringify(e.getBoundingClientRect()));
        editar.click();
        igual([editar, incluir].map(e => JSON.stringify(e.getBoundingClientRect())), antes, "Editar abierto:");
        const preparar = q(w, "#preparar > summary");
        const botones = todos(w, ".proyecto-herramientas-botones > *").map(e => JSON.stringify(e.getBoundingClientRect()));
        preparar.click();
        igual(todos(w, ".proyecto-herramientas-botones > *").map(e => JSON.stringify(e.getBoundingClientRect())), botones, "Preparar varios abierto:");
    }]);

    // Coherencia en los cinco estilos y los dos temas: la cabecera no se solapa y el cuaderno no se desborda.
    for (const estilo of ["estudio", "minimalista", "chocolab", "belugacalc", "heyalgb"]) {
        for (const tema of ["light", "dark"]) {
            casos.push([`${estilo} · ${tema}: cabecera sin solapes, aviso, proyecto y hoja legibles`, {estilo, tema, ancho: 1280}, async (w, frame) => {
                const id = await proyectoDePrueba(6);
                await calcularInversa(frame, [[2, 0], [0, 2]]);
                w = frame.contentWindow;
                igual(w.document.documentElement.dataset.estilo, estilo);
                cabeceraSinSolapes(w);
                const aviso = q(w, "#resolucion-aviso");
                cierto(getComputedStyle(aviso).color !== getComputedStyle(aviso).backgroundColor, "texto del aviso visible");
                cierto(q(w, "#proyecto-activo").getBoundingClientRect().right <= w.innerWidth, "indicador dentro de la página");
                w = await abrir(frame, "/resoluciones/");
                igual(q(w, ".header-resoluciones").getAttribute("aria-current"), "page");
                cierto(w.document.documentElement.scrollWidth <= w.innerWidth, "sin desbordamiento horizontal");
                w = await abrir(frame, `/resoluciones/proyectos/${id}/`);
                cierto(w.document.documentElement.scrollWidth <= w.innerWidth, "proyecto sin desbordamiento");
                const celda = q(w, ".mapa-celda");
                cierto(getComputedStyle(celda).color !== getComputedStyle(celda).backgroundColor, "casilla legible");
            }]);
        }
    }
    casos.push(["Cabecera sin solapes de 481 a 1600 px en los cinco estilos", {}, async (w, frame) => {
        for (const ancho of [481, 600, 768, 1180, 1240, 1366, 1440, 1600]) {
            for (const estilo of ["estudio", "minimalista", "chocolab", "belugacalc", "heyalgb"]) {
                localStorage.setItem("pygebra-estilo", estilo);
                frame.style.width = `${ancho}px`;
                w = await abrir(frame, "/matrices/inversa/");
                cabeceraSinSolapes(w, `${estilo} a ${ancho} px:`);
            }
        }
    }]);
    casos.push(["Móvil (390 px): el proyecto y su indicador caben sin desbordar", {ancho: 390}, async (w, frame) => {
        const id = await proyectoDePrueba(64);
        w = await abrir(frame, `/resoluciones/proyectos/${id}/`);
        cierto(w.document.documentElement.scrollWidth <= w.innerWidth, `desborda: ${w.document.documentElement.scrollWidth}`);
        q(w, ".proyecto-activo-resumen").click();
        const panel = q(w, ".proyecto-activo-panel").getBoundingClientRect();
        cierto(panel.left >= 0 && panel.right <= w.innerWidth, "panel del proyecto activo dentro de la pantalla");
        q(w, ".proyecto-activo-resumen").click();
        q(w, ".ejercicio .hoja-editar > summary").click();
        const editar = q(w, ".ejercicio .hoja-editar-cuerpo").getBoundingClientRect();
        cierto(editar.left >= 0 && editar.right <= w.innerWidth && editar.bottom <= w.innerHeight, "Editar se abre dentro de la pantalla");
    }]);
    casos.push(["Móvil (390 px): filtros, hoja y barra caben sin desbordar", {ancho: 390}, async (w, frame) => {
        await calcularInversa(frame, [[1, 3], [2, 7]]);
        w = await abrir(frame, "/resoluciones/");
        cierto(w.document.documentElement.scrollWidth <= w.innerWidth, `desborda: ${w.document.documentElement.scrollWidth}`);
        marcar(w, '.hoja-entrada input[name="ids"]');
        const barra = q(w, "[data-seleccion]").getBoundingClientRect();
        cierto(barra.right <= w.innerWidth && barra.left >= 0, "barra dentro de la pantalla");
    }]);

    let pasadas = 0;
    for (const [nombre, opciones, prueba] of casos) {
        await reiniciar();
        localStorage.setItem("pygebra-estilo", opciones.estilo ?? "estudio");
        localStorage.setItem("pygebra-tema", opciones.tema ?? "light");
        const frame = document.createElement("iframe");
        frame.style.width = `${opciones.ancho ?? 1100}px`;
        frame.style.height = "800px";
        if (opciones.sinJS) frame.setAttribute("sandbox", "allow-same-origin allow-forms");
        frame.src = "/resoluciones/";
        const cargado = new Promise(resolve => { frame.onload = resolve; });
        document.body.append(frame);
        await cargado;
        const item = document.createElement("li");
        const inicio = performance.now();
        const duracion = () => `${((performance.now() - inicio) / 1000).toFixed(1)} s`;
        try { await prueba(frame.contentWindow, frame); pasadas++; item.textContent = `PASS · ${nombre} (${duracion()})`; }
        catch (error) { item.textContent = `FAIL · ${nombre}: ${error.message} (${duracion()})`; }
        document.querySelector("#resultados").append(item);
        frame.remove();
    }
    localStorage.removeItem("pygebra-estilo");
    localStorage.removeItem("pygebra-tema");
    document.querySelector("#total").textContent = `${pasadas}/${casos.length} PASS`;
})();
