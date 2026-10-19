// Registra il service worker: rende l'app installabile sulla schermata Home.
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}

// Le foto del telefono pesano diversi MB: prima dell'invio le riduco a 1600px in JPEG.
const LATO_MAX = 1600;

async function riduci(file) {
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
    const files = [...input.files].slice(0, 12);
    const etichetta = input.closest('label');
    if (!files.length) return;
    etichetta.querySelector('span').textContent = files.length > 1 ? files.length + ' foto pronte' : 'Foto pronta';
    etichetta.classList.add('pronta');
    if (!window.DataTransfer || !window.createImageBitmap) return;
    try {
      const dt = new DataTransfer();
      for (const f of files) dt.items.add(await riduci(f));
      input.files = dt.files;
    } catch (e) {
      // se il browser non ci riesce, mando l'originale: lo riduce il server
    }
  });
});

// Menu a tendina che salvano subito appena si sceglie
document.querySelectorAll('select[data-invia], input[data-invia]').forEach(s => s.addEventListener('change', () => s.form.submit()));

// Azioni irreversibili: chiedi conferma (il click arriva prima dell'invio del modulo)
document.querySelectorAll('[data-conferma]').forEach(b => {
  b.addEventListener('click', e => {
    if (!confirm(b.dataset.conferma)) e.preventDefault();
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
  // come WhatsApp: si parte dagli ultimi messaggi
  const fondo = () => window.scrollTo(0, document.documentElement.scrollHeight);
  fondo();
  window.addEventListener('load', fondo);
  // tocco sul fumetto (proprio, o qualsiasi per l'ufficio): compare "Elimina"
  document.querySelector('.wa').addEventListener('click', e => {
    const msg = e.target.closest('.wa-msg');
    if (msg && msg.querySelector('.wa-elimina') && !e.target.closest('button')) msg.classList.toggle('aperto');
  });
})();

// ---------------------------------------------------------------- chat (stile WhatsApp) che si aggiorna da sola
(function () {
  const chat = document.getElementById('chat');
  if (!chat) return;
  const fondo = () => window.scrollTo(0, document.documentElement.scrollHeight);

  // il campo di scrittura si allarga mentre scrivi
  const campo = document.querySelector('.wa-scrivi textarea');
  if (campo) campo.addEventListener('input', () => { campo.style.height = 'auto'; campo.style.height = Math.min(campo.scrollHeight, 130) + 'px'; });

  function ultimo() {
    const tutti = chat.querySelectorAll('.wa-msg');
    return tutti.length ? tutti[tutti.length - 1] : null;
  }

  function aggiungi(m) {
    const prec = ultimo();
    const nuovoGiorno = !prec || prec.dataset.giorno !== m.giorno;
    if (nuovoGiorno) {
      const d = document.createElement('div');
      d.className = 'wa-data';
      const s = document.createElement('span');
      s.textContent = m.etichetta_giorno;
      d.appendChild(s);
      chat.appendChild(d);
    }
    const primo = nuovoGiorno || prec.dataset.autore !== String(m.autore_id);
    const b = document.createElement('div');
    b.className = 'wa-msg' + (m.mio ? ' mio' : '') + (primo ? ' primo' : '');
    b.dataset.id = m.id; b.dataset.autore = m.autore_id; b.dataset.giorno = m.giorno;
    if (!m.mio && primo) {
      const a = document.createElement('span');
      a.className = 'wa-autore c' + m.colore;
      a.textContent = m.autore;
      b.appendChild(a);
    }
    const t = document.createElement('span');
    t.className = 'wa-testo' + (m.eliminato ? ' eliminato' : '');
    t.textContent = m.eliminato ? (m.testo ? m.testo + ' · eliminato' : 'Messaggio eliminato') : m.testo;
    b.appendChild(t);
    const o = document.createElement('span');
    o.className = 'wa-ora';
    o.textContent = m.ora;
    b.appendChild(o);
    chat.appendChild(b);
  }

  async function aggiorna() {
    if (document.hidden) return;
    try {
      const r = await fetch(chat.dataset.url + '&dopo=' + chat.dataset.ultimo);
      const { messaggi } = await r.json();
      if (!messaggi.length) return;
      const vuota = document.getElementById('chat-vuota');
      if (vuota) vuota.remove();
      const inFondo = window.innerHeight + window.scrollY >= document.body.scrollHeight - 150;
      messaggi.forEach(aggiungi);
      chat.dataset.ultimo = messaggi[messaggi.length - 1].id;
      if (inFondo) fondo();
    } catch (e) { /* rete assente: riprova al giro dopo */ }
  }
  setInterval(aggiorna, 8000);
  document.addEventListener('visibilitychange', aggiorna);
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
    try {
      const r = await fetch('/turni/statistiche/leggi-foto/', { method: 'POST', body: dati });
      const j = await r.json();
      if (!r.ok) { scrivi(j.errore || 'Non riesco a leggere la foto.'); return; }
      let n = 0;
      for (const [nome, valore] of Object.entries(j.campi)) {
        const radio = form.querySelector(`input[type=radio][name="${nome}"][value="${valore}"]`);
        const campo = form.querySelector(`input[type=text][name="${nome}"]`);
        if (radio) { radio.checked = true; n++; }
        else if (campo) { campo.value = valore; campo.classList.add('letto'); n++; }
      }
      scrivi(`✓ Letti ${n} valori: controllali prima di salvare.`, true);
    } catch (e) {
      scrivi('Senza rete: scrivi i numeri a mano.');
    } finally { btn.disabled = false; btn.textContent = testo; }
  });
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
