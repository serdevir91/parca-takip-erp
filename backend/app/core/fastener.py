"""Fastener recognition driven by editable rules (regex + templates).

Template syntax used in desc/std/size/d/l fields:
  {1}          -> regex group 1
  {2|DN125}    -> maps["DN125"][group 2]
Rules are evaluated in priority order with re.match (anchored at the start).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_TPL = re.compile(r"\{(\d+)(?:\|([A-Za-z0-9_]+))?\}")

DN125 = {"3.2": "3", "4.3": "4", "5.3": "5", "6.4": "6", "8.4": "8", "10.5": "10",
         "13": "12", "17": "16", "21": "20", "25": "24"}
ISO7089_INNER = {"3": "3.2", "4": "4.3", "5": "5.3", "6": "6.4", "8": "8.4", "10": "10.5",
                 "12": "13", "16": "17", "20": "21"}

DEFAULT_RULES: list[dict[str, Any]] = [
    dict(name="DIN 912 / ISO 4762", pattern=r"(DIN 912|ISO 4762) M(\d+(?:\.\d+)?) x (\d+)", type="Cıvata",
         desc="İmbus cıvata (silindirik başlı)", std="DIN 912 / ISO 4762", size="M{2}x{3}", d="{2}", l="{3}"),
    dict(name="DIN 7991", pattern=r"DIN 7991 - M(\d+(?:\.\d+)?) x (\d+)", type="Cıvata",
         desc="Havşa başlı imbus cıvata", std="DIN 7991", size="M{1}x{2}", d="{1}", l="{2}"),
    dict(name="Altıgen somun", pattern=r"Hexagon Nut (ISO 4034|ISO 4032|DIN 6915) - M(\d+)", type="Somun",
         desc="{1|NUT_DESC}", std="{1}", size="M{2}", d="{2}", l=None,
         maps={"NUT_DESC": {"ISO 4034": "Altıgen somun (C sınıfı)", "ISO 4032": "Altıgen somun",
                            "DIN 6915": "Altıgen somun (HV, yüksek mukavemet)"}}),
    dict(name="ISO 8733 pim", pattern=r"DIN EN ISO 8733-(\d+)x(\d+)", type="Pim",
         desc="Silindirik pim, iç dişli (ISO 8733)", std="DIN EN ISO 8733", size="Ø{1}x{2}", d="{1}", l="{2}"),
    dict(name="ISO 8750 pim", pattern=r"DIN EN ISO 8750-(\d+)x(\d+)", type="Pim",
         desc="Spiral yaylı pim", std="DIN EN ISO 8750", size="Ø{1}x{2}", d="{1}", l="{2}"),
    dict(name="DIN EN 28734 pim", pattern=r"DIN EN 28734 - (\d+) x (\d+)", type="Pim",
         desc="Silindirik pim (sertleştirilmiş, A tipi)", std="DIN EN 28734 (ISO 8734)", size="Ø{1}x{2}", d="{1}", l="{2}"),
    dict(name="DIN 94 kopilya", pattern=r"DIN 94-(\d+(?:\.\d+)?)x(\d+)", type="Pim",
         desc="Kopilya", std="DIN 94", size="{1}x{2}", d="{1}", l="{2}"),
    dict(name="DIN 125 rondela", pattern=r"Washer DIN 125 - (A|B) (\d+(?:\.\d+)?)", type="Rondela",
         desc="Düz rondela{1|W_DESC}", std="DIN 125-{1}{1|W_STD}", size="Ø{2} (M{2|DN125})", d="{2|DN125}", l=None,
         maps={"W_DESC": {"A": "", "B": " (pahlı, B tipi)"}, "W_STD": {"A": " / ISO 7089", "B": ""}, "DN125": DN125}),
    dict(name="ISO 7089 rondela", pattern=r"Washer ISO 7089 - (\d+)", type="Rondela",
         desc="Düz rondela", std="DIN 125-A / ISO 7089", size="Ø{1|ISO7089} (M{1})", d="{1}", l=None,
         maps={"ISO7089": ISO7089_INNER}),
    dict(name="DIN 128 yaylı rondela", pattern=r"Spring washer DIN 128 - A(\d+(?:\.\d+)?)", type="Rondela",
         desc="Yaylı rondela", std="DIN 128", size="A{1} (M{1})", d="{1}", l=None),
    dict(name="DIN 6885 kama", pattern=r"Parallel key A(\d+) x (\d+) x (\d+) DIN 6885", type="Kama",
         desc="Paralel kama (A tipi)", std="DIN 6885", size="A{1}x{2}x{3}", d="{1}", l="{3}"),
    dict(name="DIN 471 segman", pattern=r"Circlip DIN 471 - (\d+) x (\d+(?:\.\d+)?)", type="Segman",
         desc="Dış segman (mil)", std="DIN 471", size="{1}x{2}", d="{1}", l=None),
]
for _i, _r in enumerate(DEFAULT_RULES):
    _r.setdefault("maps", {})
    _r["priority"] = (_i + 1) * 10


@dataclass
class FastenerMatch:
    type: str
    desc: str
    std: str
    size: str
    d: float | None
    l: float | None
    orig: str
    rule: str = ""

    @property
    def key(self) -> str:
        return f"{self.type}|{self.std}|{self.size}"


def render(tpl: str | None, m: re.Match, maps: dict[str, dict[str, str]]) -> str | None:
    if tpl is None or tpl == "":
        return None

    def sub(mm: re.Match) -> str:
        g = m.group(int(mm.group(1))) or ""
        mp = mm.group(2)
        if mp:
            return str(maps.get(mp, {}).get(g, ""))
        return g

    return _TPL.sub(sub, tpl)


def _num(s: str | None) -> float | None:
    if s is None or s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


@dataclass
class FastenerMatcher:
    rules: list[dict[str, Any]] = field(default_factory=lambda: list(DEFAULT_RULES))

    def __post_init__(self) -> None:
        self._compiled = []
        for r in sorted(self.rules, key=lambda r: r.get("priority", 0)):
            if r.get("active", True) is False:
                continue
            self._compiled.append((re.compile(r["pattern"]), r))

    def match(self, file_name: str) -> FastenerMatch | None:
        n = re.sub(r"\.sldprt$", "", file_name.strip(), flags=re.IGNORECASE).strip()
        for rx, r in self._compiled:
            m = rx.match(n)
            if not m:
                continue
            maps = r.get("maps") or {}
            return FastenerMatch(
                type=r["type"], desc=render(r.get("desc"), m, maps) or "", std=render(r.get("std"), m, maps) or "",
                size=render(r.get("size"), m, maps) or "", d=_num(render(r.get("d"), m, maps)),
                l=_num(render(r.get("l"), m, maps)), orig=n, rule=r.get("name", ""))
        return None


def validate_rule(rule: dict[str, Any], sample: str | None = None) -> tuple[bool, str, FastenerMatch | None]:
    try:
        re.compile(rule["pattern"])
    except (re.error, KeyError) as e:
        return False, f"Geçersiz regex: {e}", None
    if sample is None:
        return True, "", None
    m = FastenerMatcher([dict(rule, priority=0, active=True)]).match(sample)
    return True, "" if m else "Örnek eşleşmedi", m
