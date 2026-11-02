from app.core.status import (PROG_DONE, PROG_RUN, PROG_WAIT, STATUS_NO_TEMIN, derive_status,
                             effective_procurement)


def test_imalat():
    assert derive_status(PROG_WAIT, "İmalat", False) == "Üretilmedi"
    assert derive_status(PROG_RUN, "İmalat", False) == "Üretilmedi"
    assert derive_status(PROG_DONE, "İmalat", False) == "Üretildi"


def test_hazir():
    assert derive_status(PROG_WAIT, "Hazır Alım", False) == "Sipariş Verilmedi"
    assert derive_status(PROG_RUN, "Hazır Alım", False) == "Sipariş Verildi"
    assert derive_status(PROG_DONE, "Hazır Alım", True) == "Sipariş Teslim Edildi"


def test_montaj():
    assert derive_status(PROG_RUN, "", True) == "Montajlanmadı"
    assert derive_status(PROG_DONE, "İmalat", True) == "Montajlandı"


def test_no_temin():
    assert derive_status(PROG_WAIT, "Belirtilmemiş", False) == STATUS_NO_TEMIN
    assert effective_procurement("", None, False) == "Belirtilmemiş"
    assert effective_procurement("İmalat", "Hazır Alım", False) == "Hazır Alım"
