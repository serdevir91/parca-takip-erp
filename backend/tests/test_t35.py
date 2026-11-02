from app.core.t35 import build_preview, map_text, read_t35
from conftest import DATA


def test_mapping_rules():
    m = map_text("ROBOLEGO İMALATA ALINACAK")
    assert (m.progress, m.manufacturer) == ("Bekliyor", "ROBOLEGO")
    assert map_text("İHMA ÜRETİMDE").progress == "Devam ediyor"
    assert map_text("İHMA ÜRETİMDE").manufacturer == "İHMA"
    m = map_text("ÜRETİM TAMAMLANDI")
    assert m.progress == "Tamamlandı" and m.note is None
    assert map_text("İHMA HAZIR").progress == "Tamamlandı"
    assert map_text("HAS-MAK İMALATTA").manufacturer == "HAS-MAK"
    assert map_text("SİPARİŞ VERİLMEMİŞ, STOKTAN").material_status == "Stoktan"
    assert map_text("TEKRAR MALZEME SİPARİŞİ").material_status == "Tekrar sipariş edildi"
    assert map_text("MALZEME DAHA ÖNCE SÖYLENDİ").material_status == "Sipariş verildi"
    assert map_text("MALZEME SÖYLENECEK").material_status == "Malzeme söylenecek"


def test_case_insensitive_turkish():
    assert map_text("ihma üretimde").progress == "Devam ediyor"


def test_read_and_preview(bom_1102):
    rows = read_t35((DATA / "T-35_Guncel_Durumu.xlsx").read_bytes())
    assert rows and all(r.part_no for r in rows)
    parts = {}
    for r in bom_1102.non_fastener_rows:
        if r.depth and not r.in_purchased:
            p = parts.setdefault(r.part_no, {"rev": r.rev, "total_qty": 0, "produced": False})
            p["total_qty"] += r.total_qty
    pv = build_preview(rows, parts)
    assert pv.updates
    assert len(pv.updates) + len(pv.only_in_list) == len(rows)
