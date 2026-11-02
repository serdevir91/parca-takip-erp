from app.core.drawmatch import DrawingMatcher, parse_filename, rev_mismatch

PARTS = ["T01_0004_0001", "T01_2000_0002", "T01_2000_0002-P", "T01_0600_0001"]


def test_parse_rev():
    assert parse_filename("T01_0004_0001_RevB.pdf").rev == "B"
    assert parse_filename("T01_0004_0001-B.dwg").rev == "B"
    p = parse_filename("T01_0004_0001 (Rev C).pdf")
    assert (p.base, p.rev, p.ext) == ("T01_0004_0001", "C", "pdf")


def test_match():
    m = DrawingMatcher(PARTS, aliases={"OLD_0001": "T01_0600_0001"})
    assert m.match("T01_2000_0002-P.pdf").part_no == "T01_2000_0002-P"
    r = m.match("t01-0004-0001_RevB.PDF")
    assert (r.part_no, r.via, r.parsed.rev) == ("T01_0004_0001", "rev-stripped", "B")
    assert m.match("T01_0004_0001.dwg").via == "exact"
    assert m.match("OLD_0001.pdf").part_no == "T01_0600_0001"
    u = m.match("T01_0004_0010.pdf")
    assert u.part_no is None and u.suggestions


def test_rev_mismatch():
    assert rev_mismatch("B", "A")
    assert not rev_mismatch("b", "B")
    assert not rev_mismatch(None, "A")
