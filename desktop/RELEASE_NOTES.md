Windows masaüstü uygulaması: `LabERP-Setup-x.y.z.exe` dosyasını indirip çalıştırın.
Android uygulaması: telefonda `LabERP-x.y.z.apk` dosyasını indirip kurun (Android 8.0 ve üstü). Bu dosya her telefonda çalışır; `-arm64-v8a`, `-armeabi-v7a`, `-x86_64` ve `-x86` dosyaları işlemciye özel sürümlerdir.

## 1.5.12 yenilikleri

- **Sohbet:** Mesaj düzenleme (48 saat), benden veya herkesten silme, yanıtlama, iletme, tepki, sabitleme, kopyalama ve çoklu seçim eklendi. Menü sağ tıkla veya mesajdaki oktan açılır.
- **Android bildirimi:** Uygulama kapalıyken de yeni mesaj ve uyarı bildirimi gelir. Bildirime dokununca ilgili ekran açılır. Sunucuya ulaşılabilmesi gerekir. Ekran kapalıyken gecikme olabilir.
- **Windows bildirimi:** Pencere kapalı veya arka plandayken bildirim gelir. İstemci modunda da pencere kapatılınca uygulama saatin yanındaki gizli simgelerde çalışmaya devam eder. Tamamen kapatmak için simgeye sağ tıklayıp "Çık" seçilir.
- **Bağlantı elemanı stoğu:** Stok › Bağlantı elemanları sekmesi eklendi. BOM'daki civata ve somunlar kendiliğinden listelenir, stok ve açık ihtiyaç yan yana görünür. Giriş, çıkış, sayım ve projeye verme tek pencereden yapılır. Min. stok, raf ve QR etiket desteklenir.
- **Okunmamış sayısı:** Silinmiş mesajlar artık okunmamış sayısına girmez.

## 1.5.11 yenilikleri

- **Proje silme:** Windows sunucuda "Kalıcı olarak sil" hata veriyor, proje silinmiyordu. Sorun silmeden önce alınan yedekteydi, düzeltildi.
- **Yedekleme (Windows):** SQLite kullanan Windows kurulumlarında yedek hiç tamamlanmıyordu; gece yedeği dahil. Artık tamamlanır. Geri yükleme de aynı nedenle başarısız oluyordu, o da düzeldi.
- **Yedek alınamazsa:** Proje silinmez ve neden ekranda yazar. Yönetici isterse "Yedeksiz kalıcı olarak sil" ile devam eder, bu denetim kaydına yazılır.
- **Yedek sürerken silme:** Başka yedek sürüyorsa proje artık yedeksiz silinmez.
- **Çok uzun metin, çok büyük sayı:** PostgreSQL'de "Internal Server Error" yerine anlaşılır uyarı gelir. Bağlantılı kayıt çakışmaları da açıkça yazılır.
- **Yükselttikten sonra:** Windows sunucuda Yönetim › Yedekleme ekranından elle yedek alın ve dosyanın listede göründüğünü denetleyin.

## 1.5.10 yenilikleri

- **Tek yuvarlama kuralı:** Tutar 2, miktar 3 ondalık, her zaman yarım yukarı. Ekran, Excel ve fatura aynı sonucu verir. Bağlantı elemanı yedek miktarı da Excel ile aynı çıkar.
- **Ağırlık:** Ürün ağacı ve Excel artık aynı birimi kullanır, etiketler birimi yazar. Eski taslaklarda kg diye yazılmış değerler kendiliğinden çevrilmez, kontrol edin.
- **Saatler:** Kayıt zamanları ekranda yerel saatle görünür.
- **Telefon:** Ürün ağacı ekranı dar ekranda taşmıyor.
- **Oturum çerezi:** Oturum artık tarayıcı belleğinde değil, betiklerin okuyamadığı httpOnly çerezde durur. Sürüm yükselince herkes bir kez yeniden giriş yapar.
- **Yönetici uyarıları:** HTTPS kapalıysa ve hesap isteği ayarı açıksa yönetici ekranda uyarı görür. Ayarlar kendiliğinden değişmez.
- **Sertifika sabitleme:** Masaüstü her bağlantıda sertifikayı denetler. Android, HTTPS'e geçmiş sunucuya düz HTTP ile bağlanmaz.
- **Çakışma uyarısı:** Stok, personel, mesai, iş emri, firma, proje, sipariş ve fatura formlarında başkasının kaydının üzerine sessizce yazılmaz. Toplu düzenleme bilerek üzerine yazar.
- **Resmi tatiller:** Yönetim › Resmi Tatiller ekranından düzenlenir. Beklenen mesai ve izin günleri tatilleri düşer. Dini bayramları yönetici girer.
- **Satışta eksik kapatma:** Satış siparişi "Eksik kapatıldı" ile kapatılabilir.
- **Otomatik alacak dekontu:** Faturalı malın iadesi taslak dekontu kendisi açar.
- **Belge tarihi kuru:** Firma bakiyesi bugünkü kurla veya belge tarihindeki kurla gösterilebilir, kur farkı ayrı yazılır.
- **Mal kabulde elle kur:** Kuru olmayan yabancı para siparişte kur ekranda girilir.
- **Düz HTTP'de kamera:** Barkod ekranı canlı kameranın neden açılmadığını ve HTTPS yolunu söyler. Fotoğrafla okutma çalışır.
- **Düzeltilen hatalar:** Android'de dosya açma çökmesi, eksik kapatılmış siparişte taslak dekontun düzenlenememesi, PostgreSQL'de iade ile dekont açarken oluşan hata, aynı anda iki kez fatura kesilmesi, koyu temada etiket çıktısındaki siyah kenarlık.

## 1.5.9 yenilikleri

- **Bildirim merkezi:** Üst çubuktaki zil geciken sipariş ve faturaları, düşük stoğu, bekleyen onayları gösterir. Herkes yalnızca yetkili olduğu konuları görür.
- **İzin ve rapor:** Çalışan izin ister, yönetici onaylar. Mesai düzeltme talebi aynı yoldan gider.
- **Mesaiden işe saat:** Günün mesaisi proje ve iş emirlerine dağıtılır, maliyete yansır.
- **Barkod ve QR:** Telefon kamerası veya okuyucuyla stok, sipariş ve iş emri açılır. Etiket yazdırılır.
- **Sipariş önerisi:** Düşük stok ve açık ihtiyaçlardan satın alma önerisi çıkar.
- **İş emri:** Malzeme tüketimi, iade ve operasyon adımları iş emrinden yürür.
- **Döviz:** TCMB kurları alınır, toplamlar ana para biriminde gösterilir.
- **Kısmi sevk ve iade:** Satış siparişi parça parça sevk edilir, iade kaydedilir. Satırdan fatura kesilir.
- **Tedarikçi performansı:** Zamanında teslim ve eksik teslim oranları görünür.
- **Proje şablonları:** Bir proje şablon yapılır, yeni proje ondan açılır.
- **Çakışma uyarısı:** Parça tablosunda başkasının değiştirdiği alanın üzerine sessizce yazılmaz, seçim size sorulur.
- **Görünümler sunucuda:** Kayıtlı görünümler, sütun düzeni ve tema hesabınızla her cihaza gelir.
- **Tek tıkla HTTPS:** Yönetim › HTTPS ekranından açılır. Android ve masaüstü sertifikayı kaydeder, değişirse bağlanmaz.
- **Ekrandan geri yükleme:** Yönetim › Yedekler ekranından yedek seçilir veya dosya yüklenir.
- **Güvenlik:** Masaüstü güncellemesi imza doğrulaması olmadan kurulmaz. SMTP şifresi şifreli saklanır. E-posta, firma ve proje okuma yetkiye bağlandı. Yeni kurulumlarda hesap isteği kapalı gelir. Sohbet dosyaları, tarayıcı güvenlik başlıkları ve sunucu değişikliği onayı sıkılaştırıldı.

## 1.5.8 yenilikleri

- **Mesai takibi:** Çalışan giriş ve çıkış düğmesiyle mesaisini tutar, yalnızca kendisininkini görür. Yetkili yönetici herkesi görür, düzeltir, Excel'e aktarır. Haftalık fazla mesai otomatik hesaplanır.
- **Önemli yedek düzeltmesi:** Veritabanı veri klasöründeyse (Sunucuma kur ile kurulan Linux sunucular) yedek alma sonraki kayıtların kaybolmasına yol açabiliyordu. Düzeltildi. Yedekler artık iç içe büyümüyor, geri yükleme eski yedekleri silmiyor.
- **Stok:** Aynı anda yapılan hareketler artık birbirini ezmiyor.
- **Numaralar:** Aynı anda açılan sipariş ve faturalar hata vermiyor.
- **Çevrimdışı:** Bağlantı yokken kayıt sıraya girmiyor, hemen hata gösteriyor. Canlı göstergesi doğru durumu söylüyor.
- **Tablo:** Başka bilgisayardan gelen değişiklikte seçili hücre aynı satırda kalıyor.
- **Fatura:** Aynı satış siparişi iki kez faturalanamıyor. Satın alma siparişinde yalnızca faturalanmamış kısım gelir.
- **Silme koruması:** Fatura veya siparişi olan firma, projeye hareketi olan stok kartı silinemiyor.
- **Güvenlik:** Personel kartı e-posta ile eşleşmiyor (yönetici bağlamalı). Ana sayfa akışı yetkiye göre süzülüyor. Giriş kilidi başkasını dışarıda bırakmıyor. Girişsiz büyük istek reddediliyor. Yedekte imza anahtarı yok, yedek dosyası yalnızca sahibine açık. CSV formül koruması eklendi. Varsayılan admin şifresi için uyarı var. Kütüphaneler güncellendi.

## 1.5.7 yenilikleri

- **Temin şekilleri:** Fason İmalat, Standart Parça, Stoktan Karşılama ve Müşteri Malı eklendi. Sistem Ayarları'ndan yenisini ekleyin; davranışını, teknik resim ve sipariş önerisini seçin.
- **Excel gibi tablo:** Hücre ve aralık seçimi, kopyala, kes, yapıştır, doldurma tutamağı, geri al, bul ve değiştir, sağ tık menüsü ve seçim toplamı geldi.
- **Sütunlar:** Gizleyin, sıralayın, sabitleyin. Düzen hatırlanır.
- **Gelişmiş filtre:** Sütunda koşullu filtre, VE ve VEYA gruplu kurallar, adla kayıtlı görünümler.
- **Toplu değiştirme:** Liste ya da tablo modunda filtreleyip seçin, ilerleme ve temin şeklini hepsine birden atayın.
- **Parça adı:** Yeni sütun. Tablodan yazın ya da parça no ve ad listesini Excel'den yapıştırın. Ürün ağacında da girilir.
- **Excel dosyası:** Ekrandaki satır ve sütunlar `.xlsx` olarak iner.

## 1.5.6 yenilikleri

- **Ürün ağacı:** Proje menüsünde yeni ekran. CAD listesi olmadan ürünü montaj montaj kurun: alt montaj ve parça ekleyin, üst montajdaki adeti, temin şeklini, malzemeyi ve ağırlığı yazın, toplam adet kendiliğinden çarpılır.
- **Kalem seçimi:** Daha önce kullanılan bir numarayı yazınca seçin. Bilgileri gelir, montajsa alt kalemleri de eklenir.
- **Taslak ve sürüm:** Ağaç kendiliğinden taslak olarak kaydedilir. Var olan bir BOM sürümünden de başlayabilirsiniz. Gönderince bekleyen BOM sürümü olur, karşılaştırıp onaylarsınız.
- **Gizle:** Parça listesi ve Bağlantı elemanları ekranlarında seçilen satırlar gizlenir. Satır listede kalır, yalnızca soluk görünür; İhtiyaç ekranında da soluktur. Adet, durum ve ihtiyaç hesabı değişmez.

## 1.5.5 yenilikleri

- **Arka planda çalışma:** Sunucu olan bilgisayarda pencereyi kapatınca sistem artık durmaz. Uygulama gizli simgelere iner, diğer cihazlar çalışmaya devam eder. Tamamen kapatmak için simgeye sağ tıklayıp "Sunucuyu durdur ve çık" seçin.
- **Sistem Ayarları:** Yönetim'de yeni sekme. Uygulama adı, logo, şirket bilgileri, para birimi, KDV, vade, ödeme yöntemleri, belge numarası önekleri, varsayılan birim, şifre ve giriş kuralları, oturum süresi, yükleme sınırı, yedek saati ve açık modüller buradan değişir.
- **Her şirkete uygun:** T-35'e özel adlar ve kurallar kaldırıldı. Eski "T-35 Ayarları" artık isteğe bağlı "Durum Listesi Kuralları" oldu. Mevcut kurulumların ayarları korunur.
- **Sunucuma kur kılavuzu:** Sunucuda ve bilgisayarda yapılacaklar adım adım gösterilir. "Bağlantıyı dene" hangi adımın hazır olduğunu işaretler.
- **Proje silme:** Proje adını yazmak yerine onay penceresi çıkar.
- **Satın alma, satış ve fatura belgeleri:** Şirket bilgileri belgelere yazdırılır.

## 1.5.3 yenilikleri

- **Proje silme:** Yönetici, Projeler sayfasındaki "Sil" düğmesiyle projeyi kalıcı olarak silebilir. Pencere neyin silineceğini ve neyin kalacağını sayılarıyla gösterir, proje adının yazılmasını ister ve silmeden önce otomatik yedek alır. "Arşivle" aynen duruyor.
- **BOM sürümü silme:** Reddedilen veya geri alınan BOM sürümleri "Sürümü sil" ile kaldırılır. Onaylı sürümler silinmez.
- **Tümünü seç:** Seçim yapılan listelerde "Tümünü seç", "Tersine çevir" ve "Seçimi temizle" var. Shift ile tıklayınca aradaki satırların hepsi seçilir.
- **Teknik resim yükleme:** Dosyalar artık önce listelenir; istenmeyenlerin işareti kaldırılır, sonra "Seçilenleri yükle" ile gönderilir.
- **Toplu resim silme:** Teknik Resimler'de liste ve galeri görünümünde çoklu seçim, eşleşmeyen resimlerde de seçim ve "Seçilenleri sil" var.

## 1.5.2 yenilikleri

- **Düzeltme:** Excel'de açılıp kaydedilen BOM dosyası artık "geçersiz seviye '1.Oca'" hatası vermiyor. Excel'in tarihe çevirdiği seviye ve ağırlıklar otomatik geri düzeltilir, BOM sürümünde uyarı olarak gösterilir.

## 1.5.1 yenilikleri

- **Yeni liste kartları:** Parça listesi, stok ve diğer listelerde her kayıt düzenli bir blok: üstte parça no ve tip, sağda durum rozeti, altında etiketli alan kutuları. Telefonda parça no tek satırda kalır, durum rozeti alt satıra geçer.
- **Modern filtre:** Filtre paneli solda sütunlar, sağda değerler (telefonda alttan açılan sayfa). Değerlerin yanında kaç kayıt olduğu görünür; "Metin içerir" ve değer arama tek yerde.
- **Etkin filtreler:** Arama çubuğunun altında çip olarak görünür. Çipe dokunmak filtreyi düzenler, ✕ kaldırır, "Tümünü temizle" hepsini siler.
- **Sade araç çubuğu:** Arama kutusu simgeli ve temizleme düğmeli. Telefonda üstteki düğmeler tek satırda yana kaydırılır.
- **Düzeltme:** Tablo görünümünde sütun başlığındaki filtre penceresi artık kesik açılmıyor.

## 1.5.0 yenilikleri

- **Sunucuma kur:** Windows uygulamasının ilk ekranında yeni seçenek. Linux sunucunun (Ubuntu, Debian, Rocky, Alma, Fedora) adresini ve SSH bilgilerini girin; LAB ERP sunucuya otomatik kurulur, açılışta kendiliğinden başlayan hizmet olarak çalışır ve bu bilgisayar ona bağlanır. Tekrar çalıştırmak sunucuyu günceller, veriler korunur.
- **Personel gizliliği:** Personel ve zaman ekranını (saat ücretleri dahil) yalnızca admin ve bu yetkiyi verdiğiniz kişiler görür. Her çalışan "Personel kartım" ekranında yalnızca kendi kartını ve saatlerini görür. Personel kartı, Personel sekmesinde kullanıcı hesabına bağlanır.
- **İşe göre yetkiler:** Varsayılan roller sıkılaştırıldı. Fatura ve ödemeler yalnızca admin'de. Satış yalnızca Planlama/Satın alma rolünde (görüntüleme). Tasarımcı ve İzleyici cari kartları görmez. Proje maliyetinde işçilik, personel yetkisi olmayanlara isimsiz tek satır olarak görünür. Yönetici gerekirse kullanıcı bazında yetki açabilir.
- **Windows görünümü:** Beyaz menü çubuğu kaldırıldı. Uygulama menüsü (yeniden yükle, bağlantı ayarları, veri klasörü, güncelleme, kapat) üst çubukta temaya uygun açılır. Pencere başlığı açık, koyu ve siyah temaya göre renklenir.

## 1.4.1 yenilikleri

- **Yeni ad: LAB ERP.** Yeni logo; Windows, Android ve tarayıcıda aynı ad ve simge. Veriler ve ayarlar aynen kalır.
- **Düzeltme:** Windows uygulaması yeni bir bilgisayarda ilk açılışta "açılıyor" ekranında takılı kalmıyor.
- Açılış uzun sürerse "Bağlantı ayarlarını aç" düğmesi çıkar.

## 1.4.0 yenilikleri

- **Hesap oluştur:** Giriş ekranından hesap isteği gönderilir. Yönetici Yönetim › Kullanıcılar ekranında rol ve yetki vererek onaylar ya da reddeder; bekleyen istek sayısı menüde görünür.
- **E-posta:** Kullanıcılara e-posta adresi eklenebilir. Yönetim › E-posta ekranında Gmail, Outlook, Yandex için hazır ayarlar ve test e-postası. Listeler ve Excel dosyaları tek tıkla e-postayla gönderilir; telefonda Gmail/WhatsApp ile paylaşılır.
- **Yeni liste görünümü:** Parça listesi, stok ve diğer listeler varsayılan olarak kart görünümünde; telefonda yana kaydırma yok, rahat kaydırma, arama, filtre ve sıralama. "Tablo" düğmesi Excel benzeri görünüme geçer.
- **Parça listesi:** Sadeleştirilmiş araç çubuğu (Göster, Excel / e-posta, İçe aktar menüleri).
- **Bağlantı:** Sunucunun adresi değişirse Windows uygulaması ağdaki sunucuyu kendisi bulur. Kurulum Windows Güvenlik Duvarı iznini ekler.
- **Düzeltme:** "Yeni sürüm var" uyarısı güncel sürümde artık görünmüyor ve kapatılabiliyor.
- **Kurulum kılavuzu:** KURULUM_KILAVUZU.md ile adım adım kurulum.

## 1.3.1 yenilikleri

- **Android:** İşlemciye göre ayrı APK dosyaları (arm64-v8a, armeabi-v7a, x86_64, x86) ve her telefonda çalışan genel APK.
- **Güncelleme:** Uygulama yeni sürümde telefona uygun APK'yı kendisi seçer.

## 1.3.0 yenilikleri

- **Android uygulaması:** Ağdaki sunucuyu kendisi bulur, son sunucuyu hatırlar. İndirmeler İndirilenler › LAB ERP klasörüne kaydedilir, fotoğraf eklerken kamera kullanılabilir, geri tuşu pencereleri ve menüyü kapatır.
- **Telefona uyumlu arayüz:** Telefonda kayan yan menü, alttan açılan pencereler, kaydırılabilir tablolar ve büyük dokunma alanları.
- **Profilim:** Her kullanıcı sağ üstteki adına tıklayarak kendi adını ve şifresini değiştirebilir.
- **Güvenlik:**
  - Hatalı giriş denemeleri sınırlandırıldı.
  - Şifre değişince diğer cihazlardaki oturumlar kapanır.
  - Şifreler en az 8 karakter.
  - Zayıf oturum anahtarı otomatik olarak güçlüsüyle değiştirilir.
  - Yüklenen dosyalar güvenli biçimde sunulur.
  - Excel formül saldırılarına ve bozuk/aşırı büyük dosyalara karşı koruma eklendi.
  - Tarayıcı güvenlik başlıkları eklendi.

## 1.2.0 yenilikleri

- **Parça fotoğrafları:** Parça detayında ve stok kartında birden fazla fotoğraf; sürükle-bırak, telefonda kamera, açıklama.
- **Küçük resimler:** Teknik resimler ekranında "Galeri" görünümü; PDF ve resimler büyük küçük resimlerle listelenir.
- **Yeni görüntüleyici:** Tıklayınca tam ekran; tekerlek veya iki parmakla yakınlaştırma, sürükleyerek kaydırma, çift tık, döndürme, ← → ile sonraki resim.
- **Sohbet:** Kişiye özel ve grup mesajlaşma, dosya ve resim gönderme (sürükle-bırak, yapıştır), okundu işareti, okunmamış sayacı ve bildirim.

## 1.1.0 yenilikleri

- **Canlı eşitleme:** Aynı ağdaki cihazlarda yapılan değişiklikler birkaç saniye içinde tüm açık ekranlara yansır. Üst çubukta "Canlı" göstergesi vardır.
- **Kullanıcı yetkileri:** Yönetim › Kullanıcılar ekranında her kullanıcıya modül bazında Yok / Görüntüle / Düzenle yetkisi verilir.
- **Yeni ana sayfa:** Özet kutucukları, dikkat gerektirenler, işlem grafiği ve son işlemler.
- **Satış ve teklif:** Teklif ve satış siparişleri, iskonto, KDV, Excel teklif formu, siparişten fatura.
- **Fatura ve ödeme:** Satış ve alış faturaları, tahsilat ve ödemeler, vade takibi, cari bakiye ve ekstre.
- **Personel ve zaman:** Personel kartları ve projeye yazılan çalışma saatleri; işçilik maliyeti projeye eklenir.
- **Cari kartlar:** Müşteri firma türü ve firma bakiyesi.
- **Yeni arayüz:** Gruplu, daraltılabilir yan menü, simgeler ve sade sayfa başlıkları.

## Kurulum

- İlk açılışta "Bu bilgisayar sunucu" veya "Ağdaki sunucuya bağlan" seçilir.
- Sunucu modunda veriler seçilen klasörde (varsayılan Belgeler\ParcaTakipERP) tutulur, her gece yedek alınır. Güvenlik duvarı sorarsa Özel ağlar için izin verin.
- İstemci modunda "Ağda sunucu ara" düğmesi ağdaki sunucuları bulur.
- Uygulama açılışta yeni sürümü kendisi denetler; menüde "Güncellemeleri denetle" de vardır.
