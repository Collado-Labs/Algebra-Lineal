/* El sufijo % hace explícito el criterio antes de calcular, también al pegar. */
(() => {
    "use strict";
    for (const campo of document.querySelectorAll("[data-tolerancia]")) {
        const criterio = campo.form?.querySelector("[data-criterio-tolerancia]");
        if (!criterio) continue;
        const reconocerPorcentaje = () => {
            if (campo.value.trimEnd().endsWith("%")) criterio.value = "porcentual";
        };
        campo.addEventListener("input", reconocerPorcentaje);
        criterio.addEventListener("change", reconocerPorcentaje);
        reconocerPorcentaje();
    }
})();
