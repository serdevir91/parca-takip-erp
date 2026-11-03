# Kurulum kılavuzu (kolay yol)

Bu kılavuz, Parça Takip ERP'yi ilk kez kuracak kişi içindir. Teknik ayrıntılar ve Docker kurulumu
[README.md](README.md) dosyasındadır.

Sistem iki parçadan oluşur:

- **Sunucu:** Verilerin tutulduğu tek bilgisayar. Mesai boyunca açık kalmalıdır.
- **İstemci:** Sunucuya bağlanan diğer cihazlar. Bunlar Windows uygulaması, Android uygulaması veya
  herhangi bir tarayıcı olabilir.

Tüm cihazlar aynı ağda (aynı modem / Wi-Fi) olmalıdır. İnternet gerekmez.

İndirmeler: [Releases](https://github.com/serdevir91/parca-takip-erp/releases/latest) sayfası.

| Dosya | Ne için |
|---|---|
| `ParcaTakipERP-Setup-x.y.z.exe` | Windows uygulaması (sunucu veya istemci) |
| `ParcaTakipERP-x.y.z.apk` | Android uygulaması (her telefonda çalışır) |

## 1. Sunucuyu kurun (bir kez)

En kolay yol, bir Windows bilgisayarı sunucu yapmaktır. Docker, Python veya başka bir program gerekmez.

1. `ParcaTakipERP-Setup-x.y.z.exe` dosyasını indirip çalıştırın.
2. Kurulum "kimin için kurulsun" diye sorarsa **Tüm kullanıcılar için** seçin ve yönetici iznini onaylayın.
   Böylece kurulum, Windows Güvenlik Duvarı iznini kendisi ekler.
3. Uygulamayı açın ve **Bu bilgisayar sunucu** seçin.
4. Veri klasörünü onaylayın (varsayılan `Belgeler\ParcaTakipERP`).
5. Yönetici (`admin`) şifresini belirleyin. Bu şifreyi unutmayın.
6. Windows Güvenlik Duvarı izin sorarsa **Özel ağlar** kutusunu işaretleyip **İzin ver** deyin.
7. Ekranda sunucunun adresi yazar (örnek `http://192.168.1.20:8000`). Bu adresi not edin.

Notlar:

- Sunucu bilgisayarın ağı **Özel** (Private) olmalıdır: Ayarlar › Ağ ve İnternet › Wi-Fi/Ethernet ›
  Ağ profili türü › **Özel**. Ağ "Ortak" ise diğer cihazlar bağlanamaz.
- Modemden bu bilgisayara sabit IP vermek (DHCP rezervasyonu) adresin değişmesini önler. Zorunlu değildir:
  uygulamalar adres değişirse sunucuyu kendileri yeniden bulur.
- Sunucu her gece yedek alır. Yedekler veri klasöründeki `backups` klasöründedir.

Mac veya Linux sunucu: [README.md › Docker'sız kurulum](README.md#dockersız-kurulum) bölümündeki
`python -m app.cli serve` komutu yeterlidir.

## 2. İstemcileri bağlayın

### Windows

1. Aynı `ParcaTakipERP-Setup-x.y.z.exe` dosyasını kurun.
2. Uygulamayı açın ve **Ağdaki sunucuya bağlan** seçin.
3. **Ağda sunucu ara** düğmesine basın ve çıkan sunucuyu seçin. Çıkmazsa adresi elle yazın
   (örnek `http://192.168.1.20:8000`).
4. Uygulama bu sunucuyu hatırlar. Sunucunun adresi sonradan değişirse uygulama ağı tarar, tek sunucu
   bulursa ona kendisi geçer.

### Android

1. Telefonda `ParcaTakipERP-x.y.z.apk` dosyasını indirip açın. "Bilinmeyen kaynaklar" izni sorulursa
   tarayıcıya izin verin.
2. Uygulama ağdaki sunucuyu kendisi arar. Bulunan sunucuya dokunun ya da adresi yazın.

### Tarayıcı

Herhangi bir cihazda tarayıcıya sunucunun adresini yazın (örnek `http://192.168.1.20:8000`).

## 3. Hesap açma ve onay

Yeni çalışanlar kendi hesaplarını ister, yönetici onaylar.

**Çalışan:**

1. Giriş ekranında **Hesap oluştur** düğmesine basın.
2. Kullanıcı adı, ad soyad, e-posta (isteğe bağlı) ve şifre (en az 8 karakter) girin.
3. **Hesap isteği gönder** deyin. "Hesap isteğiniz yöneticiye gönderildi" mesajı çıkar.
4. Onaydan önce giriş denerseniz "Hesabınız yönetici onayı bekliyor" uyarısı görünür.

**Yönetici:**

1. `admin` ile giriş yapın. Sol menüde **Yönetim** yanında bekleyen istek sayısı görünür.
2. **Yönetim › Kullanıcılar** sekmesinin en üstünde **Onay bekleyen hesap istekleri** listesi vardır.
3. **Onayla ve yetki ver** düğmesine basın. Rolü seçin (İzleyici, Planlama/Satın alma, Tasarımcı, Admin)
   ve gerekirse modül yetkilerini tek tek değiştirin (Yok / Görür / Düzenler).
4. Kaydedin. Çalışan artık giriş yapabilir.
5. İstenmeyen istek için **Reddet** deyin; istek silinir.

Yetkiler sonradan da aynı ekrandan değiştirilebilir. Herkesin hesap istemesini kapatmak için
Kullanıcılar sekmesindeki **Girişte "Hesap oluştur" göster** kutusunun işaretini kaldırın.

## 4. E-posta (isteğe bağlı)

Listeleri e-postayla göndermek ve yeni hesap isteklerinde yöneticiye e-posta gitmesi için bir kez ayar gerekir.

1. **Yönetim › E-posta** sekmesini açın.
2. Hazır ayarlardan e-posta sağlayıcınızı seçin (Gmail, Outlook, Yandex, Yahoo) veya şirket sunucunuzu yazın.
3. Kullanıcı adı ve şifreyi girin.
   - **Gmail:** Normal şifre çalışmaz. Google Hesabı › Güvenlik › 2 Adımlı Doğrulama'yı açın, sonra
     **Uygulama şifreleri** bölümünden 16 haneli bir şifre oluşturup buraya yazın.
   - **Outlook / Yandex:** Hesapta iki adımlı doğrulama açıksa yine uygulama şifresi gerekir.
4. **Kaydet**, sonra **Test e-postası gönder** deyin.
5. Yöneticilerin **Profilim** penceresinde e-posta adresi olmalıdır; yeni hesap istekleri bu adrese bildirilir.

E-posta göndermek için sunucunun internete çıkabilmesi gerekir. Diğer her şey internetsiz çalışır.

**Liste gönderme:** Listelerin üstündeki **Paylaş ▾** menüsünde **E-posta ile gönder** vardır. Parça
listesinde **Excel / e-posta ▾** menüsü Excel dosyasını e-postaya ekler. Telefonda **Telefonla paylaş**
dosyayı Gmail, WhatsApp veya Drive ile gönderir; bunun için sunucuda e-posta ayarı gerekmez.

## 5. Listeleri kullanma

- Listeler varsayılan olarak **kart** görünümündedir: telefonda ve dar ekranda yana kaydırmak gerekmez.
- Sağ üstteki **Liste / Tablo** düğmesi Excel benzeri tabloya geçer. Seçim cihazda hatırlanır.
- **Ara** kutusu tüm sütunlarda arar. **Filtre** düğmesi sütun filtrelerini açar.
- Kartta düzenlenebilir alanların altı kesik çizgilidir; dokunup değiştirin. ✎ düğmesi boş alanları da gösterir.

## Sorun giderme

| Belirti | Çözüm |
|---|---|
| "Ağda sunucu ara" hiçbir şey bulmuyor | Sunucu bilgisayarda uygulama açık mı? Aynı Wi-Fi'da mısınız? Adresi elle yazmayı deneyin. |
| "Sunucuya ulaşılamadı" | Sunucuda Windows Güvenlik Duvarı'nda "Parca Takip ERP" (veya Python) için **Özel** ağ izni olmalı. Ağ profili **Özel** olmalı. |
| Telefon bağlanamıyor, bilgisayar bağlanıyor | Modemde "misafir ağı" veya "AP/istemci yalıtımı" açık olabilir; telefonu ana Wi-Fi ağına bağlayın. |
| Adres değişti | Uygulamalar sunucuyu kendileri yeniden arar. Olmazsa "Sunucuyu değiştir" ile yeni adresi seçin. Kalıcı çözüm: modemde sabit IP. |
| Giriş: "Hesabınız yönetici onayı bekliyor" | Yönetici Yönetim › Kullanıcılar ekranından onaylamalı. |
| Giriş: "Hesabınız pasif" | Yönetici hesabı pasif yapmış; Kullanıcılar ekranından tekrar aktif yapılabilir. |
| E-posta: "kullanıcı adı/şifreyi kabul etmedi" | Gmail'de normal şifre yerine uygulama şifresi kullanın. |
| "Yeni sürüm var" uyarısı | İstemci uygulamanın yeni sürümünü kurun veya sayfayı yenileyin. ✕ ile o oturum için kapatılabilir. |
| Yönetici şifresi unutuldu | Sunucuda: `python -m app.cli create-admin --username admin --password YeniSifre123` |
