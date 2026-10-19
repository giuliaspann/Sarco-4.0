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
