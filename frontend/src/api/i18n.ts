// Interface language. The Turkish source text is the key, so a missing entry
// falls back to Turkish. The language is read once at start-up and changing it
// reloads the page, which lets module-level constants use tx() too.
import de from "../locales/de.json";
import en from "../locales/en.json";
import es from "../locales/es.json";

export type Lang = "tr" | "en" | "es" | "de";

export const LANGS: { code: Lang; name: string }[] = [
  { code: "tr", name: "Türkçe" },
  { code: "en", name: "English" },
  { code: "es", name: "Español" },
  { code: "de", name: "Deutsch" },
];

const LANG_KEY = "erp_lang";
const CATALOGS: Record<string, Record<string, string>> = { en, es, de };
const LOCALES: Record<Lang, string> = { tr: "tr-TR", en: "en-GB", es: "es-ES", de: "de-DE" };

function stored(): Lang {
  try {
    const v = localStorage.getItem(LANG_KEY);
    if (LANGS.some((l) => l.code === v)) return v as Lang;
  } catch {
    // Storage can be blocked; Turkish stays the default.
  }
  return "tr";
}

export const LANG: Lang = stored();
export const LOCALE = LOCALES[LANG];
const catalog = CATALOGS[LANG];

// The server reads this cookie for direct downloads, which carry no X-Lang header.
document.cookie = `${LANG_KEY}=${LANG}; path=/; max-age=31536000; samesite=strict`;
document.documentElement.lang = LANG;

/** Translates Turkish source text and fills its {0}, {1} placeholders. */
export function tx(text: string | null | undefined, ...args: unknown[]): string {
  if (!text) return "";
  const out = (catalog && catalog[text]) || text;
  if (!args.length) return out;
  return out.replace(/\{(\d+)\}/g, (_, i) => String(args[Number(i)] ?? ""));
}

/** Labels the server builds, such as status_label, carry Turkish text. Translates them in a response. */
export function localizeLabels<T>(data: T): T {
  if (!catalog || data === null || typeof data !== "object") return data;
  const walk = (v: unknown) => {
    if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === "object") {
      const o = v as Record<string, unknown>;
      for (const k of Object.keys(o)) {
        const x = o[k];
        if (typeof x === "string") {
          if ((k === "label" || k.endsWith("_label")) && catalog[x]) o[k] = catalog[x];
        } else walk(x);
      }
    }
  };
  walk(data);
  return data;
}

export function setLang(code: Lang) {
  if (code === LANG) return;
  try {
    localStorage.setItem(LANG_KEY, code);
  } catch {
    // Without storage the choice lasts only until the cookie is rewritten.
  }
  location.reload();
}
