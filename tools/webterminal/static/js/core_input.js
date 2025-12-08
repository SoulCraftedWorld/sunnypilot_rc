const activePointers = new Map();

function onPointerDown(e, id, handlers) {
  e.target.setPointerCapture(e.pointerId);
  activePointers.set(e.pointerId, { handlers, lastX: e.clientX, lastY: e.clientY });
  handlers.onStart?.(e.clientX, e.clientY, e);
}
function onPointerMove(e) {
  const st = activePointers.get(e.pointerId);
  if (!st) return;
  st.handlers.onMove?.(e.clientX, e.clientY, e);
}
function onPointerUp(e) {
  const st = activePointers.get(e.pointerId);
  if (!st) return;
  st.handlers.onEnd?.(e);
  activePointers.delete(e.pointerId);
}

export function attachPointerHandlers(el, handlers) {
  el.addEventListener('pointerdown', (e) => onPointerDown(e, el.id, handlers), { passive: true });
  el.addEventListener('pointermove', onPointerMove, { passive: true });
  el.addEventListener('pointerup', onPointerUp, { passive: true });
  el.addEventListener('pointercancel', onPointerUp, { passive: true });
}
