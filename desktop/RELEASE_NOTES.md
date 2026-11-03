Windows masaüstü uygulaması: `LabERP-Setup-x.y.z.exe` dosyasını indirip çalıştırın.
Android uygulaması: telefonda `LabERP-x.y.z.apk` dosyasını indirip kurun (Android 8.0 ve üstü). Bu dosya her telefonda çalışır; `-arm64-v8a`, `-armeabi-v7a`, `-x86_64` ve `-x86` dosyaları işlemciye özel sürümlerdir.

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
