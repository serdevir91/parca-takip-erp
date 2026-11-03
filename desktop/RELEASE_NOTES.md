Windows masaüstü uygulaması: `ParcaTakipERP-Setup-x.y.z.exe` dosyasını indirip çalıştırın.
Android uygulaması: telefonda `ParcaTakipERP-x.y.z.apk` dosyasını indirip kurun (Android 8.0 ve üstü). Bu dosya her telefonda çalışır; `-arm64-v8a`, `-armeabi-v7a`, `-x86_64` ve `-x86` dosyaları işlemciye özel sürümlerdir.

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

- **Android uygulaması:** Ağdaki sunucuyu kendisi bulur, son sunucuyu hatırlar. İndirmeler İndirilenler › ParcaTakip klasörüne kaydedilir, fotoğraf eklerken kamera kullanılabilir, geri tuşu pencereleri ve menüyü kapatır.
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
