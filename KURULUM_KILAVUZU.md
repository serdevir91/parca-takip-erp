# Kurulum kılavuzu (kolay yol)

Bu kılavuz, LAB ERP'yi ilk kez kuracak kişi içindir. Teknik ayrıntılar ve Docker kurulumu
[README.md](README.md) dosyasındadır.

Sistem iki parçadan oluşur:

- **Sunucu:** Verilerin tutulduğu tek bilgisayar. Mesai boyunca açık kalmalıdır.
- **İstemci:** Sunucuya bağlanan diğer cihazlar. Bunlar Windows uygulaması, Android uygulaması veya
  herhangi bir tarayıcı olabilir.

Tüm cihazlar aynı ağda (aynı modem / Wi-Fi) olmalıdır. İnternet gerekmez.

İndirmeler: [Releases](https://github.com/serdevir91/parca-takip-erp/releases/latest) sayfası.

| Dosya | Ne için |
|---|---|
| `LabERP-Setup-x.y.z.exe` | Windows uygulaması (sunucu veya istemci) |
| `LabERP-x.y.z.apk` | Android uygulaması (her telefonda çalışır) |

## 1. Sunucuyu kurun (bir kez)

En kolay yol, bir Windows bilgisayarı sunucu yapmaktır. Docker, Python veya başka bir program gerekmez.

1. `LabERP-Setup-x.y.z.exe` dosyasını indirip çalıştırın.
2. Kurulum "kimin için kurulsun" diye sorarsa **Tüm kullanıcılar için** seçin ve yönetici iznini onaylayın.
   Böylece kurulum, Windows Güvenlik Duvarı iznini kendisi ekler.
3. Uygulamayı açın ve **Bu bilgisayar sunucu** seçin.
4. Veri klasörünü onaylayın (varsayılan `Belgeler\LabERP`).
5. Yönetici (`admin`) şifresini belirleyin. Bu şifreyi unutmayın.
6. Windows Güvenlik Duvarı izin sorarsa **Özel ağlar** kutusunu işaretleyip **İzin ver** deyin.
7. Ekranda sunucunun adresi yazar (örnek `http://192.168.1.20:8000`). Bu adresi not edin.
8. Pencereyi kapattığınızda sunucu durmaz; uygulama saatin yanındaki gizli simgelere iner. Sunucuyu tamamen
   kapatmak için simgeye sağ tıklayıp **Sunucuyu durdur ve çık** seçin.

Notlar:

- Sunucu bilgisayarın ağı **Özel** (Private) olmalıdır: Ayarlar › Ağ ve İnternet › Wi-Fi/Ethernet ›
  Ağ profili türü › **Özel**. Ağ "Ortak" ise diğer cihazlar bağlanamaz.
- Modemden bu bilgisayara sabit IP vermek (DHCP rezervasyonu) adresin değişmesini önler. Zorunlu değildir:
  uygulamalar adres değişirse sunucuyu kendileri yeniden bulur.
- Sunucu her gece yedek alır. Yedekler veri klasöründeki `backups` klasöründedir.

### Linux sunucuya otomatik kurulum (Sunucuma kur)

Şirkette bir Linux sunucu varsa (Ubuntu, Debian, Rocky, Alma, Fedora; kendi sunucunuz veya bulut), Windows
uygulaması LAB ERP'yi oraya kendisi kurar.

1. Windows bilgisayarda `LabERP-Setup-x.y.z.exe` dosyasını kurup uygulamayı açın.
2. **Sunucuma kur** seçin. Uygulama zaten kuruluysa üst çubuktaki **Uygulama › Bağlantı ayarları** ile bu
   ekrana dönün.
3. Sunucu adresini (örnek `192.168.1.50`), SSH portunu (genellikle `22`), SSH kullanıcı adını ve şifresini
   yazın. Kullanıcı `root` değilse sudo yetkisi olmalıdır; aynı şifre sudo için kullanılır.
4. Yönetici (`admin`) şifresini belirleyin (en az 8 karakter).
5. **Kur ve bağlan** deyin. İlerleme ekranda görünür; kurulum birkaç dakika sürer. Bittiğinde bu bilgisayar
   sunucuya bağlanır. Diğer cihazlar `http://SUNUCU-ADRESİ:8000` ile bağlanır.

Notlar:

- Sunucunun internete çıkabilmesi gerekir (Python paketleri indirilir).
- Uygulama `/opt/laberp`, veriler ve yedekler `/var/lib/laberp` klasörüne kurulur. `laberp` hizmeti sunucu
  açılınca kendiliğinden başlar. Durum: `systemctl status laberp`, günlük: `journalctl -u laberp`.
- Sunucuyu güncellemek için yeni sürüm Windows uygulamasında aynı adımları tekrarlayın. Yönetici şifresini boş
  bırakırsanız şifre değişmez; veriler korunur.
- "Güvenlik duvarında bu portu aç" kutusu sunucudaki ufw veya firewalld'da portu açar. Bulut sunucularda
  sağlayıcının panelindeki güvenlik grubunda da portu (8000/TCP) açmanız gerekir.
- SSH anahtarıyla giriş için **SSH anahtarıyla giriş** bölümünden özel anahtar dosyasını seçin.

Mac veya Linux sunucuda elle kurulum: [README.md › Docker'sız kurulum](README.md#dockersız-kurulum) bölümündeki
`python -m app.cli serve` komutu yeterlidir.

## 2. İstemcileri bağlayın

### Windows

1. Aynı `LabERP-Setup-x.y.z.exe` dosyasını kurun.
2. Uygulamayı açın ve **Ağdaki sunucuya bağlan** seçin.
3. **Ağda sunucu ara** düğmesine basın ve çıkan sunucuyu seçin. Çıkmazsa adresi elle yazın
   (örnek `http://192.168.1.20:8000`).
4. Uygulama bu sunucuyu hatırlar. Sunucunun adresi sonradan değişirse uygulama ağı tarar, tek sunucu
   bulursa ona kendisi geçer.

### Android

1. Telefonda `LabERP-x.y.z.apk` dosyasını indirip açın. "Bilinmeyen kaynaklar" izni sorulursa
   tarayıcıya izin verin.
2. Uygulama ağdaki sunucuyu kendisi arar. Bulunan sunucuya dokunun ya da adresi yazın.

### Tarayıcı

Herhangi bir cihazda tarayıcıya sunucunun adresini yazın (örnek `http://192.168.1.20:8000`).

## 3. Hesap açma ve onay

Yeni çalışanlar kendi hesaplarını ister, yönetici onaylar. Bu özellik yeni kurulumlarda kapalıdır. Yönetici önce
**Yönetim › Kullanıcılar** ekranından hesap isteklerini açar. Açmak istemezseniz hesapları aynı ekrandan siz oluşturun.

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
   Roller işe göre gelir: Personel ve zaman (saat ücretleri) ile Fatura ve ödemeler yalnızca Admin'de açıktır.
   Başka birine gerekiyorsa o modülü kullanıcıya ayrıca açın.
4. Kaydedin. Çalışan artık giriş yapabilir.
5. İstenmeyen istek için **Reddet** deyin; istek silinir.

Her çalışan **Personel kartım** ekranında yalnızca kendi kartını ve çalışma saatlerini görür. Bunun için
**Personel ve zaman › Personel** sekmesinde kişinin kartını açıp **Kullanıcı hesabı** alanından hesabını seçin
(bağlantıyı yalnızca yönetici kurar; e-posta eşleşmesi artık sayılmaz).

**Mesai takibi:** Çalışan menüdeki **Mesai takibi** ekranından giriş ve çıkış yapar, yalnızca kendi mesaisini görür.
Yöneticiye herkesi göstermek için **Mesai takibi (tüm personel)** modülünü açın: Görür herkesi listeler, Düzenler
kayıt ekler ve düzeltir. Haftalık çalışma saati ve mola süresi Sistem Ayarları'nda.

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
- **Ara** kutusu tüm sütunlarda arar. **Filtre** düğmesi sütun filtrelerini açar. Sütun başlığındaki ok, değer listesinin yanında koşul da sunar: içerir, eşittir, büyüktür, arasında, boş ve benzerleri.
- **Gelişmiş** düğmesi kural grupları kurar. Grubun içi VE ya da VEYA olur; gruplar birlikte uygulanır. Filtre, sıralama ve sütun düzeni **Görünümler** menüsünden adla kaydedilir. Kayıtlı görünümler o cihazda tutulur.
- Tablo modunda hücreye tıklayıp ok tuşlarıyla gezin, yazmaya başlayıp düzenleyin. Fareyle ya da Shift ile aralık seçin. Ctrl+C, Ctrl+X, Ctrl+V Excel ile karşılıklı çalışır. Köşedeki tutamağı sürükleyerek doldurun: 1, 2 ya da A1, A2 seri olarak devam eder. Ctrl+Z geri alır, Ctrl+F bulur, Ctrl+H değiştirir. Sağ tık menüsü aynı işleri sunar. Durum çubuğu seçimin toplamını ve ortalamasını gösterir.
- **Sütunlar** düğmesi sütun gizler, sıralar ve sabitler. Paylaş menüsü ekranda görünen satır ve sütunları `.xlsx` olarak indirir.
- Formül, grafik, pivot, makro ve birbirinden ayrı aralık seçimi yoktur. Bunlar için listeyi `.xlsx` olarak indirip Excel'de açın.
- Parça listesinde filtreleyip satırları seçin, üstteki çubuktan **İlerleme ata** ya da **Temin ata** ile hepsini birden değiştirin. Bu iki modda da çalışır.
- **Parça adı** tablodan yazılır ya da yapıştırılır. Çok sayıda ad için **İçe aktar > Parça adlarını yapıştır**: Excel'den parça no ve ad sütunlarını kopyalayın. Ad, aynı parça numarasının geçtiği tüm projelerde görünür.
- Temin şekilleri **Yönetim > Sistem Ayarları** altından eklenir. Her türün davranışı, teknik resim isteyip istemediği ve sipariş önerisi ayrı seçilir.
- Kartta düzenlenebilir alanların altı kesik çizgilidir; dokunup değiştirin. ✎ düğmesi boş alanları da gösterir.
- Parça listesi ve Bağlantı elemanları ekranında satırları seçip **Gizle** deyin: satır listede kalır, yalnızca soluk görünür. Hesaplar değişmez.

## Sorun giderme

| Belirti | Çözüm |
|---|---|
| "Ağda sunucu ara" hiçbir şey bulmuyor | Sunucu bilgisayarda uygulama açık mı? Aynı Wi-Fi'da mısınız? Adresi elle yazmayı deneyin. |
| "Sunucuya ulaşılamadı" | Sunucuda Windows Güvenlik Duvarı'nda "LAB ERP" (veya Python) için **Özel** ağ izni olmalı. Ağ profili **Özel** olmalı. |
| Telefon bağlanamıyor, bilgisayar bağlanıyor | Modemde "misafir ağı" veya "AP/istemci yalıtımı" açık olabilir; telefonu ana Wi-Fi ağına bağlayın. |
| Adres değişti | Uygulamalar sunucuyu kendileri yeniden arar. Olmazsa "Sunucuyu değiştir" ile yeni adresi seçin. Kalıcı çözüm: modemde sabit IP. |
| Giriş ekranında **Hesap oluştur** yok | Yönetici Yönetim › Kullanıcılar ekranından hesap isteklerini açmalı. |
| Telefon: "Sunucunun sertifikası değişmiş" uyarısı | Sunucunun HTTPS sertifikası değişmiş. Değişikliği siz yaptıysanız "Sunucuyu değiştir" ile sunucuyu unutup yeniden bağlanın. Yapmadıysanız bağlanmayın, ağı kontrol edin. |
| Telefon: "Bu sunucu HTTPS kullanıyor" uyarısı | Sunucuya `https://` ile bağlanın. Sunucuda HTTPS kapatıldıysa önce sunucuyu Son kullanılanlar listesinden silin. |
| Barkod ekranında canlı kamera yok | Tarayıcı düz HTTP'de kamerayı açmaz. Yönetim › HTTPS ile HTTPS'i açın veya fotoğrafla okutun. |
| 1.5.10'a geçince herkes çıkış yaptı | Beklenen durum: oturum çerezine geçildi, bir kez yeniden giriş yapılır. |
| Beklenen mesai tatil gününü sayıyor | Yönetim › Resmi Tatiller ekranından tatili ekleyin. Dini bayramlar her yıl elle girilir. |
| Giriş: "Hesabınız yönetici onayı bekliyor" | Yönetici Yönetim › Kullanıcılar ekranından onaylamalı. |
| Giriş: "Hesabınız pasif" | Yönetici hesabı pasif yapmış; Kullanıcılar ekranından tekrar aktif yapılabilir. |
| E-posta: "kullanıcı adı/şifreyi kabul etmedi" | Gmail'de normal şifre yerine uygulama şifresi kullanın. |
| "Yeni sürüm var" uyarısı | İstemci uygulamanın yeni sürümünü kurun veya sayfayı yenileyin. ✕ ile o oturum için kapatılabilir. |
| Yönetici şifresi unutuldu | Sunucuda: `python -m app.cli create-admin --username admin --password YeniSifre123` |
