from app.core.compare import compare_boms, suggest_aliases


def test_v1_v2(boms_v):
    r = compare_boms(boms_v[0], boms_v[1])
    assert "Part1-1" in r.added
    assert sum(1 for c in r.rev_changed if c.old == "" and c.new == "A") == 16
    mats = {c.part_no: (c.old, c.new) for c in r.material_changed}
    assert mats["T01_0004_0028"] == ("5083-111", "EPDM")
    assert mats["T01_0004_0029"] == ("5083-111", "EPDM")


def test_v2_v3(boms_v):
    r = compare_boms(boms_v[1], boms_v[2])
    assert "Part1-1" in r.removed
    assert "T01_0004_0033" in r.added
    revs = {c.part_no: (c.old, c.new) for c in r.rev_changed}
    assert revs["T01_0004_0001"] == ("A", "B")
    assert (r.fastener_total_old, r.fastener_total_new) == (130, 138)
    deltas = {(c.std, c.size): c.delta for c in r.fastener_changes}
    assert deltas[("DIN 912 / ISO 4762", "M6x12")] == 6
    assert deltas[("DIN EN 28734 (ISO 8734)", "Ø5x18")] == 2
    assert not r.fastener_big_drop


def test_1031_1102(bom_1031, bom_1102):
    r = compare_boms(bom_1031, bom_1102)
    for p in ["T01_0000_0005", "T01_0000_0016", "T01_0001_0000", "T01_2000_0007", "Zemin"]:
        assert p in r.removed, p
    assert "TSDacikboy" in r.added
    assert any(p.startswith("T01_6000_") for p in r.added)
    qty = {c.part_no: (c.old, c.new) for c in r.qty_changed}
    assert qty["T01_0600_0001"] == (44, 40)
    assert "T01_2000_0002-P" in r.added


def test_suggest_aliases():
    s = suggest_aliases(["T01_2000_0002"], ["T01_2000_0002-P", "X"])
    assert [(a.removed, a.added) for a in s] == [("T01_2000_0002", "T01_2000_0002-P")]
    s = suggest_aliases(["T01_2000_0003-1"], ["T01_2000_0003"])
    assert [(a.removed, a.added) for a in s] == [("T01_2000_0003-1", "T01_2000_0003")]
