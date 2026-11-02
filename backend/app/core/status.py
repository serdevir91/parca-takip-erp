"""Progress -> derived status logic and colours (single source of truth for API, UI and Excel)."""
from __future__ import annotations

PROG_WAIT = "Bekliyor"
PROG_RUN = "Devam ediyor"
PROG_DONE = "Tamamlandı"
PROGRESS_CHOICES = [PROG_WAIT, PROG_RUN, PROG_DONE]

KIND_IMALAT = "İmalat"
KIND_HAZIR = "Hazır Alım"
KIND_MONTAJ = "Montaj"

STATUS_MAP: dict[str, dict[str, str]] = {
    KIND_IMALAT: {PROG_WAIT: "Üretilmedi", PROG_RUN: "Üretilmedi", PROG_DONE: "Üretildi"},
    KIND_HAZIR: {PROG_WAIT: "Sipariş Verilmedi", PROG_RUN: "Sipariş Verildi", PROG_DONE: "Sipariş Teslim Edildi"},
    KIND_MONTAJ: {PROG_WAIT: "Montajlanmadı", PROG_RUN: "Montajlanmadı", PROG_DONE: "Montajlandı"},
}
STATUS_NO_TEMIN = "Temin seçilmedi"
STATUS_IN_PURCHASED = "Hazır montaj içinde"

COLORS = {
    "Üretilmedi": "F8CBAD",
    "Üretildi": "BDD7EE",
    "Sipariş Verilmedi": "FFC7CE",
    "Sipariş Verildi": "FFEB9C",
    "Sipariş Teslim Edildi": "C6EFCE",
    "Montajlanmadı": "E7E6E6",
    "Montajlandı": "D9C3E9",
    STATUS_NO_TEMIN: "FF0000",
    "missing": "E4DFEC",
    "new": "D9EAD3",
    "in_purchased": "D9D9D9",
}

MATERIAL_STATUS_CHOICES = ["Stoktan", "Malzeme söylenecek", "Sipariş verildi", "Tekrar sipariş edildi", "Malzeme geldi"]

PRODUCED_STATUSES = {"Üretildi", "Sipariş Teslim Edildi", "Montajlandı"}


def status_kind(procurement: str, is_assembly: bool) -> str | None:
    """Which status column applies. A purchased assembly behaves like Hazır Alım."""
    if procurement == KIND_HAZIR:
        return KIND_HAZIR
    if is_assembly:
        return KIND_MONTAJ
    if procurement == KIND_IMALAT:
        return KIND_IMALAT
    return None


def derive_status(progress: str | None, procurement: str, is_assembly: bool, in_purchased: bool = False) -> str:
    if in_purchased:
        return STATUS_IN_PURCHASED
    kind = status_kind(procurement, is_assembly)
    if kind is None:
        return STATUS_NO_TEMIN
    return STATUS_MAP[kind].get(progress or PROG_WAIT, STATUS_MAP[kind][PROG_WAIT])


def is_produced(progress: str | None) -> bool:
    return progress == PROG_DONE


def effective_procurement(csv_temin: str, override: str | None, is_assembly: bool) -> str:
    t = override or csv_temin or ""
    if not t and not is_assembly:
        return "Belirtilmemiş"
    return t
