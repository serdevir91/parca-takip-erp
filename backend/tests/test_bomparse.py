from app.core.bomparse import ROW_IN_PURCHASED, TEMIN_HAZIR, clean_material, parse_bom


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
