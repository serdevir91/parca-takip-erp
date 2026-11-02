# PROMPT – Yerel Sunucuda Çalışan Proje / Parça Takip ERP Yazılımı

> Bu dosyayı Claude Code'a (veya başka bir kodlama ajanına) ver. Aynı klasördeki `ornek_veriler/`, `referans_ciktilar/` ve `referans_kod/` klasörleri promptun parçasıdır; önce hepsini oku.

---

## 0. Senden istenen

Bir savunma sanayi firmasında mekanik tasarım ekibi için **web tabanlı, yerel sunucuya (internetsiz ağ) kolayca kurulabilen bir ERP / proje-parça takip yazılımı** geliştir.

Bugün bu iş elle yapılıyor:
1. SolidWorks'ten montajın BOM'u `.csv` olarak alınıyor.
2. BOM'dan bir "Takip Listesi" Excel'i üretiliyor: parça listesi, durum takibi, bağlantı elemanları özeti, grafikli özet sayfası.
3. Yeni BOM geldikçe liste güncelleniyor; eski durumlar (üretildi, sipariş verildi vb.) korunuyor.
4. Parçaların teknik resimleri (PDF/DWG/SLDDRW) ayrı klasörlerde duruyor.

Yazılım bu akışın tamamını tek bir web arayüzünde yapmalı. Excel çıktısı da almaya devam edebilmeliyiz.

`referans_kod/` içindeki Python kodu bu kuralların çalışan bir prototipidir. `referans_ciktilar/` içindeki Excel'ler hedeflenen çıktı biçimidir. İş kurallarını bunlardan ve aşağıdaki bölümlerden çıkar. Kodu kopyalamak zorunda değilsin ama davranış aynı olmalı.

---

## 1. Çalışma ortamı ve kısıtlar (kesin)

- **İnternetsiz yerel ağ.** Uygulama çalışırken hiçbir dış kaynağa (CDN, Google Fonts, harici API, telemetri) bağlanmamalı. Tüm JS/CSS/font paketlenmiş olmalı.
- **Kurulum tek komut:** `docker compose up -d`. Linux sunucuda ve Windows'ta (Docker Desktop) çalışmalı. README'de adım adım kurulum, güncelleme, yedekleme ve geri yükleme anlatılmalı.
- **Offline kurulum:** İnternet olan bir makinede imajları hazırlayıp (`docker save`) internetsiz sunucuya taşıyabilmek için bir script ve README bölümü hazırla.
- **Arayüz dili Türkçe.** Türkçe karakterler (ı, İ, ş, ğ, ü, ö, ç) her yerde düzgün çalışmalı: CSV okuma, arama, sıralama, dosya adları ve Excel çıktısı dahil.
- Veriler ve yüklenen dosyalar Docker volume'larında kalıcı olmalı. Günlük otomatik yedek alınmalı (veritabanı dökümü + dosyalar, son N gün saklanır).

## 2. Teknoloji yığını

Aksi bir gerekçen yoksa bunu kullan; değiştireceksen önce gerekçesiyle sor.

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic (migration), Pydantic.
- **Veritabanı:** PostgreSQL 16.
- **Excel:** openpyxl (okuma ve yazma; veri doğrulama, koşullu biçimlendirme ve grafikler dahil).
- **Frontend:** React + TypeScript + Vite. Tablolar için TanStack Table (sanal kaydırma, kolon filtresi, çoklu seçim, satır içi düzenleme). Grafikler için Recharts. Hepsi paketlenmiş, CDN yok.
- **Dosya deposu:** Yerel dosya sistemi (volume). Dosya meta verisi veritabanında tutulur.
- **Ters vekil:** nginx (frontend statik dosyaları + `/api` yönlendirmesi). Büyük dosya yüklemeleri için limitler (≥ 2 GB toplu yükleme) ayarlanmalı.
- **Kimlik doğrulama:** Kullanıcı adı + şifre, JWT veya oturum çerezi. İlk kurulumda admin kullanıcısı oluşturulur.

## 3. Ana kavramlar ve veri modeli

Aşağıdaki modeli temel al; gerekirse genişlet.

- **Proje:** örneğin "T-35". Ana montaj numarası (T01_0000_0000), açıklama.
- **BOM Sürümü:** Bir projeye yüklenen her CSV yeni bir sürümdür. Tutulanlar: yükleme tarihi, yükleyen, dosya adı, not. Sürümler silinmez; geçmiş görülebilir.
- **Parça (master):** Parça numarasıyla benzersiz kayıt. Projeler ve sürümler boyunca aynı parça numarası aynı kayıttır. Durum bilgisi buna bağlıdır.
- **BOM Satırı:** Bir sürümdeki her satır. Tutulanlar: seviye ("1.3.2.4"), üst montaj, ana grup (seviye-1 montaj), adet, toplam adet, malzeme, ağırlık, revizyon, temin şekli, kaplama, satır tipi (Parça / Montaj / Bağlantı Elemanı / Satın alınan montajın içi).
- **Takip Kaydı (proje + parça başına):** temin şekli (kullanıcı değiştirebilir, BOM'daki değeri ezer), ilerleme, notlar, dış durum notu (T-35 notu), üretici/firma.
- **Eksik / Ek Adet:** Bir parçaya bağlı ek ihtiyaç satırı (adet, sebep, kendi ilerlemesi). Örnek: "T01_2200_0026 – 8 olmalı, 4 var – 4 adet eksik".
- **Parça Takma Adı (alias):** "T01_2000_0002-P = T01_2000_0002" gibi kullanıcı eşleştirmeleri. Bir parça yeni numarayla geldiğinde eski durumunu devralır.
- **Bağlantı Elemanı Kalemi:** Normalleştirilmiş standart + ölçü (örn. "DIN 912 / ISO 4762 – M12x55"). Toplam adet ve sipariş durumu.
- **Teknik Resim Dosyası:** dosya adı, uzantı, boyut, hash, yükleme tarihi, yükleyen, eşleştiği parça, revizyon (dosya adından okunabiliyorsa), sürüm geçmişi.
- **Değişiklik Günlüğü (audit log):** kim, ne zaman, hangi kayıtta, hangi alanı, eski değer → yeni değer.
- **Kullanıcılar ve roller:** Admin, Tasarımcı (BOM ve resim yükler), Planlama/Satın alma (durum günceller), İzleyici (sadece okur).

## 4. BOM CSV içe aktarma kuralları

Örnek dosyalar `ornek_veriler/` klasöründe.

### 4.1 Dosya biçimi
- Ayraç `;`, kodlama UTF-8 BOM'lu (`utf-8-sig`). Başlıklar: `Level;Dosya Adı;Reference Count;Malzeme;Ağırlık;Revizyon;TeminSekli;Kaplama Bilgisi`.
- `Level` hiyerarşiyi belirtir: `1`, `1.1`, `1.1.2`, … Dosya adlarının başındaki girinti boşlukları temizlenir.
- Parça numarası = dosya adının uzantısız hali (`.SLDPRT`, `.SLDASM`, `.sldprt` büyük-küçük harf duyarsız). `.SLDASM` = montaj.
- "Material <not specified>" ve "Malzeme <belirli değil>" → boş malzeme ("Belirtilmemiş").
- Ağırlık nokta ondalıklı; gram kabul et.

### 4.2 Adet hesabı
- **Toplam Adet = satır adedi × tüm üst montajların adetlerinin çarpımı.** Örnek: T01_0050_0000 (2) → T01_0051_0000 (2) → T01_0051_0002 (2) = 8.
- Aynı parça birden fazla montajda geçebilir (örn. T01_0600_0001 sekiz farklı montajda). Satırlar ayrı gösterilir. Toplam ihtiyaç ayrıca hesaplanabilmeli (parça bazında toplama).

### 4.3 Satın alınan montajlar
- Temin şekli "Hazır Alım" olan bir **montaj** tek kalem olarak satın alınır. Altındaki parçalar ayrı takip edilmez: "Satın alınan montajın içi" olarak gri gösterilir, sayımlara girmez.
- Kullanıcı bir montajı sonradan "tek hazır alım kalemi" olarak işaretleyebilmeli. Örnek: TSDacikboy alt montajındaki 30 tedarikçi kodlu parça (26.2108.xx, 2000xx.R00); BOM'da temin şekli boş, ama tek kalem olarak alınıyor. Bu işaret parça kaydında saklanır ve sonraki BOM yüklemelerinde de geçerli olur.

### 4.4 Bağlantı elemanlarını tanıma ve normalleştirme
Dosya adından tür, standart, çap ve boy çıkar. Desenlerin tamamı `referans_kod/parse.py` → `fastener()` fonksiyonunda var. Özetle:

| Örnek dosya adı | Tür | Standart (normalleştirilmiş) | Ölçü |
|---|---|---|---|
| `DIN 912 M10 x 65 --- 32N` | Cıvata | DIN 912 / ISO 4762 | M10x65 |
| `ISO 4762 M12 x 20 - 20N` | Cıvata | DIN 912 / ISO 4762 (aynı parça, birleştir) | M12x20 |
| `DIN 7991 - M3 x 10 --- 6.8N` | Cıvata (havşa başlı) | DIN 7991 | M3x10 |
| `Hexagon Nut ISO 4032 - M16 - W - N` | Somun | ISO 4032 / ISO 4034 / DIN 6915 | M16 |
| `DIN EN ISO 8733-8x30-St` | Pim (iç dişli silindirik) | DIN EN ISO 8733 | Ø8x30 |
| `DIN EN ISO 8750-5x45-St` | Pim (spiral yaylı) | DIN EN ISO 8750 | Ø5x45 |
| `DIN EN 28734 - 3 x 8 - A - St` | Pim (sertleştirilmiş silindirik) | DIN EN 28734 (ISO 8734) | Ø3x8 |
| `DIN 94-6.3x28-C-St` | Pim (kopilya) | DIN 94 | 6.3x28 |
| `Washer DIN 125 - A 10.5` / `Washer ISO 7089 - 10` | Rondela (düz) | DIN 125-A / ISO 7089 (aynı parça, birleştir) | Ø10.5 (M10) |
| `Washer DIN 125 - B 17` | Rondela (pahlı) | DIN 125-B | Ø17 (M16) |
| `Spring washer DIN 128 - A10` | Rondela (yaylı) | DIN 128 | A10 (M10) |
| `Parallel key A12 x 8 x 32 DIN 6885` | Kama | DIN 6885 | A12x8x32 |
| `Circlip DIN 471 - 30 x 1.5` | Segman | DIN 471 | 30x1.5 |

- Tanınmayan standart dışı isimler parça olarak alınır ve "standart dışı isim" uyarısıyla işaretlenir (örn. `gps anteni`, `Kauçuk1`, `montaj Ø1400`, `35MM DIN RAIL-12`).
- Desenler bir ayar dosyasında veya veritabanında tutulmalı; yeni desen eklemek kod değişikliği gerektirmemeli (admin ekranından regex + eşleme tanımlanabilir).

### 4.5 Yeni BOM sürümü yüklenince
- Önceki sürümle **parça numarasına göre** karşılaştır. Ağırlık farklarını **dikkate alma**; sadece parça numaraları önemli. Revizyon, malzeme, temin ve adet farkları bilgi olarak gösterilir.
- Sonuç ekranı ("BOM Karşılaştırma"), onaydan önce gösterilir:
  - Yeni eklenen parçalar,
  - Kaldırılan parçalar (o parçada ilerleme varsa kırmızı uyarı: "Üretildi durumundaki parça BOM'dan kalktı"),
  - Revizyonu değişen parçalar (parça "Üretildi"/"Tamamlandı" ise uyarı: "eski revizyonla üretilmiş olabilir"),
  - Adet değişiklikleri,
  - Bağlantı elemanı kalem/adet değişiklikleri (toplam adette büyük düşüş varsa uyarı).
- **Olası eşleştirme önerisi:** Kaldırılan bir numara ile yeni gelen numara arasında sadece son ek farkı varsa (`-P`, `-1` vb.) kullanıcıya "aynı parça mı?" diye sor. Evet derse alias oluştur ve durumu taşı. Hayır derse ayrı parça kalır.
- Onaydan sonra:
  - Mevcut parçaların takip bilgisi (temin değişikliği, ilerleme, notlar, eksik satırları) **korunur**.
  - Yeni parçalar varsayılan durumla eklenir ve "Yeni" etiketi alır (etiket kullanıcı kaldırana veya sonraki sürüme kadar kalır).
  - Kaldırılan parçalar listeden çıkar ama veritabanında arşivlenir; geçmiş sürümde görülebilir.
- Geri alma: son BOM yüklemesi geri alınabilmeli.

## 5. Durum mantığı (önemli)

Kullanıcı durumu doğrudan seçmez. **"İlerleme"** seçer; **"Durum"** temin şekline göre otomatik türetilir. Böylece temin şekli değişince durum da otomatik değişir, grafikler ve sayımlar anında güncellenir.

İlerleme seçenekleri: **Bekliyor / Devam ediyor / Tamamlandı**

| İlerleme | Temin = İmalat | Temin = Hazır Alım | Montaj (satın alınmayan) |
|---|---|---|---|
| Bekliyor | Üretilmedi | Sipariş Verilmedi | Montajlanmadı |
| Devam ediyor | Üretilmedi | Sipariş Verildi | Montajlanmadı |
| Tamamlandı | Üretildi | Sipariş Teslim Edildi | Montajlandı |

- Temin şekli "Belirtilmemiş" ise Durum = "Temin seçilmedi" (kırmızı).
- Renkler: Üretilmedi `#F8CBAD`, Üretildi `#BDD7EE`, Sipariş Verilmedi `#FFC7CE`, Sipariş Verildi `#FFEB9C`, Sipariş Teslim Edildi `#C6EFCE`, Montajlanmadı `#E7E6E6`, Montajlandı `#D9C3E9`. Eksik satırları mor (`#E4DFEC`), yeni parçalar yeşil (`#D9EAD3`).
- Ek alanlar: Üretici/Firma (örn. ROBOLEGO, İHMA, HAS-MAK; listesi admin'den yönetilir), malzeme durumu (Stoktan / Malzeme söylenecek / Sipariş verildi / Tekrar sipariş edildi / Malzeme geldi), serbest not.
- Her durum değişikliği audit log'a yazılır. Parça detayında zaman çizelgesi gösterilir.
- Toplu güncelleme: tabloda çoklu seçim → "İlerlemeyi ayarla" / "Temin şeklini ayarla".

## 6. Dış durum listesi içe aktarma (T-35 Güncel Durumu tipi)

Örnek: `ornek_veriler/T-35_Guncel_Durumu.xlsx`. Kolonlar: No, Dosya Adı, Reference Count, Malzeme, Ağırlık, Revizyon, Durum (serbest metin, çok satırlı).

- Serbest metni ilerlemeye eşle. Kurallar yapılandırılabilir; varsayılanlar:
  - "TAMAMLANDI", "İHMA HAZIR" → Tamamlandı
  - "ÜRETİMDE", "İMALATTA" → Devam ediyor
  - Diğerleri → Bekliyor
  - Metinde geçen firma adı → Üretici
  - Metnin tamamı → "T-35 Notu" alanı (tek başına "ÜRETİM TAMAMLANDI" ise not yazma)
  - "SİPARİŞ VERİLMEMİŞ" + "STOK" → malzeme durumu "Stoktan"; "TEKRAR MALZEME" → "Tekrar sipariş edildi"; "DAHA ÖNCE" → "Sipariş verildi"; "MALZEME SÖYLENECEK" → "Malzeme söylenecek"
- İçe aktarma önizlemesinde karşılaştırma tablosu göster: BOM'da olup listede olmayanlar, listede olup BOM'da olmayanlar, revizyon farkı (üretildiyse "DİKKAT"), adet farkı. Kullanıcı onaylayınca uygula.
- Hücre arka plan renkleri (kırmızı/turuncu işaret) "dış listede kırmızı işaretli" notu olarak alınır.

## 7. Teknik resim yönetimi

- **Toplu yükleme:** Çoklu dosya seçme, sürükle-bırak, klasör yükleme ve `.zip` yükleme. Desteklenen uzantılar en az şunlar: PDF, DWG, DXF, SLDDRW, SLDPRT, SLDASM, STEP/STP, PNG/JPG.
- **Otomatik eşleştirme:** Dosya adı (uzantısız) parça numarasıyla aynıdır. Eşleştirme kuralları:
  - Büyük-küçük harf duyarsız; baştaki/sondaki boşluklar ve `_`/`-` farkları normalize edilir.
  - Dosya adında revizyon eki varsa ayrıştır ve kaydet: `T01_2110_0004_RevD.pdf`, `T01_2110_0004-D.pdf`, `T01_2110_0004 (Rev C).pdf` gibi.
  - Alias tablosundaki eşleştirmeler kullanılır.
  - Bir parçanın birden fazla dosyası olabilir (PDF + DWG + SLDDRW): tür bazında gruplanır.
  - Aynı adla yeniden yüklenen dosya yeni **sürüm** olur; eski sürümler saklanır ve indirilebilir.
- **Eşleşmeyenler ekranı:** Otomatik eşleşmeyen dosyalar listelenir. Benzer parça numarası önerilir (fuzzy match). Kullanıcı elle eşleştirir veya siler.
- **Parça listesinde** teknik resim kolonu bulunur. Kolonda resmi olan parçalarda ikonlar gösterilir (PDF/DWG/…), resmi olmayan imalat parçaları "resim yok" uyarısı alır. "Resmi olmayan imalat parçaları" filtresi olmalı.
- **Görüntüleme:** PDF tarayıcıda açılır (paketlenmiş pdf.js; dış kaynak yok). DWG/SLDDRW indirilir. Varsa PDF'in ilk sayfasından küçük önizleme üretilir.
- **Revizyon kontrolü:** Resimdeki revizyon BOM'daki revizyonla uyuşmuyorsa uyarı ver.
- **Toplu indirme:** Seçili parçaların veya bir ana grubun resimlerini `.zip` olarak indir. Tedarikçiye gönderim için isteğe bağlı "sadece PDF" veya "PDF + DWG" seçeneği olmalı.

## 8. Ekranlar

1. **Giriş**
2. **Projeler:** liste, yeni proje.
3. **Proje Özeti (dashboard):**
   - KPI kartları: imalat ilerlemesi %, üretilen/toplam, hazır alım teslim/toplam, bağlantı elemanı adedi ve teslim, eksik adet, resmi olmayan imalat parçası sayısı.
   - Pasta grafikleri: imalat durumu, hazır alım sipariş durumu, bağlantı elemanı türleri, bağlantı elemanı sipariş durumu.
   - Ana grup tablosu ve yatay yığılmış çubuk grafik (ana grup başına üretildi/üretilmedi, ilerleme çubuğu).
   - Hepsi canlı veriden hesaplanır.
4. **Parça Listesi:**
   - Ağaç görünümü (montaj hiyerarşisi, açılır-kapanır) ve düz görünüm ("sadece parçalar": montajlar gizli; satın alınan montajlar tek satır).
   - Kolonlar: Seviye, Parça No, Tip, Ana Grup, Üst Montaj, Adet, Toplam Adet, Malzeme, Ağırlık, Temin Şekli, Kaplama, Rev, İlerleme, Durum, Üretici, T-35 Notu, Not, Teknik Resim.
   - Her kolonda filtre (çoklu seçim + metin arama). Filtrelenen satır ve toplam adet sayısı üstte görünür.
   - Satır içi düzenleme, çoklu seçim ile toplu düzenleme.
   - Parça detay paneli: bilgiler, teknik resimler, durum geçmişi, kullanıldığı montajlar, eksik satırları.
5. **Bağlantı Elemanları:**
   - Detay sekmesi: montaj bazında satırlar, adet × çarpan.
   - Özet sekmesi: kalem bazında toplam, kullanıldığı ana gruplar, sipariş durumu, yedek % ve sipariş miktarı hesabı (yukarı yuvarlama), tedarikçi, birim fiyat.
6. **BOM Sürümleri:** yükleme, karşılaştırma ekranı (bkz. 4.5), sürüm geçmişi.
7. **Teknik Resimler:** toplu yükleme, eşleşmeyenler, tüm dosyalar.
8. **Kontrol Listesi:** Sistemin otomatik bulduğu sorunlar ve kullanıcının açtığı konular (Açık/Çözüldü):
   - Malzemesi veya temin şekli boş parçalar,
   - Standart dışı isimler,
   - Aynı numara hem parça hem montaj (`T01_0004_0014` örneği),
   - Aynı parçanın aynı montajda hem alt montaj içinde hem doğrudan bulunması (çift sayım şüphesi, `T01_0051_0012` örneği),
   - Malzeme adı tutarsızlıkları (`5083-111` / `5083-H11`),
   - Revizyon uyarıları,
   - Resmi olmayan imalat parçaları.
9. **Yönetim:** kullanıcılar ve roller, firma listesi, bağlantı elemanı desenleri, durum eşleme kuralları, yedekleme durumu, audit log görüntüleme.

## 9. Excel çıktıları

`referans_ciktilar/` içindeki iki dosya hedef biçimdir. Aynı yapıyı openpyxl ile üret:

1. **Takip Listesi (tam):** Özet, Parça Listesi (montajlar dahil, girintili), Bağlantı Elemanları, Bağlantı Özeti.
2. **Parça Takip (sade):** Özet + Parça Listesi; montajlar çıkarılmış, satın alınan montajlar tek satır.

Excel'de olması gerekenler:
- Arial font, koyu lacivert (`#1F3864`) başlık satırı, ince gri kenarlıklar, ızgara çizgileri kapalı, başlık satırı dondurulmuş, otomatik filtre açık, yatay sayfa ve sayfaya sığdırma ayarlı.
- **İlerleme** kolonu açılır listeli (sarı zemin). **Durum** kolonu formüldür (`=IF(...)`, bölüm 5'teki tablo). Temin şekli Excel'de değiştirilirse durum orada da otomatik değişir.
- Temin Şekli kolonunda açılır liste.
- Durum renkleri koşullu biçimlendirmeyle.
- Üstte `SUBTOTAL` ile "filtrelenen satır" ve "filtrelenen toplam adet" sayaçları.
- Özet sayfasında formülle hesaplanan KPI kartları, pasta grafikleri ve ana grup çubuk grafiği. Kullanıcı Excel'de değişiklik yapınca bunlar da güncellenmeli.
- Ek çıktılar: bağlantı elemanı sipariş formu (kalem, standart, ölçü, ihtiyaç, yedek %, sipariş miktarı, birim, birim fiyat, tutar), filtrelenmiş tablonun "görüneni dışa aktar" seçeneği.
- **Excel'den geri içe aktarma:** Kullanıcı dışa aktardığı Excel'de İlerleme/Temin/Not değiştirip geri yükleyebilmeli. Sistem parça numarası + üst montaja göre eşleştirir, farkları önizletir, onaylanınca uygular.

## 10. Kalite ve kabul kriterleri

- Backend için pytest ile birim testleri yaz: CSV ayrıştırma, adet çarpımı, bağlantı elemanı desenleri, BOM karşılaştırma, durum türetme, T-35 eşleme, resim dosya adı eşleştirme.
- `ornek_veriler/BOM_T01_0000_0000_2026-11-02.csv` için beklenen sonuçlar (TSDacikboy "tek hazır alım kalemi" işaretlendiğinde):
  - 450 BOM satırı, bunların 388'i parça/montaj, 62'si bağlantı elemanı satırı.
  - Bağlantı elemanları 43 benzersiz kaleme düşer, toplam adet **1006**.
  - Satın alınan montajların içinde kalan (takip edilmeyen) satır sayısı 60.
- `BOM_T01_0000_0000_2026-10-31.csv` → `2026-11-02.csv` karşılaştırması şunları bulmalı:
  - T01_3000 grubu tamamen kaldırılmış; T01_0001_0000 ve parçaları, T01_0000_0005, T01_0000_0016, T01_2000_0007 kaldırılmış.
  - Yeni eklenenler: T01_6000_0000 grubu, T01_6000_0000-P grubu, T01_2000_0002-P.
  - Bağlantı elemanı toplamı 1642 → 1006.
- `BOM_T01_0004_0000_v1/v2/v3.csv` sırasıyla yüklendiğinde:
  - v1 → v2: Part1-1 eklenir, T01_0004_0028/0029 malzemesi EPDM olur, 16 parçaya Rev A gelir.
  - v2 → v3: Part1-1 kalkar, T01_0004_0033 eklenir, T01_0004_0001 Rev B olur, DIN 912 M6x12 (6 adet) ve Ø5x18 pim (2 adet) eklenir.
- Excel çıktısı LibreOffice ile yeniden hesaplatıldığında formül hatası (#REF!, #NAME? vb.) olmamalı.
- 2000+ satırlık BOM'da parça listesi akıcı çalışmalı (sanal kaydırma).

## 11. Çalışma şekli

1. Önce bu dosyayı ve ekleri oku. Belirsiz gördüğün noktaları **kod yazmadan önce** madde madde sor.
2. Kısa bir mimari plan ve veritabanı şeması çıkar, onay al.
3. Aşamalı geliştir; her aşama sonunda çalışan, `docker compose up` ile ayağa kalkan bir sürüm olsun:
   - **Aşama 1:** Altyapı (Docker, DB, auth, proje), BOM içe aktarma, Parça Listesi ekranı, İlerleme → Durum mantığı.
   - **Aşama 2:** BOM sürüm karşılaştırma ve durum taşıma, alias, eksik satırları, dashboard.
   - **Aşama 3:** Teknik resim yükleme, otomatik eşleştirme ve görüntüleme.
   - **Aşama 4:** Excel dışa/içe aktarma (referans çıktılarla birebir biçim), T-35 tipi dış liste içe aktarma.
   - **Aşama 5:** Bağlantı elemanı sipariş modülü, kontrol listesi, yönetim ekranları, audit log, yedekleme.
   - **Sonraki aşamalar (şimdilik tasarımda yer bırak):** satın alma siparişleri ve tedarikçi kartları, stok/depo, iş emirleri, maliyet takibi.
4. Her aşamada README'yi güncelle. Örnek verilerle demo veritabanı oluşturan bir `seed` komutu ekle.
5. Kodu temiz, katmanlı ve yorumlu yaz. İş kuralları (desenler, eşleme tabloları) koda gömülü değil, yapılandırılabilir olsun.

## 12. Ekler

- `ornek_veriler/`
  - `BOM_T01_0000_0000_2026-10-31.csv`, `BOM_T01_0000_0000_2026-11-02.csv`: ana montajın iki BOM sürümü
  - `BOM_T01_0004_0000_v1.csv`, `_v2.csv`, `_v3.csv`: alt montajın üç sürümü (karşılaştırma testi için)
  - `T-35_Guncel_Durumu.xlsx`: dış durum listesi örneği
- `referans_ciktilar/`
  - `T01_0000_0000_Takip_Listesi.xlsx`: tam takip listesi (hedef Excel biçimi)
  - `T01_0000_0000_Parca_Takip.xlsx`: sade parça takip (hedef Excel biçimi)
- `referans_kod/`
  - `parse.py`: BOM ayrıştırma, adet çarpımı, satın alınan montaj tespiti, bağlantı elemanı desenleri, T-35 okuma
  - `build_takip_excel.py`: Excel çıktılarını üreten prototip (durum taşıma, İlerleme → Durum formülü, özet ve grafikler). Dosya yolları prototipe göre sabit yazılmıştır; sadece mantık için referans al.
