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
    etichetta.querySelector('span').textContent = 'Foto pronta ✓';
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
