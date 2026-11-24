/* Sarco Workspace su PC: Ctrl K apre la ricerca tra le pagine (file a parte: la sicurezza vieta gli script dentro la pagina) */
(function () {
  var d = document.getElementById('pc-cerca'), t = document.getElementById('pc-cerca-testo');
  var voci = Array.prototype.slice.call(document.querySelectorAll('#pc-cerca-lista li'));
  var vuoto = d.querySelector('.pc-cerca-vuoto');
  function apri(testo) { d.showModal(); t.value = testo || ''; filtra(); t.focus(); }
  function filtra() {
    var q = t.value.trim().toLowerCase(), viste = 0;
    voci.forEach(function (li) { var ok = li.textContent.toLowerCase().indexOf(q) > -1; li.hidden = !ok; if (ok) viste++; });
    vuoto.hidden = viste > 0;
  }
  t.addEventListener('input', filtra);
  t.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { var a = d.querySelector('#pc-cerca-lista li:not([hidden]) a'); if (a) { e.preventDefault(); location.href = a.href; } }
  });
  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); apri(); }
  });
  document.querySelectorAll('[data-apri-cerca]').forEach(function (el) {
    el.addEventListener('focus', function () { el.blur(); apri(el.value); });
    el.addEventListener('click', function () { apri(el.value); });
  });
  d.addEventListener('click', function (e) { if (e.target === d) d.close(); });
})();
