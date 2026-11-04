from pathlib import Path

import pytest

from app.core.bomparse import ROW_IN_PURCHASED, TEMIN_HAZIR, BomParseError, clean_material, parse_bom

DATA = Path(__file__).parent / "data"


def test_acceptance_1102(bom_1102):
    b = bom_1102
    assert len(b.rows) == 450
    assert len(b.non_fastener_rows) == 388
    assert len(b.fastener_rows) + sum(1 for r in b.rows if r.fastener and r.in_purchased) == 62
    totals = b.fastener_totals()
    assert len(totals) == 43
    assert sum(totals.values()) == 1006
    assert sum(1 for r in b.rows if r.in_purchased) == 60


def test_1031_counts(bom_1031):
    totals = bom_1031.fastener_totals()
    assert len(bom_1031.rows) == 501
    assert len(totals) == 84
    assert sum(totals.values()) == 1642


def test_purchased_flag_marks_children(bom_1102):
    asm = [r for r in bom_1102.rows if r.part_no == "TSDacikboy"]
    assert asm and all(r.is_purchased_assembly and r.procurement == TEMIN_HAZIR for r in asm)
    kids = [r for r in bom_1102.rows if r.in_purchased]
    assert all(r.row_type == ROW_IN_PURCHASED for r in kids)


def test_qty_multiplies_parents():
    csv = ("Level;Dosya Adı;Reference Count;Malzeme;Ağırlık;Revizyon;TeminSekli;Kaplama Bilgisi\n"
           "1;ROOT.SLDASM;1;;;;;\n"
           "1.1;A.SLDASM;2;;;;;\n"
           "1.1.1;B.SLDASM;3;;;;;\n"
           "1.1.1.1;  P_0001.SLDPRT;4;Material <not specified>;12.5;A;İmalat;\n")
    b = parse_bom(csv.encode("utf-8-sig"))
    p = [r for r in b.rows if r.part_no == "P_0001"][0]
    assert p.total_qty == 24
    assert p.material == ""
    assert p.weight == 12.5
    assert p.main_group == "A"


def test_clean_material():
    assert clean_material("Malzeme <belirli değil>") == ""
    assert clean_material("Material <not specified>") == ""
    assert clean_material("5083-H111") == "5083-H111"


def test_same_part_many_assemblies_totals(bom_1102):
    totals = bom_1102.part_totals()
    rows_by = {}
    for r in bom_1102.non_fastener_rows:
        if r.depth and not r.in_purchased:
            rows_by.setdefault(r.part_no, 0)
            rows_by[r.part_no] += r.total_qty
    for k, v in rows_by.items():
        assert totals[k] == v


MONTHS = "Oca Şub Mar Nis May Haz Tem Ağu Eyl Eki Kas Ara".split()


def as_excel(v: str) -> str:
    """What Turkish Excel writes back to the CSV for a dotted number it took for a date."""
    parts = v.split(".")
    if not all(x.isdigit() for x in parts):
        return v
    a, b = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    if len(parts) == 2:
        if 1 <= a <= 31 and 1 <= b <= 12:
            return f"{a}.{MONTHS[b - 1]}"
        if 1 <= a <= 12 and len(parts[1]) <= 2:
            return f"{MONTHS[a - 1]}.{b:02d}"
    if len(parts) == 3 and 1 <= a <= 31 and 1 <= b <= 12 and len(parts[2]) <= 2:
        y = int(parts[2])
        return f"{a:02d}.{b:02d}.{2000 + y if y < 30 else 1900 + y}"
    return v


def test_bom_saved_by_turkish_excel_reads_the_same():
    raw = (DATA / "BOM_T01_0000_0000_2026-11-02.csv").read_text(encoding="utf-8-sig").splitlines()
    lines = [raw[0]]
    for line in raw[1:]:
        c = line.split(";")
        c[0], c[4] = as_excel(c[0]), as_excel(c[4])
        lines.append(";".join(c))
    mangled = "\n".join(lines)
    assert "1.Oca" in mangled and "Oca.13" in mangled and "01.01.2001" in mangled
    got = parse_bom(mangled.encode("cp1254", "replace"))
    want = parse_bom("\n".join(raw))
    assert got.warnings and not want.warnings
    assert [(r.level, r.part_no, r.total_qty, r.weight) for r in got.rows] == \
           [(r.level, r.part_no, r.total_qty, r.weight) for r in want.rows]


def test_unknown_level_text_is_still_refused():
    csv = ("Level;Dosya Adı;Reference Count;Malzeme;Ağırlık;Revizyon;TeminSekli;Kaplama Bilgisi\n"
           "1;ROOT.SLDASM;1;;;;;\n"
           "1.Abc;A.SLDASM;2;;;;;\n")
    with pytest.raises(BomParseError, match="geçersiz seviye"):
        parse_bom(csv.encode("utf-8-sig"))

