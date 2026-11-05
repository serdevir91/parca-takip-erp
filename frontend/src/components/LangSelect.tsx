import { LANG, LANGS, setLang, tx, type Lang } from "../api/i18n";

/** Language picker for the header and the login page. Choosing a language reloads the page. */
export default function LangSelect() {
  const narrow = window.matchMedia("(max-width: 640px)").matches;
  return (
    <select className="lang-select" value={LANG} aria-label={tx("Dil")} title={tx("Dil")}
      onChange={(e) => setLang(e.target.value as Lang)}>
      {LANGS.map((l) => <option key={l.code} value={l.code}>{narrow ? l.code.toUpperCase() : l.name}</option>)}
    </select>
  );
}
