/* Progressive enhancement: data stays readable without JavaScript. */
(() => {
  const $ = (id) => document.getElementById(id);
  const normal = (s) => String(s ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("es");
  const setStatus = (value) => { const target = $("status-live"); if (target) target.textContent = value; };
  document.querySelectorAll("[data-copy-for]").forEach(button => {
    button.addEventListener("click", async () => {
      const source = $(button.getAttribute("data-copy-for"));
      if (!source) return;
      const str = source.textContent?.trim() ?? "";
      try {
        await navigator.clipboard.writeText(str);
        button.textContent = "Copiado";
        setStatus("Contenido copiado al portapapeles.");
      } catch {
        const selection = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(source);
        selection.removeAllRanges();
        selection.addRange(range);
        button.textContent = "Texto seleccionado";
        setStatus("Texto seleccionado para copia manual.");
      }
    });
  });
  const search = $("record-search"), counter = $("visible-count"), sort = $("record-sort");
  const recordsParent = $("records-body");
  const records = recordsParent ? [...recordsParent.querySelectorAll("[data-record]")] : [];
  function refresh() {
    if (!records.length) return;
    const term = normal(search?.value ?? "");
    const visible = records.filter(el => normal(el.getAttribute("data-search") ?? el.textContent).includes(term));
    for (const item of records) item.hidden = !visible.includes(item);
    if (sort?.value === "name") {
      visible.sort((a, b) => normal(a.dataset.title).localeCompare(normal(b.dataset.title), "es"));
    } else if (sort?.value === "date") {
      visible.sort((a, b) => String(b.dataset.date ?? "").localeCompare(String(a.dataset.date ?? "")));
    } else {
      visible.sort((a, b) => Number(a.dataset.original) - Number(b.dataset.original));
    }
    for (const item of visible) recordsParent.append(item);
    if (counter) counter.textContent = String(visible.length);
    const empty = $("no-records");
    if (empty) empty.hidden = visible.length !== 0;
    setStatus(visible.length + " coincidencias dentro de esta captura histórica.");
  }
  search?.addEventListener("input", refresh);
  sort?.addEventListener("change", refresh);
  const csv = $("export-csv");
  csv?.addEventListener("click", () => {
    if (!records.length) return;
    const table = recordsParent.closest("table");
    if (!table) { setStatus("Esta vista no contiene una tabla para exportar."); return; }
    const visible = records.filter(x => !x.hidden);
    const headers = [...table.querySelectorAll("thead th")].map(x => x.textContent.trim());
    const cells = visible.map(row => [...row.children].map(x => x.textContent.trim().replace(/\s+/g, " ")));
    const quote = v => '"' + String(v).replaceAll('"', '""') + '"';
    const documentDate = document.body.dataset.capture ?? "";
    const lines = [
      ["Captura original", documentDate, "Ejemplo histórico, no consulta actual"],
      headers, ...cells
    ].map(r => r.map(quote).join(","));
    const object = URL.createObjectURL(new Blob(["\ufeff"+lines.join("\r\n")], {type: "text/csv;charset=utf-8"}));
    const anchor = document.createElement("a");
    anchor.href = object; anchor.download = (document.body.dataset.product ?? "spain-evidence") + "-ejemplo.csv";
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(object), 1000);
    setStatus("CSV generado con los registros visibles de la muestra histórica.");
  });
  refresh();
})();
