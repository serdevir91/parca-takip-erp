import { Contact } from "lucide-react";
import { Page, PageHeader } from "../components/Layout";
import FirmsTab from "./admin/Firms";

/** Cari kartlar: one list for customers, suppliers and manufacturers. */
export default function Contacts() {
  return (
    <Page>
      <PageHeader icon={Contact} title="Cari kartlar" sub="Müşteri, tedarikçi ve fason üretici kartları, bakiye ve hesap ekstresi" />
      <FirmsTab />
    </Page>
  );
}
