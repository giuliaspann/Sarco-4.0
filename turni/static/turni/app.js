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
    const file = input.files[0];
    const etichetta = input.closest('label');
    if (!file) return;
    etichetta.querySelector('span').textContent = 'Foto pronta';
    etichetta.classList.add('pronta');
    if (!window.DataTransfer || !window.createImageBitmap) return;
    try {
      const ridotta = await riduci(file);
      const dt = new DataTransfer();
      dt.items.add(ridotta);
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
    t.textContent = m.eliminato ? 'Messaggio eliminato' : m.testo;
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
      const r = await fetch(chat.dataset.url + '?dopo=' + chat.dataset.ultimo);
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
