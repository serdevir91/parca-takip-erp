"""Language selection and the integrity of the translation catalogs."""
import json
import re
from pathlib import Path

import pytest

from app.core.i18n import LANGS, current_lang, set_lang, tx

LOCALES = Path(__file__).resolve().parent.parent / "app" / "locales"
FRONTEND_LOCALES = Path(__file__).resolve().parent.parent.parent / "frontend" / "src" / "locales"
SLOTS = re.compile(r"\{\d+\}")


@pytest.fixture(autouse=True)
def back_to_turkish():
    yield
    set_lang("tr")


def test_unknown_language_falls_back_to_turkish():
    set_lang("fr")
    assert current_lang() == "tr"
    set_lang(None)
    assert current_lang() == "tr"


def test_missing_text_stays_turkish_and_fills_placeholders():
    set_lang("en")
    assert tx("Kataloğa eklenmemiş {0} metin", 5) == "Kataloğa eklenmemiş 5 metin"


@pytest.mark.parametrize("lang", [code for code in LANGS if code != "tr"])
def test_translated_message(lang):
    set_lang(lang)
    assert tx("Proje bulunamadı") != "Proje bulunamadı"


@pytest.mark.parametrize("folder", [LOCALES, FRONTEND_LOCALES])
@pytest.mark.parametrize("lang", ["en", "es", "de"])
def test_catalog_keeps_every_placeholder(folder, lang):
    catalog = json.loads((folder / f"{lang}.json").read_text(encoding="utf-8"))
    assert catalog
    for source, text in catalog.items():
        assert text.strip(), source
        assert sorted(SLOTS.findall(source)) == sorted(SLOTS.findall(text)), source


def test_error_message_follows_the_language_header(client):
    r = client.post("/api/auth/login", data={"username": "nobody", "password": "x"},
                    headers={"X-Lang": "de", "X-Requested-With": "LabERP"})
    assert r.status_code == 401
    assert r.json()["detail"] != "Kullanıcı adı veya şifre hatalı"


def test_turkish_is_the_default_language(client):
    r = client.post("/api/auth/login", data={"username": "nobody", "password": "x"},
                    headers={"X-Requested-With": "LabERP"})
    assert r.json()["detail"] == "Kullanıcı adı veya şifre hatalı"
