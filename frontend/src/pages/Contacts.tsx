import { Contact } from "lucide-react";
import { Page, PageHeader } from "../components/Layout";
import FirmsTab from "./admin/Firms";
import { tx } from "../api/i18n";

/** Cari kartlar: one list for customers, suppliers and manufacturers. */
export default function Contacts() {
  return (
    <Page>
      <PageHeader icon={Contact} title={tx("Cari kartlar")} sub={tx("Müşteri, tedarikçi ve fason üretici kartları, bakiye ve hesap ekstresi")} />
      <FirmsTab />
    </Page>
  );
}
