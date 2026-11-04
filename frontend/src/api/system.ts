import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./client";

/** Form defaults from Yönetim > Sistem Ayarları; /auth/me and /auth/login refresh them. */
export interface SystemDefaults {
  currency: string;
  vat: number;
  payment_days: number;
  quote_days: number;
  pay_methods: string[];
  unit: string;
  work_hours: number;
  password_min: number;
  modules_off: string[];
}

export const sys: SystemDefaults = {
  currency: "TRY", vat: 20, payment_days: 30, quote_days: 15,
  pay_methods: ["Havale/EFT", "Nakit", "Kredi kartı", "Çek", "Senet", "Mahsup"],
  unit: "Adet", work_hours: 8, password_min: 8, modules_off: [],
};

export const setSys = (v?: SystemDefaults) => { if (v) Object.assign(sys, v); };

export const curSign = (cur = sys.currency) => (cur === "TRY" ? "₺" : cur);

export interface LoginOptions {
  signup: boolean;
  app_name: string;
  logo: string;
  password_min: number;
}

export const OPTIONS_KEY = ["auth", "options"];

/** Public branding; also keeps the browser tab title in step with the application name. */
export function useBrand() {
  const q = useQuery({
    queryKey: OPTIONS_KEY, queryFn: () => api.get<LoginOptions>("/auth/options"), staleTime: 5 * 60_000,
  });
  const name = q.data?.app_name ?? "LAB ERP";
  useEffect(() => {
    document.title = document.title.replace(/^(\(\d+\+?\) )?.*$/, (_, badge) => `${badge ?? ""}${name}`);
  }, [name]);
  return { name, logo: q.data?.logo ?? "", options: q.data, failed: q.isError };
}
