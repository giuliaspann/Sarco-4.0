// Registra il service worker: rende l'app installabile sulla schermata Home.
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}

// Le foto del telefono pesano diversi MB: prima dell'invio le riduco a 1600px in JPEG.
const LATO_MAX = 1600;

async function riduci(file) {
  if (!(file.type || '').startsWith('image/')) return file;  // i video si mandano come sono
  const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
  const scala = Math.min(1, LATO_MAX / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(bitmap.width * scala);
  canvas.height = Math.round(bitmap.height * scala);
  canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise(r => canvas.toBlob(r, 'image/jpeg', 0.75));
  return new File([blob], 'foto.jpg', { type: 'image/jpeg' });
}

document.querySelectorAll('input[type=file][data-riduci]').forEach(input => {
  input.addEventListener('change', async () => {
    const files = [...input.files].slice(0, 20);
    const etichetta = input.closest('label');
    if (!files.length) return;
    const video = files.filter(f => (f.type || '').startsWith('video/')).length;
    const foto = files.length - video;
    etichetta.querySelector('span').textContent = '✓ ' + [foto ? foto + ' foto' : '', video ? video + ' video' : ''].filter(Boolean).join(' e ');
    etichetta.classList.add('pronta');
    if (!window.DataTransfer || !window.createImageBitmap) return;
    try {
      const dt = new DataTransfer();
      for (const f of files) dt.items.add(await riduci(f));
      input.files = dt.files;
    } catch (e) {
      // se il browser non ci riesce, mando l'originale: lo riduce il server
    }
    input.dispatchEvent(new Event('foto-pronta'));
  });
});

// Menu a tendina che salvano subito appena si sceglie
document.querySelectorAll('select[data-invia], input[data-invia]').forEach(s => s.addEventListener('change', () => s.form.submit()));

// Azioni irreversibili: chiedi conferma con una finestra dell'app, non con confirm() del browser,
// che alcuni browser (anche quello integrato di Claude) bloccano rispondendo «Annulla» (Giulia, 25/11/2026)
window.chiediConferma = function (testo, conferma) {
  return new Promise(risolvi => {
    const d = document.createElement('dialog');
    d.className = 'conferma-dlg';
    const p = document.createElement('p');
    p.textContent = testo;
    const tasti = document.createElement('div');
    tasti.className = 'conferma-tasti';
    const no = document.createElement('button');
    no.type = 'button'; no.className = 'bottone'; no.textContent = 'Annulla';
    const si = document.createElement('button');
    si.type = 'button'; si.className = 'bottone conferma-si'; si.textContent = conferma || 'Conferma';
    tasti.append(no, si);
    d.append(p, tasti);
    document.body.appendChild(d);
    let esito = false;
    const chiudi = v => { esito = v; d.close(); };
    no.addEventListener('click', () => chiudi(false));
    si.addEventListener('click', () => chiudi(true));
    d.addEventListener('close', () => { d.remove(); risolvi(esito); });
    if (typeof d.showModal === 'function') { d.showModal(); si.focus(); }
    else { d.remove(); risolvi(window.confirm(testo)); }  // browser molto vecchi
  });
};
document.querySelectorAll('[data-conferma]').forEach(b => {
  b.addEventListener('click', e => {
    if (b.dataset.confermato) { delete b.dataset.confermato; return; }
    e.preventDefault();
    window.chiediConferma(b.dataset.conferma, b.textContent.trim()).then(ok => {
      if (!ok) return;
      b.dataset.confermato = '1';
      if (b.form && b.form.requestSubmit) b.form.requestSubmit(b); else b.click();
    });
  });
});

// Evita doppi invii quando la rete è lenta
document.querySelectorAll('form').forEach(form => {
  form.addEventListener('submit', e => {
    if (form.dataset.inviato) { e.preventDefault(); return; }
    form.dataset.inviato = '1';
    const bottone = e.submitter;
    if (bottone && bottone.name) {
      // il bottone disabilitato non verrebbe inviato: ne copio il valore
      const h = document.createElement('input');
      h.type = 'hidden'; h.name = bottone.name; h.value = bottone.value;
      form.appendChild(h);
    }
    form.querySelectorAll('button').forEach(b => b.disabled = true);
  });
});

// ---------------------------------------------------------------- notifiche sul telefono
function chiaveInByte(b64) {
  const pad = '='.repeat((4 - b64.length % 4) % 4);
  const raw = atob((b64 + pad).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from([...raw].map(c => c.charCodeAt(0)));
}

function csrf() {
  return (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';
}

async function iscrivi(riquadro) {
  const reg = await navigator.serviceWorker.ready;
  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: chiaveInByte(riquadro.dataset.chiave),
    });
  }
  await fetch(riquadro.dataset.url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
    body: JSON.stringify(sub.toJSON()),
  });
}

(function () {
  const riquadro = document.getElementById('attiva-notifiche');
  if (!riquadro) return;
  const iphone = /iPhone|iPad|iPod/.test(navigator.userAgent);
  const installata = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone;
  if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
    const box = document.getElementById('notifiche-iphone');
    let nascosto = false;
    try { nascosto = localStorage.getItem('notifiche-iphone-chiuso') === '1'; } catch (e) {}
    if (iphone && !installata && !nascosto) {
      box.hidden = false;
      document.getElementById('chiudi-iphone').addEventListener('click', () => {
        box.hidden = true;
        try { localStorage.setItem('notifiche-iphone-chiuso', '1'); } catch (e) {}
      });
    }
    return;
  }
  if (Notification.permission === 'granted') {
    iscrivi(riquadro).catch(() => {});  // rinnova in silenzio
  } else if (Notification.permission === 'default') {
    riquadro.hidden = false;
    document.getElementById('bottone-notifiche').addEventListener('click', async () => {
      const esito = await Notification.requestPermission();
      if (esito === 'granted') {
        await iscrivi(riquadro).catch(() => {});
        riquadro.hidden = true;
      }
    });
  }
})();

// ---------------------------------------------------------------- chat e bacheca in stile WhatsApp
(function () {
  if (!document.querySelector('.wa')) return;
  // come WhatsApp: si parte dagli ultimi messaggi; dopo un voto si torna al sondaggio (#m…), sotto il titolo della chat
  const bersaglio = /^#m\d+$/.test(location.hash) ? document.querySelector(location.hash) : null;
  // a tutto schermo (Giulia, 23/11/2026) scorrono solo i messaggi, dentro il loro riquadro
  const sfondo = document.querySelector('.wa-sfondo');
  const dentro = document.body.classList.contains('in-chat') && sfondo;
  const fondo = () => bersaglio ? bersaglio.scrollIntoView({ block: 'center' })
    : dentro ? (sfondo.scrollTop = sfondo.scrollHeight) : window.scrollTo(0, document.documentElement.scrollHeight);
  fondo();
  window.addEventListener('load', fondo);
  // le foto e i video si caricano dopo e allungano la chat: finché non si tocca lo schermo la chat resta agganciata
  // all'ultimo messaggio (bug 22/11: si apriva a metà)
  if (sfondo) {
    let agganciata = true;
    const stacca = () => { agganciata = false; };
    ['touchstart', 'wheel', 'keydown', 'mousedown'].forEach(ev => window.addEventListener(ev, stacca, { once: true, passive: true }));
    setTimeout(stacca, 6000);
    ['load', 'loadedmetadata'].forEach(ev => sfondo.addEventListener(ev, () => { if (agganciata) fondo(); }, true));
    if (window.ResizeObserver) new ResizeObserver(() => { if (agganciata) fondo(); }).observe(sfondo);
  }
  // la tastiera dell'iPhone: la chat si restringe sopra la tastiera e resta sull'ultimo messaggio, come WhatsApp
  if (dentro && window.visualViewport) {
    const vv = window.visualViewport, radice = document.documentElement.style;
    const adatta = () => {
      // la pagina non deve scorrere: se il telefono la sposta per far posto alla tastiera, la barra con il nome
      // del gruppo uscirebbe dallo schermo (bug 25/11/2026). La riportiamo su e la chat si stringe sopra la tastiera
      if (window.scrollY) window.scrollTo(0, 0);
      const inFondo = sfondo.scrollTop + sfondo.clientHeight >= sfondo.scrollHeight - 60;
      radice.setProperty('--vv-h', vv.height + 'px');
      radice.setProperty('--vv-top', vv.offsetTop + 'px');
      document.body.classList.toggle('tastiera', window.innerHeight - vv.height > 120);
      if (inFondo) sfondo.scrollTop = sfondo.scrollHeight;
    };
    vv.addEventListener('resize', adatta);
    vv.addEventListener('scroll', adatta);
    window.addEventListener('scroll', () => { if (window.scrollY) window.scrollTo(0, 0); }, { passive: true });
    document.addEventListener('focusin', e => { if (e.target.closest('.wa-scrivi')) { setTimeout(adatta, 60); setTimeout(adatta, 350); } });
    adatta();
  }
  // bacheca: tocco sul fumetto (per l'ufficio) compare "Elimina"
  document.querySelector('.wa').addEventListener('click', e => {
    const msg = e.target.closest('.wa-msg.bacheca');
    if (msg && msg.querySelector('.wa-elimina') && !e.target.closest('button')) msg.classList.toggle('aperto');
  });
})();

// ---------------------------------------------------------------- chat (stile WhatsApp): aggiornamento, risposte, reazioni (Giulia, 22/11/2026)
(function () {
  const chat = document.getElementById('chat');
  if (!chat) return;
  const modulo = document.querySelector('.wa-scrivi');
  const csrf = modulo ? modulo.querySelector('[name=csrfmiddlewaretoken]').value : '';
  const dentro = document.body.classList.contains('in-chat');
  const fondo = () => dentro ? (chat.scrollTop = chat.scrollHeight) : window.scrollTo(0, document.documentElement.scrollHeight);
  const spunte = letto => ' <svg class="wa-spunte' + (letto ? ' lette' : '') + '" viewBox="0 0 18 12" role="img" aria-label="Inviato"><path d="M1 6l3.5 3.5L11 3M7 9.5L8 10.5 15 3"/></svg>';
  const el = (tag, classe, testo) => { const e = document.createElement(tag); if (classe) e.className = classe; if (testo != null) e.textContent = testo; return e; };

  // il campo di scrittura si allarga mentre scrivi
  const campo = document.querySelector('.wa-scrivi textarea');
  if (campo) campo.addEventListener('input', () => { campo.style.height = 'auto'; campo.style.height = Math.min(campo.scrollHeight, 130) + 'px'; });

  function ultimo() {
    const tutti = chat.querySelectorAll('.wa-msg');
    return tutti.length ? tutti[tutti.length - 1] : null;
  }

  // le reazioni sotto il fumetto: 👍 2 ❤️
  function mostraReazioni(b, reazioni) {
    let box = b.querySelector('.wa-reazioni');
    if (!box) { box = el('span', 'wa-reazioni'); b.insertBefore(box, b.querySelector('.wa-elimina')); }
    box.textContent = '';
    (reazioni || []).forEach(r => {
      const s = el('span', 'wa-reazione' + (r.mia ? ' mia' : ''), r.emoji);
      s.title = r.chi;
      if (r.n > 1) s.appendChild(el('b', '', String(r.n)));
      box.appendChild(s);
    });
    b.classList.toggle('con-reazioni', !!(reazioni && reazioni.length));
  }

  function citazione(r) {
    const a = el('a', 'wa-citazione q' + r.colore);
    a.href = '#m' + r.id; a.dataset.vai = 'm' + r.id;
    const t = el('span', 'wa-citazione-testi');
    t.appendChild(el('b', 'c' + r.colore, r.autore));
    t.appendChild(el('span', '', r.testo));
    a.appendChild(t);
    if (r.foto) { const i = el('img'); i.src = r.foto; i.alt = ''; a.appendChild(i); }
    return a;
  }

  function aggiungi(m) {
    const prec = ultimo();
    const nuovoGiorno = !prec || prec.dataset.giorno !== m.giorno;
    if (nuovoGiorno) {
      const d = el('div', 'wa-data');
      d.appendChild(el('span', '', m.etichetta_giorno));
      chat.appendChild(d);
    }
    const primo = nuovoGiorno || prec.dataset.autore !== String(m.autore_id);
    const riga = el('div', 'wa-riga' + (m.mio ? ' mia' : '') + (primo ? ' primo' : ''));
    riga.id = 'm' + m.id;
    if (!m.mio) {
      const tondo = el('span', 'wa-tondo' + (primo ? '' : ' vuoto'));
      if (primo && m.tondo.foto) { const i = el('img'); i.src = m.tondo.foto; i.alt = ''; tondo.appendChild(i); }
      else if (primo) tondo.textContent = m.tondo.iniziali;
      riga.appendChild(tondo);
    }
    const b = el('div', 'wa-msg' + (m.mio ? ' mio' : '') + (primo ? ' primo' : '') + (m.foto || m.video ? ' con-foto' : ''));
    Object.assign(b.dataset, { id: m.id, autore: m.autore_id, giorno: m.giorno, nome: m.mio ? 'Tu' : m.autore, colore: m.colore, breve: m.testo_breve });
    if (m.info) b.dataset.info = m.info;
    if (!m.eliminato && !m.sondaggio) b.dataset.rispondi = '1';
    if (!m.mio && primo) b.appendChild(el('span', 'wa-autore c' + m.colore, m.autore));
    if (m.risposta) b.appendChild(citazione(m.risposta));
    if (m.foto) {
      const l = el('a', 'wa-foto'); l.href = m.foto; l.target = '_blank';
      const i = el('img'); i.src = m.foto; i.alt = 'Foto di ' + m.autore; l.appendChild(i); b.appendChild(l);
    }
    if (m.video) {
      const v = el('video', 'wa-video'); v.src = m.video; v.controls = true; v.playsInline = true; v.preload = 'metadata'; b.appendChild(v);
    }
    if (m.documento) {
      const d = el('a', 'wa-doc'); d.href = m.documento; d.target = '_blank';
      d.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h9l4 4v14H6zM14 3v5h5M9 13h6M9 17h6"/></svg>';
      d.appendChild(el('span', '', m.documento_nome)); b.appendChild(d);
    }
    if (m.sondaggio) {
      const l = el('a', 'wa-testo', 'Sondaggio: ' + m.sondaggio.domanda + ' · tocca per votare');
      l.href = location.pathname + location.search + '#m' + m.id;
      l.addEventListener('click', () => setTimeout(() => location.reload(), 0));
      b.appendChild(l);
    } else if (m.testo || m.eliminato) {
      b.appendChild(el('span', 'wa-testo' + (m.eliminato ? ' eliminato' : ''), m.eliminato ? (m.testo ? m.testo + ' · eliminato' : 'Messaggio eliminato') : m.testo));
    }
    const o = el('span', 'wa-ora', m.ora);
    if (m.mio) o.insertAdjacentHTML('beforeend', spunte(m.letto));
    b.appendChild(o);
    mostraReazioni(b, m.reazioni);
    if (m.eliminabile) {
      const f = el('form', 'wa-elimina'); f.method = 'post'; f.hidden = true;
      [['csrfmiddlewaretoken', csrf], ['vista', 'chat'], ['chat', new URLSearchParams(location.search).get('chat')], ['messaggio', m.id], ['azione', 'elimina_chat']]
        .forEach(([n, v]) => { const i = el('input'); i.type = 'hidden'; i.name = n; i.value = v; f.appendChild(i); });
      b.appendChild(f);
    }
    riga.appendChild(b);
    chat.appendChild(riga);
  }

  async function aggiorna() {
    if (document.hidden) return;
    try {
      const r = await fetch(chat.dataset.url + '&dopo=' + chat.dataset.ultimo);
      const { messaggi, letto_fino, reazioni } = await r.json();
      // spunte blu: i miei messaggi letti da tutti
      chat.querySelectorAll('.wa-msg.mio').forEach(b => {
        if (Number(b.dataset.id) <= letto_fino) { const sp = b.querySelector('.wa-spunte'); if (sp) sp.classList.add('lette'); }
      });
      // le reazioni degli altri
      Object.entries(reazioni || {}).forEach(([id, rr]) => {
        const b = chat.querySelector('.wa-msg[data-id="' + id + '"]');
        if (b && JSON.stringify(rr.map(x => [x.emoji, x.n, x.mia])) !== b.dataset.firma) { mostraReazioni(b, rr); b.dataset.firma = JSON.stringify(rr.map(x => [x.emoji, x.n, x.mia])); }
      });
      if (!messaggi.length) return;
      const vuota = document.getElementById('chat-vuota');
      if (vuota) vuota.remove();
      const inFondo = dentro ? chat.scrollTop + chat.clientHeight >= chat.scrollHeight - 150
        : window.innerHeight + window.scrollY >= document.body.scrollHeight - 150;
      messaggi.forEach(aggiungi);
      chat.dataset.ultimo = messaggi[messaggi.length - 1].id;
      if (inFondo) fondo();
    } catch (e) { /* rete assente: riprova al giro dopo */ }
  }
  setInterval(aggiorna, 8000);
  document.addEventListener('visibilitychange', aggiorna);

  // ---- rispondi a un messaggio: la citazione sopra il campo di scrittura
  const barra = document.getElementById('wa-rispondi');
  const campoRisposta = document.getElementById('risposta-a');
  function rispondi(b) {
    if (!barra || !b.dataset.rispondi) return;
    campoRisposta.value = b.dataset.id;
    const q = barra.querySelector('.wa-citazione');
    q.className = 'wa-citazione q' + b.dataset.colore;
    q.querySelector('b').className = 'c' + b.dataset.colore;
    q.querySelector('b').textContent = b.dataset.nome;
    q.querySelector('.wa-citazione-testi > span').textContent = b.dataset.breve;
    barra.hidden = false;
    if (campo) campo.focus();
  }
  const annulla = document.getElementById('rispondi-togli');
  if (annulla) annulla.addEventListener('click', () => { campoRisposta.value = ''; barra.hidden = true; });

  // tocco sulla citazione: va al messaggio originale e lo illumina un attimo
  chat.addEventListener('click', e => {
    const q = e.target.closest('[data-vai]');
    if (!q) return;
    e.preventDefault();
    const riga = document.getElementById(q.dataset.vai);
    if (!riga) return;
    riga.scrollIntoView({ block: 'center', behavior: 'smooth' });
    riga.classList.remove('illumina'); void riga.offsetWidth; riga.classList.add('illumina');
  });

  // ---- tocco su un fumetto: il foglio con le reazioni e le azioni
  const foglio = document.getElementById('wa-azioni');
  let scelto = null;
  function chiudi() { if (foglio) foglio.hidden = true; if (scelto) scelto.classList.remove('scelto'); scelto = null; document.body.classList.remove('foglio-aperto'); }
  function apri(b) {
    if (!foglio) return;
    scelto = b;
    b.classList.add('scelto');
    const eliminato = !b.dataset.rispondi && !b.querySelector('.wa-sondaggio');
    foglio.querySelector('.wa-emoji').hidden = eliminato;
    foglio.querySelector('[data-azione=rispondi]').hidden = !b.dataset.rispondi;
    const info = foglio.querySelector('[data-azione=info]');
    info.hidden = !b.dataset.info; info.href = b.dataset.info || '#';
    foglio.querySelector('[data-azione=elimina]').hidden = !b.querySelector('.wa-elimina');
    const mie = [...b.querySelectorAll('.wa-reazione.mia')].map(s => s.firstChild.textContent);
    foglio.querySelectorAll('[data-emoji]').forEach(x => x.classList.toggle('mia', mie.includes(x.dataset.emoji)));
    if (eliminato && info.hidden && !b.querySelector('.wa-elimina')) { scelto = null; b.classList.remove('scelto'); return; }
    foglio.hidden = false;
    document.body.classList.add('foglio-aperto');
  }
  chat.addEventListener('click', e => {
    if (e.target.closest('a, button, video, form, input, [data-vai]')) return;
    const b = e.target.closest('.wa-msg');
    if (b && !b.classList.contains('bacheca')) apri(b);
  });
  if (foglio) {
    foglio.addEventListener('click', async e => {
      if (e.target.closest('[data-chiudi]')) { chiudi(); return; }
      const b = scelto;
      if (!b) return;
      const emoji = e.target.closest('[data-emoji]');
      if (emoji) {
        chiudi();
        const dati = new FormData(); dati.append('emoji', emoji.dataset.emoji); dati.append('csrfmiddlewaretoken', csrf);
        try {
          const r = await fetch(chat.dataset.reazione.replace('/0/', '/' + b.dataset.id + '/'), { method: 'POST', body: dati, headers: { 'X-Requested-With': 'fetch' } });
          if (r.ok) { const j = await r.json(); mostraReazioni(b, j.reazioni); }
        } catch (err) { /* rete assente */ }
        return;
      }
      const azione = e.target.closest('[data-azione]');
      if (!azione) return;
      if (azione.dataset.azione === 'rispondi') { e.preventDefault(); chiudi(); rispondi(b); }
      else if (azione.dataset.azione === 'elimina') {
        e.preventDefault(); chiudi();
        window.chiediConferma('Eliminare questo messaggio per tutti?', 'Elimina').then(ok => { if (ok) b.querySelector('.wa-elimina').submit(); });
      }
    });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') chiudi(); });
  }

  // ---- scorri come WhatsApp: verso destra = rispondi; verso sinistra un tuo messaggio = chi l'ha letto
  let fumetto = null, x0 = 0, y0 = 0, dx = 0, deciso = false;
  chat.addEventListener('touchstart', e => {
    fumetto = e.target.closest('.wa-msg');
    if (!fumetto || e.target.closest('video, .wa-sondaggio')) { fumetto = null; return; }
    x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; dx = 0; deciso = false;
  }, { passive: true });
  chat.addEventListener('touchmove', e => {
    if (!fumetto) return;
    dx = e.touches[0].clientX - x0;
    const dy = e.touches[0].clientY - y0;
    if (!deciso) {
      if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return;
      if (Math.abs(dy) > Math.abs(dx)) { fumetto = null; return; }
      deciso = true;
    }
    const ok = dx > 0 ? fumetto.dataset.rispondi : fumetto.dataset.info;
    if (!ok) return;
    const corsa = Math.max(-90, Math.min(dx, 90));
    fumetto.style.transform = 'translateX(' + corsa + 'px)';
    fumetto.classList.toggle('pronto-rispondi', dx > 60);
    fumetto.classList.toggle('pronto-info', dx < -60);
  }, { passive: true });
  chat.addEventListener('touchend', () => {
    if (!fumetto) return;
    const b = fumetto;
    b.style.transform = '';
    b.classList.remove('pronto-rispondi', 'pronto-info');
    fumetto = null;
    if (dx > 60 && b.dataset.rispondi) { if (navigator.vibrate) navigator.vibrate(15); rispondi(b); }
    else if (dx < -60 && b.dataset.info) location.href = b.dataset.info;
  });
})();

// ---------------------------------------------------------------- tastierino PIN (pagina di accesso)
document.querySelectorAll('[data-tastierino]').forEach(tastierino => {
  const campo = document.getElementById(tastierino.dataset.tastierino);
  if (!campo) return;
  tastierino.hidden = false;
  tastierino.addEventListener('click', e => {
    const tasto = e.target.closest('[data-tasto]');
    if (!tasto) return;
    campo.value = tasto.dataset.tasto === 'canc' ? campo.value.slice(0, -1) : campo.value + tasto.dataset.tasto;
  });
});

// ---------------------------------------------------------------- accesso e tessere
document.querySelectorAll('[data-stampa]').forEach(b => b.addEventListener('click', () => window.print()));
(function () {
  // arrivando dal QR della tessera il nome utente è già scritto: si parte dal PIN
  const nome = document.getElementById('id_username');
  const pin = document.getElementById('id_password');
  if (!nome || !pin) return;
  (nome.value ? pin : nome).focus();
})();

// "Oggi" / "Domani mattina": compila la data con un tocco
document.querySelectorAll('.mn-quando-rapido button').forEach(b => b.addEventListener('click', () => {
  const campo = b.closest('form').querySelector('input[name=da_fare_il]');
  if (campo) campo.value = b.dataset.data;
}));

// video scelto: lo dico sul pulsante (non lo riduco: va inviato così)
document.querySelectorAll('input[type=file][name=video]').forEach(input => input.addEventListener('change', () => {
  const f = input.files[0];
  const etichetta = input.closest('label');
  if (!f) return;
  const mb = (f.size / 1048576).toFixed(0);
  etichetta.querySelector('span').textContent = f.size > 50 * 1048576 ? '⚠️ Video troppo grande (' + mb + ' MB): massimo 50' : '🎥 Video pronto (' + mb + ' MB)';
  etichetta.classList.add('pronta');
}));

// Statistiche: "Leggi i numeri dalla foto" riempie il modulo (si controlla prima di salvare)
document.querySelectorAll('form[data-lettura] [data-leggi]').forEach(btn => {
  btn.addEventListener('click', async () => {
    const form = btn.form, esito = form.querySelector('.st-esito'), foto = form.querySelector('input[type=file]');
    const scrivi = (t, ok) => { esito.hidden = false; esito.textContent = t; esito.classList.toggle('ok', !!ok); };
    if (!foto.files.length) { foto.click(); return; }
    const dati = new FormData();
    dati.append('foto', foto.files[0]);
    dati.append('tipo', form.dataset.lettura);
    dati.append('csrfmiddlewaretoken', form.querySelector('[name=csrfmiddlewaretoken]').value);
    btn.disabled = true; const testo = btn.textContent; btn.textContent = '⏳ Sto leggendo…';
    if (btn.hidden) scrivi('⏳ Sto leggendo i numeri dalla foto…');
    try {
      const r = await fetch('/turni/statistiche/leggi-foto/', { method: 'POST', body: dati });
      const j = await r.json();
      if (!r.ok) { scrivi(j.errore || 'Non riesco a leggere la foto.'); return; }
      let n = 0;
      for (const [nome, valore] of Object.entries(j.campi)) {
        const radio = form.querySelector(`input[type=radio][name="${nome}"][value="${valore}"]`);
        const campo = form.querySelector(`input[type=text][name="${nome}"], input[type=date][name="${nome}"]`);
        if (radio) { radio.checked = true; n++; }
        else if (campo) { campo.value = valore; campo.classList.add('letto'); n++; }
      }
      const quando = form.querySelector('[data-quando]');
      if (quando) {
        // produzione: giorno e turno letti dal display, sopra l'avviso in rosso
        const giorno = form.querySelector('input[name=data]').value, f = form.querySelector('input[name=fascia]:checked');
        const sigle = { '1T': ['1T', 'f-mattina'], '2T': ['2T', 'f-pomeriggio'], 'N': ['N', 'f-notte'] };
        if (giorno) {
          const t = new Date(giorno + 'T12:00').toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long' });
          quando.querySelector('[data-giorno]').textContent = t.charAt(0).toUpperCase() + t.slice(1);
        }
        if (f && sigle[f.value]) { const s = quando.querySelector('[data-sigla]'); s.textContent = sigle[f.value][0]; s.className = 'cal-sigla pr-sigla ' + sigle[f.value][1]; }
        quando.hidden = false; esito.hidden = true;
      } else scrivi(`✓ Letti ${n} valori: controllali prima di salvare.`, true);
    } catch (e) {
      scrivi('Senza rete: scrivi i numeri a mano.');
    } finally { btn.disabled = false; btn.textContent = testo; }
  });
});

// Analisi: un solo tasto Foto; appena la foto è pronta i numeri si leggono da soli (Giulia, 12/11)
document.querySelectorAll('input[type=file][data-leggi-subito]').forEach(input => {
  input.addEventListener('foto-pronta', () => { const b = input.form.querySelector('[data-leggi]'); if (b && input.files.length) b.click(); });
});

document.querySelectorAll('[data-condividi]').forEach(btn => {
  btn.addEventListener('click', async () => {
    const testo = document.getElementById(btn.dataset.condividi).value;
    if (navigator.share) { try { await navigator.share({ text: testo }); return; } catch (e) { return; } }
    location.href = 'https://wa.me/?text=' + encodeURIComponent(testo);
  });
});

// Assistente digitale: fumetto in basso a destra, chat a tutto schermo, voce con il microfono del telefono
(() => {
  const apri = document.getElementById('as-apri');
  if (!apri) return;
  const pannello = document.getElementById('as-pannello'), corpo = document.getElementById('as-corpo');
  const modulo = document.getElementById('as-scrivi'), campo = document.getElementById('as-testo');
  const sugg = document.getElementById('as-suggerimenti'), mic = document.getElementById('as-mic');
  const csrf = modulo.querySelector('[name=csrfmiddlewaretoken]').value;
  let caricata = false, occupato = false;

  const invia = (url, dati) => fetch(url, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: JSON.stringify(dati || {}),
  }).then(r => r.json().then(j => (r.ok ? j : Promise.reject(j.errore || 'Errore'))));

  const fumetto = (chi, testo) => {
    const d = document.createElement('div');
    d.className = 'as-msg ' + chi;
    d.textContent = testo;
    corpo.appendChild(d);
    corpo.scrollTop = corpo.scrollHeight;
    return d;
  };

  const proposta = p => {
    const d = document.createElement('div');
    d.className = 'as-proposta';
    d.innerHTML = '<p></p><div><button type="button" class="si">✓ Conferma</button><button type="button" class="no">Annulla</button></div>';
    d.querySelector('p').textContent = p.riassunto;
    d.querySelectorAll('button').forEach(b => b.addEventListener('click', async () => {
      d.querySelectorAll('button').forEach(x => (x.disabled = true));
      try {
        const j = await invia('/turni/assistente/conferma/', { id: p.id, accetta: b.classList.contains('si') });
        d.replaceWith(fumetto('esito', j.esito));
      } catch (e) { fumetto('errore', e); }
    }));
    corpo.appendChild(d);
    corpo.scrollTop = corpo.scrollHeight;
  };

  const suggerimenti = elenco => {
    sugg.innerHTML = '';
    (elenco || []).forEach(t => {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = t;
      b.addEventListener('click', () => manda(t));
      sugg.appendChild(b);
    });
  };

  const file = document.getElementById('as-file'), allegato = document.getElementById('as-allegato');
  file.addEventListener('change', () => { allegato.hidden = !file.files.length; });
  document.getElementById('as-togli').addEventListener('click', () => { file.value = ''; allegato.hidden = true; });

  async function manda(testo) {
    testo = (testo || '').trim();
    const foto = file.files[0];
    if ((!testo && !foto) || occupato) return;
    occupato = true;
    sugg.innerHTML = '';
    fumetto('io', (foto ? '📷 ' : '') + testo);
    campo.value = '';
    const attesa = fumetto('bot attesa', '…');
    try {
      let j;
      if (foto) {
        const dati = new FormData();
        dati.append('testo', testo);
        dati.append('foto', foto);
        file.value = ''; allegato.hidden = true;
        j = await fetch('/turni/assistente/', { method: 'POST', headers: { 'X-CSRFToken': csrf }, body: dati })
          .then(r => r.json().then(x => (r.ok ? x : Promise.reject(x.errore || 'Errore'))));
      } else {
        j = await invia('/turni/assistente/', { testo });
      }
      attesa.remove();
      fumetto('bot', j.risposta);
      j.proposte.forEach(proposta);
    } catch (e) {
      attesa.remove();
      fumetto('errore', typeof e === 'string' ? e : 'Senza rete: riprova.');
    } finally { occupato = false; }
  }

  async function carica() {
    if (caricata) return;
    caricata = true;
    try {
      const j = await fetch('/turni/assistente/').then(r => r.json());
      j.messaggi.forEach(m => fumetto(m.chi, m.testo));
      j.proposte.forEach(proposta);
      suggerimenti(j.suggerimenti);
    } catch (e) { /* senza rete: resta il saluto */ }
  }

  apri.addEventListener('click', () => { pannello.hidden = false; apri.hidden = true; document.body.classList.add('as-aperto'); carica(); });
  document.getElementById('as-chiudi').addEventListener('click', () => { pannello.hidden = true; apri.hidden = false; document.body.classList.remove('as-aperto'); });
  document.getElementById('as-nuova').addEventListener('click', async () => {
    const j = await invia('/turni/assistente/nuova/');
    corpo.querySelectorAll('.as-msg:not(:first-child), .as-proposta').forEach(x => x.remove());
    suggerimenti(j.suggerimenti);
  });
  modulo.addEventListener('submit', e => { e.preventDefault(); manda(campo.value); });

  // voce: il riconoscimento vocale del telefono (Safari e Chrome), in italiano
  const Riconosci = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (Riconosci) {
    mic.hidden = false;
    mic.addEventListener('click', () => {
      const r = new Riconosci();
      r.lang = 'it-IT';
      r.interimResults = true;
      mic.classList.add('ascolto');
      campo.placeholder = 'Ti ascolto…';
      r.onresult = ev => {
        const t = [...ev.results].map(x => x[0].transcript).join('');
        campo.value = t;
        if (ev.results[ev.results.length - 1].isFinal) manda(t);
      };
      r.onend = r.onerror = () => { mic.classList.remove('ascolto'); campo.placeholder = 'Scrivi un messaggio…'; };
      r.start();
    });
  }
})();

// Valori letti dalla foto: prima di salvare l'utente vede il riepilogo e conferma (o torna a correggere)
document.querySelectorAll('form[data-lettura]').forEach(form => {
  form.addEventListener('submit', e => {
    if (form.dataset.confermato || !form.querySelector('input.letto')) return;
    e.preventDefault();
    // il blocco dei doppi invii ha già segnato il modulo come inviato: lo riapro finché non si conferma
    delete form.dataset.inviato;
    form.querySelectorAll('button').forEach(b => (b.disabled = false));
    const righe = [];
    const nomi = { campione: 'Campione', fascia: 'Turno' };
    const giorno = form.querySelector('input[name=data]');
    if (giorno && giorno.value) righe.push(['Giorno', giorno.value.split('-').reverse().join('/')]);
    form.querySelectorAll('input[type=radio]:checked').forEach(r => righe.push([nomi[r.name] || r.name, r.nextElementSibling.textContent]));
    form.querySelectorAll('.pr-riga').forEach(l => {
      const i = l.querySelector('input');
      if (i.value.trim()) righe.push([l.querySelector('span').textContent.trim(), i.value + ' ' + (l.querySelector('i')?.textContent || '')]);
    });
    const v = document.createElement('div');
    v.className = 'st-conferma';
    v.innerHTML = '<div class="st-conferma-box"><h2>Controlla i valori</h2><p class="tenue">Letti dalla foto: sono giusti?</p><table></table>' +
      '<button type="button" class="bottone pieno piena-larghezza si">✓ Conferma e salva</button>' +
      '<button type="button" class="bottone piena-larghezza no">✏️ Correggi</button></div>';
    const t = v.querySelector('table');
    righe.filter(r => r[0]).forEach(([n, x]) => { const tr = t.insertRow(); tr.insertCell().textContent = n; tr.insertCell().textContent = x; });
    v.querySelector('.si').addEventListener('click', () => { form.dataset.confermato = '1'; v.remove(); form.requestSubmit(); });
    v.querySelector('.no').addEventListener('click', () => { v.remove(); form.querySelector('input.letto')?.focus(); });
    document.body.appendChild(v);
  });
});

// Manutenzione: "Inquadra il QR code" con la fotocamera (dove il browser sa leggere i QR), altrimenti si scrive il codice
document.querySelectorAll('form[data-qr]').forEach(form => {
  const avvia = form.querySelector('.qr-avvia'), mirino = form.querySelector('.qr-mirino'), video = mirino.querySelector('video');
  avvia.addEventListener('click', async () => {
    if (!('BarcodeDetector' in window) || !navigator.mediaDevices) {
      avvia.textContent = 'Usa la fotocamera del telefono sul QR, oppure scrivi il codice qui sotto';
      avvia.disabled = true;
      return;
    }
    try {
      const flusso = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
      video.srcObject = flusso; await video.play();
      mirino.hidden = false; avvia.hidden = true;
      const lettore = new BarcodeDetector({ formats: ['qr_code'] });
      const cerca = async () => {
        const trovati = await lettore.detect(video).catch(() => []);
        if (trovati.length) {
          flusso.getTracks().forEach(t => t.stop());
          form.querySelector('[name=c]').value = trovati[0].rawValue;
          form.submit();
          return;
        }
        requestAnimationFrame(cerca);
      };
      cerca();
    } catch (e) {
      avvia.textContent = 'Fotocamera non disponibile: scrivi il codice qui sotto';
      avvia.disabled = true;
    }
  });
});

// ---------------------------------------------------------------- foto profilo: si invia appena scelta
// prima la converto in JPEG nel telefono: le foto dell'iPhone (HEIC) il server non le sa leggere (bug segnalato l'11/11)
document.querySelectorAll('input[type=file][data-invia-subito]').forEach(input => {
  input.addEventListener('change', async () => {
    if (!input.files.length) return;
    const piu = input.closest('label') && input.closest('label').querySelector('.ig-piu');
    if (piu) piu.textContent = '…';
    if (window.DataTransfer && window.createImageBitmap) {
      try {
        const dt = new DataTransfer();
        dt.items.add(await riduci(input.files[0]));
        input.files = dt.files;
      } catch (e) {
        // il browser non riesce a leggerla: mando l'originale e il server dice se non va
      }
    }
    input.form.submit();
  });
});

// ---------------------------------------------------------------- tasto "indietro": torna da dove si è arrivati
// Ogni pagina ricorda la schermata da cui è stata aperta (anche dopo aver inviato un modulo nella pagina stessa);
// il tasto porta lì e dice il suo nome. Se la pagina è stata aperta direttamente, resta il tasto scritto nel template.
(function () {
  const NOMI = [
    [/^\/turni\/(oggi\/)?$/, 'Oggi'],
    [/^\/turni\/miei\/$/, 'Area personale'],
    [/^\/turni\/pulizie\/piazzale\//, 'Piazzale'],
    [/^\/turni\/pulizie\/$/, 'Pulizia'],
    [/^\/turni\/capoturno\/$/, 'Verifica pulizie'],
    [/^\/turni\/archivio\//, 'Archivio'],
    [/^\/turni\/messaggi\//, 'Messaggi'],
    [/^\/turni\/settimana\/$/, 'Turni di tutti'],
  ];
  const qui = location.pathname;
  let da = null;
  try {
    const tornando = sessionStorage.getItem('indietro:tornando');
    sessionStorage.removeItem('indietro:tornando');
    if (tornando !== qui && document.referrer) {
      const r = new URL(document.referrer);
      if (r.origin === location.origin && r.pathname !== qui && !r.pathname.includes('/accesso/')) {
        sessionStorage.setItem('indietro:' + qui, r.pathname + r.search);
      }
    }
    da = sessionStorage.getItem('indietro:' + qui);
  } catch (e) { return; }
  if (!da) return;
  const destinazione = new URL(da, location.origin).pathname;
  const nome = (NOMI.find(([re]) => re.test(destinazione)) || [])[1] || 'Indietro';
  document.querySelectorAll('a.tasto-indietro').forEach(a => {
    a.href = da;
    const testo = [...a.childNodes].reverse().find(n => n.nodeType === 3 && n.textContent.trim());
    if (testo) testo.textContent = nome;
    // tornando indietro, la pagina di arrivo non deve "ricordare" questa come provenienza
    a.addEventListener('click', () => { try { sessionStorage.setItem('indietro:tornando', destinazione); } catch (e) {} });
  });
})();

// ---------------------------------------------------------------- tasto indietro sulla riga del titolo (come Instagram)
(function () {
  document.querySelectorAll('a.tasto-indietro:not([data-resta])').forEach(a => {
    const nome = a.textContent.trim();
    if (nome) a.setAttribute('aria-label', 'Indietro: ' + nome);
    // il primo titolo dopo il tasto: lì dentro la freccia, così non occupa una riga sua
    let el = a.nextElementSibling;
    for (let i = 0; el && i < 3; i++, el = el.nextElementSibling) {
      const h = el.matches('h1, h2') ? el : el.querySelector('h1');
      if (h) {
        const riga = h.parentElement && h.parentElement.classList.contains('naviga') ? h.parentElement : h;
        riga.classList.add('ha-indietro');
        riga.insertBefore(a, riga.firstChild);
        return;
      }
    }
  });
})();


// Fermo impianto facoltativo (Manutenzione in corso, Programma): la spunta mostra i campi del fermo
(function () {
  const c = document.getElementById('mc-fermo'), d = document.getElementById('mc-fermo-dati');
  if (c && d) c.addEventListener('change', () => { d.hidden = !c.checked; });
})();

// Programma riunione: cerca un nome, "Tutti", conteggio degli invitati
(function () {
  const f = document.getElementById('rn-filtro'), elenco = document.querySelector('.rn-persone');
  if (!f || !elenco) return;
  const righe = [...elenco.querySelectorAll('label')], conta = document.getElementById('rn-conta');
  const aggiorna = () => { const n = elenco.querySelectorAll('input:checked').length; if (conta) conta.textContent = n ? n + ' scelti' : ''; };
  f.addEventListener('input', () => { const q = f.value.trim().toLowerCase(); righe.forEach(l => { l.hidden = !!q && !l.dataset.nome.includes(q); }); });
  const tutti = document.getElementById('rn-tutti');
  if (tutti) tutti.addEventListener('click', () => {
    const visibili = righe.filter(l => !l.hidden).map(l => l.querySelector('input'));
    const giaTutti = visibili.every(c => c.checked);
    visibili.forEach(c => { c.checked = !giaTutti; });
    aggiorna();
  });
  elenco.addEventListener('change', aggiorna);
  aggiorna();
})();

// Turni di tutti: la testa con settimana e giorni si ferma subito sotto la barra in alto
(function () {
  const barra = document.querySelector('.barra');
  if (barra && document.querySelector('.st-testa, .wa-testa')) document.documentElement.style.setProperty('--alto-barra', barra.offsetHeight + 'px');
  // il nome dell'area (Impianto 1…) resta fisso sotto la testa finché non arriva l'area dopo (Giulia, 12/11)
  const testa = document.querySelector('.st-testa');
  if (testa) document.documentElement.style.setProperty('--alto-testa', testa.offsetHeight + 'px');
})();

// Anagrafica: scelto il dipendente, la pagina si aggiorna da sola
document.querySelectorAll('select[data-invia-subito-select]').forEach(s => s.addEventListener('change', () => s.form.submit()));


// Chat · foto scattata o scelta: la riduco in JPEG (anche le HEIC dell'iPhone) e la mostro prima di inviarla
(function () {
  const inputs = document.querySelectorAll('input[data-foto-chat]');
  const pronta = document.getElementById('foto-pronta');
  if (!inputs.length || !pronta) return;
  const togli = () => { inputs.forEach(i => { i.value = ''; }); pronta.hidden = true; };
  // il video ci mette un po' a partire: lo dico, così non si tocca Invia due volte
  const modulo = inputs[0].form;
  modulo.addEventListener('submit', () => {
    if ([...inputs].some(i => i.files.length && (i.files[0].type || '').startsWith('video/'))) pronta.querySelector('span').textContent = 'Invio del video in corso…';
  });
  inputs.forEach(input => input.addEventListener('change', async () => {
    if (!input.files.length) return;
    inputs.forEach(altro => { if (altro !== input) altro.value = ''; });
    const menu = input.form.querySelector('.wa-piu'); if (menu) menu.open = false;
    if (window.DataTransfer && window.createImageBitmap) {
      try { const dt = new DataTransfer(); dt.items.add(await riduci(input.files[0])); input.files = dt.files; } catch (e) { /* la riduce il server */ }
    }
    // video (Giulia, 22/11/2026): l'anteprima è il video stesso, fermo sul primo fotogramma
    const f = input.files[0], video = (f.type || '').startsWith('video/');
    const img = pronta.querySelector('img'), vid = pronta.querySelector('video'), testo = pronta.querySelector('span');
    img.hidden = video; if (vid) vid.hidden = !video;
    if (video && vid) vid.src = URL.createObjectURL(f) + '#t=0.1'; else img.src = URL.createObjectURL(f);
    testo.textContent = video
      ? (f.size > 100 * 1048576 ? '⚠️ Video troppo grande (massimo 100 MB)' : 'Video pronto: scrivi un commento o tocca Invia')
      : 'Foto pronta: scrivi un commento o tocca Invia';
    pronta.hidden = false;
  }));
  const x = document.getElementById('foto-togli');
  if (x) x.addEventListener('click', togli);
})();

// Chat · documento scelto dal "+": ne mostro il nome prima di inviarlo (Giulia, 12/11)
(function () {
  const input = document.querySelector('input[data-doc-chat]');
  const pronto = document.getElementById('doc-pronto');
  if (!input || !pronto) return;
  input.addEventListener('change', () => {
    if (!input.files.length) { pronto.hidden = true; return; }
    const f = input.files[0];
    const menu = input.form.querySelector('.wa-piu'); if (menu) menu.open = false;
    pronto.querySelector('span').textContent = f.size > 15 * 1048576 ? '⚠️ ' + f.name + ': troppo grande (massimo 15 MB)' : f.name + ': scrivi un commento o tocca Invia';
    pronto.hidden = false;
  });
  document.getElementById('doc-togli').addEventListener('click', () => { input.value = ''; pronto.hidden = true; });
})();

// Info gruppo: la lente filtra i membri per nome
(function () {
  const lente = document.querySelector('[data-apri-filtro]');
  const filtro = document.querySelector('[data-filtro-membri]');
  if (!lente || !filtro) return;
  lente.addEventListener('click', () => { filtro.hidden = !filtro.hidden; if (!filtro.hidden) filtro.focus(); });
  filtro.addEventListener('input', () => {
    const q = filtro.value.trim().toLowerCase();
    document.querySelectorAll('.ci-persona[data-nome]').forEach(r => { r.hidden = q && !r.dataset.nome.includes(q); });
  });
})();


// ---------------------------------------------------------------- PDF e foto con il tasto indietro (Giulia, 13/11/2026)
// aperti da soli, sul telefono l'app a tutto schermo non ha modo di tornare indietro: li apro nella pagina «vedi»
(function () {
  const FOTO = /\/turni\/(foto\/\d+|foto\/allegato\/\d+|messaggi\/foto\/\d+|messaggi\/video\/\d+|statistiche\/analisi\/\d+\/foto|produzione\/\d+\/foto|manutenzione\/fermi\/\d+\/foto\/\w+|manutenzione\/foto\/\w+\/\d+)\/$/;
  const PDF = /\/pdf\/$/;
  document.addEventListener('click', e => {
    const a = e.target.closest('a[href]');
    if (!a || a.closest('[data-vedi-no]') || e.defaultPrevented) return;
    let url;
    try { url = new URL(a.href, location.href); } catch (err) { return; }
    if (url.origin !== location.origin || location.pathname === '/turni/vedi/') return;
    const doc = /\/turni\/messaggi\/documento\/\d+\/$/.test(url.pathname) && /\.pdf$/i.test(a.textContent.trim());
    if (!(PDF.test(url.pathname) || FOTO.test(url.pathname) || doc)) return;
    e.preventDefault();
    const q = new URLSearchParams({ u: url.pathname + url.search });
    if (doc) { q.set('tipo', 'pdf'); q.set('nome', a.textContent.trim()); }
    if (a.dataset.video) { q.set('tipo', 'video'); q.set('nome', a.title || 'Video'); }
    location.href = '/turni/vedi/?' + q.toString();
  });
  // «Indietro»: torna alla pagina di prima
  document.querySelectorAll('[data-indietro]').forEach(a => a.addEventListener('click', e => {
    if (history.length > 1 && document.referrer.startsWith(location.origin)) { e.preventDefault(); history.back(); }
  }));
  // «Salva, stampa o invia»: il foglio di condivisione del telefono (File, Stampa, Mail…); altrimenti si scarica
  document.querySelectorAll('[data-condividi]').forEach(b => b.addEventListener('click', async () => {
    const url = b.dataset.condividi;
    try {
      const r = await fetch(url, { credentials: 'same-origin' });
      const blob = await r.blob();
      const nome = (b.dataset.nome || 'documento').replace(/[\\/:*?"<>|]/g, '') + (b.dataset.pdf ? (/\.pdf$/i.test(b.dataset.nome) ? '' : '.pdf') : '.jpg');
      const file = new File([blob], nome, { type: blob.type });
      if (navigator.canShare && navigator.canShare({ files: [file] })) { await navigator.share({ files: [file] }); return; }
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob); a.download = nome; document.body.appendChild(a); a.click(); a.remove();
    } catch (err) { /* annullato */ }
  }));
})();

// ---------------------------------------------------------------- mentre si scrive, la barra in basso sparisce (Giulia, 13/11/2026)
(function () {
  const scrive = el => el && (el.tagName === 'TEXTAREA' || (el.tagName === 'INPUT' && /^(text|search|email|number|tel|url|password)$/.test(el.type)));
  document.addEventListener('focusin', e => { if (scrive(e.target)) document.body.classList.add('scrive'); });
  document.addEventListener('focusout', e => { if (scrive(e.target)) setTimeout(() => { if (!scrive(document.activeElement)) document.body.classList.remove('scrive'); }, 50); });
})();


// Gestione accessi: «Quale ufficio» compare solo se il ruolo è «Ufficio» (Giulia, 13/11/2026)
document.querySelectorAll('select[data-mostra-se]').forEach(s => {
  const altro = document.querySelector(s.dataset.mostra);
  if (!altro) return;
  const aggiorna = () => { altro.hidden = s.value !== s.dataset.mostraSe; };
  s.addEventListener('change', aggiorna);
  aggiorna();
});

// Richiedi turno extra: «+ Aggiungi un ruolo» mostra una riga in più, la × la toglie (Giulia, 25/11/2026)
document.querySelectorAll('[data-ex-ruoli]').forEach(box => {
  const aggiungi = box.querySelector('[data-ex-aggiungi]');
  const righe = [...box.querySelectorAll('[data-ex-riga]')];
  const mostra = (riga, si) => {
    riga.hidden = !si;
    riga.querySelectorAll('select, input').forEach(c => { c.disabled = !si; if (!si) c.value = c.tagName === 'INPUT' ? '1' : ''; });
  };
  const aggiorna = () => { aggiungi.hidden = righe.every(r => !r.hidden); };
  aggiungi.addEventListener('click', () => {
    const riga = righe.find(r => r.hidden);
    if (riga) { mostra(riga, true); riga.querySelector('select').focus(); }
    aggiorna();
  });
  righe.forEach(r => r.querySelector('[data-ex-togli]').addEventListener('click', () => { mostra(r, false); aggiorna(); }));
  aggiorna();
});

// Gestione accessi: scelto il nome, il ruolo va su quello attuale della persona (così un nuovo PIN non la declassa)
document.querySelectorAll('select[data-ruolo-in]').forEach(s => {
  const ruolo = document.querySelector(s.dataset.ruoloIn);
  if (!ruolo) return;
  s.addEventListener('change', () => { const o = s.selectedOptions[0]; if (o && o.dataset.ruolo) ruolo.value = o.dataset.ruolo; });
});
