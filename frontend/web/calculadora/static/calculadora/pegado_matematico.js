/* Lee la estructura que entrega el portapapeles. El HTML vive en un template inerte. */
window.linealizarPegadoMatematico = html => {
    "use strict";
    if (!html || html.length > 65536) return null;
    const plantilla = document.createElement("template");
    plantilla.innerHTML = html;
    let estructurado = false;
    function leer(nodo) {
        if (nodo.nodeType === Node.TEXT_NODE) return nodo.textContent;
        if (nodo.nodeType !== Node.ELEMENT_NODE) return "";
        const etiqueta = nodo.localName;
        if (["script", "style", "annotation", "annotation-xml", "xml", "img"].includes(etiqueta)
            || nodo.hidden || nodo.style?.display === "none") return "";
        const hijos = [...nodo.childNodes];
        const partes = [...nodo.children];
        if (etiqueta === "semantics") return partes[0] ? leer(partes[0]) : "";
        if (etiqueta === "mfrac" && partes.length === 2) {
            estructurado = true;
            return "(" + leer(partes[0]) + ")/(" + leer(partes[1]) + ")";
        }
        if (etiqueta === "msup" && partes.length === 2) {
            estructurado = true;
            return "(" + leer(partes[0]) + ")^(" + leer(partes[1]) + ")";
        }
        const texto = hijos.map(leer).join("");
        if (etiqueta === "msqrt") {
            estructurado = true;
            return "√(" + texto + ")";
        }
        if (etiqueta === "sup" || nodo.style?.verticalAlign === "super") {
            estructurado = true;
            return "^(" + texto.trim() + ")";
        }
        return texto;
    }
    const texto = [...plantilla.content.childNodes].map(leer).join("").trim();
    return estructurado && texto ? texto : null;
};
