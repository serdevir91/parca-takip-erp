/**
 * The rounding rule of backend/app/core/numbers.py for the browser, so a total typed into a form and the same total
 * saved on the server never differ. Money keeps 2 decimals, quantities 3, half up on the decimal value.
 * backend/tests/test_numbers.py pins both sides to the same cases.
 */
function halfUp(v: number, dp: number): number {
  // 9 decimals first drop the binary noise: 1.1 * 1.15 is 1.2649999999999999 and must count as 1.265
  const r = Number(`${Math.round(Number(`${Math.abs(v).toFixed(9)}e${dp}`))}e-${dp}`);
  return v < 0 ? -r : r;
}

export const money = (v: number) => halfUp(v, 2);
export const qty = (v: number) => halfUp(v, 3);

/** Same steps as commerce.totals: rounded lines, their sum, then discount, then tax. */
export function docTotals(lines: { qty: number; price: number }[], taxRate = 0, discountPct = 0) {
  const subtotal = money(lines.reduce((s, l) => s + money(l.qty * l.price), 0));
  const discount = money((subtotal * discountPct) / 100);
  const tax = money(((subtotal - discount) * taxRate) / 100);
  return { subtotal, discount, tax, total: money(subtotal - discount + tax) };
}

/** Sum of values that are already rounded, without the binary tail a long reduce leaves behind. */
export const sumMoney = (values: (number | null | undefined)[]) => money(values.reduce<number>((s, v) => s + (v ?? 0), 0));
