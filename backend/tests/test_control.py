from app.core.control import (KIND_DOUBLE_COUNT, KIND_MATERIAL_MISMATCH, KIND_NO_DRAWING,
                              KIND_PART_AND_ASM, check_bom)
from conftest import load


def test_part_and_assembly_same_number(bom_1102):
    iss = check_bom(bom_1102)
    assert any(i.kind == KIND_PART_AND_ASM and i.part_no == "T01_0004_0014" for i in iss)


def test_double_count(bom_1102):
    iss = check_bom(bom_1102)
    assert any(i.kind == KIND_DOUBLE_COUNT and i.part_no == "T01_0051_0012" for i in iss)


def test_material_mismatch():
    found = False
    for name in ["BOM_T01_0000_0000_2026-11-02.csv", "BOM_T01_0000_0000_2026-10-31.csv",
                 "BOM_T01_0004_0000_v1.csv"]:
        iss = check_bom(load(name))
        found |= any(i.kind == KIND_MATERIAL_MISMATCH and "5083-111" in i.part_no and "5083-H11" in i.part_no
                     for i in iss)
    assert found


def test_no_drawing(bom_1102):
    iss = check_bom(bom_1102, drawing_parts=set())
    assert any(i.kind == KIND_NO_DRAWING for i in iss)
    assert not any(i.kind == KIND_NO_DRAWING for i in check_bom(bom_1102))
