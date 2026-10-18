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
    if (iphone && !installata) document.getElementById('notifiche-iphone').hidden = false;
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

// ---------------------------------------------------------------- chat che si aggiorna da sola
(function () {
  const chat = document.getElementById('chat');
  if (!chat) return;
  const fondo = () => document.getElementById('fondo').scrollIntoView({ block: 'end' });
  fondo();

  function bolla(m) {
    const d = document.createElement('div');
    d.className = 'bolla' + (m.mio ? ' mia' : '') + (m.ufficio ? ' ufficio' : '');
    d.dataset.id = m.id;
    if (!m.mio) {
      const a = document.createElement('span');
      a.className = 'bolla-autore';
      a.textContent = m.autore;
      d.appendChild(a);
    }
    const t = document.createElement('span');
    t.className = 'bolla-testo' + (m.eliminato ? ' tenue' : '');
    t.textContent = m.eliminato ? 'Messaggio eliminato' : m.testo;
    d.appendChild(t);
    const o = document.createElement('span');
    o.className = 'bolla-ora';
    o.textContent = m.ora;
    d.appendChild(o);
    return d;
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
      messaggi.forEach(m => chat.appendChild(bolla(m)));
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
