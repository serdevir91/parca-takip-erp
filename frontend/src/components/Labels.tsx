import qrcode from "qrcode-generator";
import { useMemo } from "react";
import { createPortal } from "react-dom";
import { mobileApp } from "../api/mobile";
import { Modal } from "../pages/admin/shared";
import { useToast } from "./Toast";
import { tx } from "../api/i18n";

export type Label = { payload: string; title: string; sub?: string };

// The library keeps only the low byte of each character, which would break ş, ğ and ı in a code
qrcode.stringToBytes = (s) => Array.from(new TextEncoder().encode(s));

function qrSvg(text: string): string {
  const qr = qrcode(0, "M");
  qr.addData(text, "Byte");
  qr.make();
  return qr.createSvgTag({ scalable: true, margin: 0 });
}

function Sheet({ labels, svgs, className }: { labels: Label[]; svgs: string[]; className: string }) {
  return (
    <div className={className}>
      {labels.map((l, i) => (
        <div className="label" key={`${l.payload}-${i}`}>
          <span style={{ display: "contents" }} dangerouslySetInnerHTML={{ __html: svgs[i] }} />
          <div><b>{l.title}</b>{l.sub}</div>
        </div>
      ))}
    </div>
  );
}

/** Preview and print. There is no popup or new window: pywebview opens those in the system browser, signed out.
 * The print copy sits directly under body and the print CSS hides everything else, so window.print() prints the
 * labels alone; in the desktop app that is WebView2's own print dialog. */
export default function LabelsModal({ labels, onClose }: { labels: Label[]; onClose: () => void }) {
  const toast = useToast();
  const svgs = useMemo(() => labels.map((l) => qrSvg(l.payload)), [labels]);
  const print = () => {
    const app = mobileApp();
    if (!app) window.print();
    else if (app.print) app.print();
    else toast(tx("Bu uygulama sürümü yazdıramıyor; etiketi bilgisayardan yazdırın"), true);
  };
  return (
    <Modal wide title={tx("QR etiket ({0})", labels.length)} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>{tx("Kapat")}</button>
        <button className="btn primary" onClick={print}>{tx("Yazdır")}</button>
      </>}>
      <Sheet labels={labels} svgs={svgs} className="label-sheet" />
      <p className="muted">{tx("A4, sayfada 3 × 7 etiket (63 × 37 mm). Yazdırırken ölçek %100 olmalı.")}</p>
      {createPortal(<Sheet labels={labels} svgs={svgs} className="label-print" />, document.body)}
    </Modal>
  );
}
