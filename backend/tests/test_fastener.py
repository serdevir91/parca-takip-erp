from app.core.fastener import FastenerMatcher, validate_rule

M = FastenerMatcher()


def test_patterns():
    cases = {
        "DIN 912 M6 x 12.SLDPRT": ("Cıvata", "DIN 912 / ISO 4762", "M6x12"),
        "DIN 7991 - M5 x 16": ("Cıvata", "DIN 7991", "M5x16"),
        "Hexagon Nut ISO 4032 - M8": ("Somun", "ISO 4032", "M8"),
        "DIN EN ISO 8733-5x18": ("Pim", "DIN EN ISO 8733", "Ø5x18"),
        "Washer DIN 125 - A 6.4": ("Rondela", "DIN 125-A / ISO 7089", "Ø6.4 (M6)"),
        "Washer ISO 7089 - 8": ("Rondela", "DIN 125-A / ISO 7089", "Ø8.4 (M8)"),
        "Spring washer DIN 128 - A6": ("Rondela", "DIN 128", "A6 (M6)"),
        "Parallel key A8 x 7 x 40 DIN 6885": ("Kama", "DIN 6885", "A8x7x40"),
        "Circlip DIN 471 - 20 x 1.2": ("Segman", "DIN 471", "20x1.2"),
    }
    for name, (t, std, size) in cases.items():
        m = M.match(name)
        assert m is not None, name
        assert (m.type, m.std, m.size) == (t, std, size), name


def test_iso_and_din_912_same_key():
    assert M.match("ISO 4762 M6 x 12").key == M.match("DIN 912 M6 x 12").key


def test_non_fastener():
    assert M.match("T01_0004_0001.SLDPRT") is None


def test_validate_rule_rejects_bad_regex():
    ok, msg, _ = validate_rule({"name": "x", "pattern": "(", "type": "Cıvata", "desc": "", "std": "", "size": ""})
    assert not ok and msg
