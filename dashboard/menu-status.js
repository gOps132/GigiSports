import { drawContest } from './contest-view.js';

const invoke = (...args) => globalThis.__TAURI_INTERNALS__.invoke(...args);
let pending = false;
window.refreshMenuStatus = async () => {
  if (pending) return;
  pending = true;
  let status;
  try {
    status = await invoke('contest_status');
  } catch {
    status = {contest: null, ongoing: null};
  } finally {
    pending = false;
  }
  drawContest(document.getElementById('menu-metrics'), status);
};
window.refreshMenuStatus();
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') invoke('dismiss_menu_status');
});
