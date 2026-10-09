/* Marcajix · utilidades compartidas por todas las pantallas. */
(() => {
  // Escapa texto antes de insertarlo con innerHTML (nombres, códigos y mensajes vienen de la BD o del lector).
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));

  const toast = (message, tone = 'info', ms = 6000) => {
    let stack = document.querySelector('.toast-stack');
    if (!stack) {
      stack = document.createElement('div');
      stack.className = 'toast-stack';
      stack.setAttribute('aria-live', 'polite');
      document.body.appendChild(stack);
    }
    const item = document.createElement('div');
    item.className = `toast toast-${tone}`;
    item.innerHTML = `<i class="dot"></i><span class="toast-text">${escapeHtml(message)}</span><button type="button" class="toast-close" aria-label="Cerrar">×</button>`;
    const close = () => item.remove();
    item.querySelector('.toast-close').addEventListener('click', close);
    stack.appendChild(item);
    setTimeout(close, ms);
  };

  // Consulta el feed de la garita (marcajes y alertas) desde el último evento visto.
  const pollFeed = (url, intervalMs, onData, onError) => {
    let cursor = null;
    const poll = async () => {
      try {
        const params = cursor ? `?log=${cursor.log}&event=${cursor.event}` : '';
        const response = await fetch(url + params, { cache: 'no-store', credentials: 'same-origin' });
        if (!response.ok) throw new Error(response.status);
        const data = await response.json();
        const first = cursor === null;
        cursor = data.cursor;
        onData(data, first);
      } catch (error) {
        if (onError) onError(error);
      } finally {
        setTimeout(poll, intervalMs);
      }
    };
    poll();
  };

  window.escapeHtml = escapeHtml;
  window.Marcajix = { escapeHtml, toast, pollFeed };

  // Abre un diálogo y pone el foco en el primer campo (no en el botón de cerrar).
  const openDialog = (dialog) => {
    dialog.showModal();
    dialog.querySelector('.modal-body input:not([type=hidden]), .modal-body select, .modal-body textarea')?.focus();
  };

  document.addEventListener('DOMContentLoaded', () => {
    // Modales: <button data-open-modal="id">, <button data-close-modal>, <dialog data-autoshow>.
    document.addEventListener('click', (event) => {
      const opener = event.target.closest('[data-open-modal]');
      if (opener) {
        const dialog = document.getElementById(opener.dataset.openModal);
        if (dialog) openDialog(dialog);
      }
      const closer = event.target.closest('[data-close-modal]');
      if (closer) closer.closest('dialog').close();
    });
    document.querySelectorAll('dialog[data-autoshow]').forEach((dialog) => openDialog(dialog));
    document.querySelectorAll('dialog.modal').forEach((dialog) => {
      dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });
    });

    // Confirmación antes de enviar formularios destructivos: <form data-confirm="¿Seguro?">.
    document.addEventListener('submit', (event) => {
      const message = event.target.dataset.confirm;
      if (message && !window.confirm(message)) event.preventDefault();
    }, true);

    // Menú lateral en móvil.
    const sidebar = document.querySelector('.sidebar');
    const backdrop = document.querySelector('.sidebar-backdrop');
    const toggleSidebar = (open) => {
      sidebar?.classList.toggle('is-open', open);
      backdrop?.classList.toggle('is-open', open);
    };
    document.querySelector('.menu-toggle')?.addEventListener('click', () => toggleSidebar(!sidebar.classList.contains('is-open')));
    backdrop?.addEventListener('click', () => toggleSidebar(false));

    // Sombra en la barra superior al desplazarse.
    const topbar = document.querySelector('.topbar');
    if (topbar) {
      const update = () => topbar.classList.toggle('is-scrolled', window.scrollY > 4);
      window.addEventListener('scroll', update, { passive: true });
      update();
    }

    // Mostrar u ocultar contraseñas.
    document.querySelectorAll('input[type="password"]').forEach((input) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn btn-ghost btn-sm password-toggle';
      button.textContent = 'Mostrar';
      button.addEventListener('click', () => {
        const visible = input.type === 'text';
        input.type = visible ? 'password' : 'text';
        button.textContent = visible ? 'Mostrar' : 'Ocultar';
      });
      const wrapper = document.createElement('div');
      wrapper.className = 'password-field';
      input.parentNode.insertBefore(wrapper, input);
      wrapper.append(input, button);
    });

    // Campana de alertas: consulta cada 30 s y avisa de las nuevas (con sonido si son críticas).
    const bell = document.getElementById('alert-bell');
    if (bell) {
      const counter = document.getElementById('alert-count');
      const SEEN_KEY = 'marcajix.alerts.seen';
      let seen = 0;
      try { seen = Number(sessionStorage.getItem(SEEN_KEY) || 0); } catch (error) { /* sin almacenamiento */ }
      const beep = () => {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (!AudioContext) return;
        const context = new AudioContext();
        const oscillator = context.createOscillator();
        const gain = context.createGain();
        oscillator.frequency.value = 660;
        gain.gain.setValueAtTime(0.0001, context.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.08, context.currentTime + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.35);
        oscillator.connect(gain).connect(context.destination);
        oscillator.start();
        oscillator.stop(context.currentTime + 0.36);
        oscillator.addEventListener('ended', () => context.close(), { once: true });
      };
      const check = async () => {
        try {
          const response = await fetch(bell.dataset.summaryUrl, { cache: 'no-store' });
          if (!response.ok) return;
          const data = await response.json();
          counter.textContent = data.count;
          counter.hidden = !data.count;
          bell.classList.toggle('has-alerts', data.count > 0);
          const fresh = data.latest.filter((alert) => alert.id > seen);
          if (seen && fresh.length) {
            fresh.reverse().forEach((alert) => toast(alert.title, alert.severity === 'critical' ? 'error' : 'warning', 10000));
            if (fresh.some((alert) => alert.severity === 'critical')) beep();
          }
          const newest = Math.max(seen, ...data.latest.map((alert) => alert.id));
          seen = newest || seen || 1;
          try { sessionStorage.setItem(SEEN_KEY, String(seen)); } catch (error) { /* sin almacenamiento */ }
        } catch (error) { /* se reintenta en el siguiente ciclo */ }
      };
      check();
      setInterval(check, 30000);
    }

    // Vista previa de fotos antes de subirlas: <input type="file" data-preview="id-img">.
    document.querySelectorAll('input[type="file"][data-preview]').forEach((input) => {
      input.addEventListener('change', () => {
        const target = document.getElementById(input.dataset.preview);
        const file = input.files && input.files[0];
        if (target && file) {
          target.src = URL.createObjectURL(file);
          target.hidden = false;
        }
      });
    });
  });
})();
