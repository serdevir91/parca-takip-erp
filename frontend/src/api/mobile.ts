// Bridge to the Android app (mobile/android, MainActivity.Bridge). The app injects window.ParcaTakipApp;
// in a normal browser mobileApp() is null and the web code paths are used.

type MobileApi = {
  appVersion(): string;
  download(url: string, filename: string, token: string): void;
  changeServer(): void;
  checkUpdate(manual: boolean): void;
  setTheme(bg: string, dark: boolean): void;
};

export function mobileApp(): MobileApi | null {
  const api = (window as unknown as { ParcaTakipApp?: Partial<MobileApi> }).ParcaTakipApp;
  return api && typeof api.download === "function" ? (api as MobileApi) : null;
}

/** Android back button: the app calls window.__erpBack() first; true means the page handled it. */
const backHandlers: (() => boolean)[] = [];
(window as unknown as { __erpBack?: () => boolean }).__erpBack = () => {
  for (let i = backHandlers.length - 1; i >= 0; i--) if (backHandlers[i]()) return true;
  // Open dialogs (Modal, viewers, drawers) all close on Escape.
  if (document.querySelector('[role="dialog"]')) {
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    return true;
  }
  return false;
};

export function onBack(handler: () => boolean): () => void {
  backHandlers.push(handler);
  return () => {
    const i = backHandlers.indexOf(handler);
    if (i >= 0) backHandlers.splice(i, 1);
  };
}
