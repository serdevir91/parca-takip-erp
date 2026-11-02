# Parça Takip ERP

Yerel ağda (internetsiz) çalışan parça takip sistemi. SolidWorks BOM listeleri, teknik resimler,
üretim ve satın alma durumu tek yerde tutulur. Tarayıcıdan kullanılır, istemci bilgisayarlara kurulum gerekmez.

Sistem dört Docker konteynerinden oluşur:

| Servis | Görevi |
|---|---|
| `db` | PostgreSQL 16 veritabanı (`pgdata` volume) |
| `backend` | API (FastAPI). Açılışta veritabanı şemasını otomatik günceller (`alembic upgrade head`) |
| `backup` | Her gün belirlenen saatte yedek alır, eski yedekleri siler |
| `frontend` | Web arayüzü (nginx). `/api` isteklerini backend'e iletir, 2 GB'a kadar yüklemeye izin verir |

Çalışırken internet gerekmez. Arayüz CDN kullanmaz, tüm dosyalar imajın içindedir.

## İçindekiler

1. [Gereksinimler](#gereksinimler)
2. [Kurulum: Linux](#kurulum-linux)
3. [Kurulum: Windows](#kurulum-windows)
4. [Offline kurulum (internetsiz sunucu)](#offline-kurulum-internetsiz-sunucu)
5. [İlk giriş](#ilk-giriş)
6. [Yedekleme ve geri yükleme](#yedekleme-ve-geri-yükleme)
7. [Güncelleme](#güncelleme)
8. [Roller](#roller)
9. [Ayarlar (.env)](#ayarlar-env)
10. [Sorun giderme](#sorun-giderme)
11. [Geliştirme](#geliştirme)

## Gereksinimler

- 64 bit sunucu, en az 4 GB RAM (8 GB önerilir), çizimler ve yedekler için yeterli disk.
- Linux: Docker Engine 24+ ve Docker Compose v2 (`docker compose`).
- Windows 10/11 veya Windows Server: Docker Desktop (WSL 2 altyapısıyla).
- İstemciler: güncel Chrome, Edge veya Firefox.

> Komutlarda `docker compose` yazıyor. Eski kurulumlarda `docker-compose` (tireli) kullanın.

## Kurulum: Linux

```bash
# 1. Proje klasörünü sunucuya kopyalayın, örneğin /opt/parca-takip
cd /opt/parca-takip

# 2. Ayar dosyasını oluşturun ve düzenleyin (şifreler ve oturum anahtarı)
cp .env.example .env
nano .env

# 3. İmajları derleyin ve başlatın (derleme için internet gerekir, bir kez yapılır)
docker compose up -d --build

# 4. Durumu kontrol edin: hepsi "running", db ve backend "healthy" olmalı
docker compose ps
```

Tarayıcıdan `http://SUNUCU_IP` adresini açın (port 80 değilse `http://SUNUCU_IP:PORT`).

Sunucu yeniden başladığında servisler otomatik açılır (`restart: unless-stopped`).
Docker'ın açılışta başlaması için: `sudo systemctl enable docker`.

Güvenlik duvarı açıksa portu izin verin, örneğin: `sudo ufw allow 80/tcp`.

## Kurulum: Windows

### Kolay kurulum (önerilen)

1. **Docker Desktop**'ı kurun: https://www.docker.com/products/docker-desktop/
   Kurulumda "Use WSL 2 instead of Hyper-V" seçili kalsın. Bitince bilgisayarı yeniden başlatın.
   Docker Desktop ayarlarında "Start Docker Desktop when you sign in" seçili olsun.
2. Projeyi indirin:
   - Git varsa: `git clone https://github.com/KULLANICI/parca-takip-erp.git C:\ParcaTakip`
   - Git yoksa: GitHub sayfasında **Code > Download ZIP**, ZIP'i `C:\ParcaTakip` klasörüne açın.
   Klasör yolunda Türkçe karakter ve boşluk olmaması önerilir.
3. `C:\ParcaTakip\KURULUM.bat` dosyasına çift tıklayın ve yönetici iznini onaylayın.

`KURULUM.bat` şunları yapar:

- Docker'ın kurulu ve çalışır olduğunu kontrol eder, kapalıysa Docker Desktop'ı başlatır.
- İlk kurulumda `.env` dosyasını oluşturur. Veritabanı şifresi, oturum anahtarı ve yönetici şifresi rastgele üretilir.
- Port 80 doluysa (IIS, Skype vb.) 8080 gibi boş bir port seçer.
- İmajları derler ve sistemi başlatır (ilk kurulumda internet gerekir, 5-10 dakika sürebilir).
- Windows Güvenlik Duvarı'nda portu yerel ağa açar.
- Sonunda erişim adreslerini, kullanıcı adını ve ilk şifreyi yazar, tarayıcıyı açar.

Aynı dosya güncelleme için de kullanılır: yeni sürüm dosyalarını klasöre kopyalayıp tekrar çalıştırın.
`.env` ve veriler korunur.

Seçenekler (PowerShell'den):

```powershell
powershell -ExecutionPolicy Bypass -File deploy\windows_install.ps1 -Demo        # demo projelerle
powershell -ExecutionPolicy Bypass -File deploy\windows_install.ps1 -Port 8080   # belirli port
```

### Elle kurulum

```powershell
cd C:\ParcaTakip
copy .env.example .env
notepad .env
docker compose up -d --build
docker compose ps
New-NetFirewallRule -DisplayName "Parca Takip ERP" -Direction Inbound -Protocol TCP -LocalPort 80 -Action Allow
```

Not: Docker Desktop, bir kullanıcı oturum açınca başlar. Sunucu kimse oturum açmadan çalışacaksa
otomatik oturum açma ayarlayın veya Linux kurulumu tercih edin.

**Windows'ta sık sorunlar:**

- *"WSL 2 installation is incomplete"*: Yönetici PowerShell'de `wsl --install` çalıştırıp bilgisayarı yeniden başlatın.
- *Sanallaştırma kapalı*: BIOS'ta Intel VT-x / AMD-V (SVM) seçeneğini açın.
- *"Windows container modunda"*: Sistem tepsisindeki Docker simgesine sağ tıklayıp "Switch to Linux containers" seçin.
- *Diğer bilgisayarlar erişemiyor*: Ağ profili "Ortak" ise "Özel" yapın, güvenlik duvarı kuralını kontrol edin.

## Offline kurulum (internetsiz sunucu)

İnternete bağlı bir bilgisayarda imajlar hazırlanır ve tek bir `.tar` dosyası olarak sunucuya taşınır.

**1. İnternetli bilgisayarda (Docker kurulu, proje klasöründe):**

```bash
# Linux / macOS
deploy/offline_export.sh 1.0.0
```

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File deploy\offline_export.ps1 -Tag 1.0.0
```

Bu komut `dist-offline/` klasörünü oluşturur:

- `parca-takip-images-1.0.0.tar`: backend, frontend ve postgres imajları
- `parca-takip-images-1.0.0.tar.sha256`: bozulma kontrolü için sağlama toplamı
- `docker-compose.yml`, `.env.example`, `README.md`, `deploy/`

**2. `dist-offline` klasörünü USB disk ile sunucuya kopyalayın.**

Sunucuda Docker kurulu olmalıdır. Docker'ın kendisi de offline kurulacaksa, kurulum paketlerini
(Linux için `.deb`/`.rpm` paketleri, Windows için Docker Desktop kurulum dosyası) ayrıca indirip taşıyın.

**3. Sunucuda, kopyalanan klasörün içinde:**

```bash
# Linux
deploy/offline_import.sh
```

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File deploy\offline_import.ps1
```

İlk çalıştırmada `.env` dosyası oluşturulur ve betik durur. `.env` dosyasındaki şifreleri değiştirin,
sonra betiği tekrar çalıştırın. Betik imajları yükler (`docker load`), `ERP_TAG` değerini ayarlar
ve sistemi başlatır (`docker compose up -d --no-build`).

## İlk giriş

1. Tarayıcıdan `http://SUNUCU_IP` adresini açın.
2. `.env` içindeki `ERP_ADMIN_USER` / `ERP_ADMIN_PASSWORD` ile giriş yapın (elle kurulumda varsayılan `admin` / `admin`;
   `KURULUM.bat` rastgele şifre üretir ve kurulum sonunda ekrana yazar).
3. **Hemen Yönetim > Kullanıcılar ekranından yönetici şifresini değiştirin.**
4. Çalışanlar için kullanıcı açın ve rol verin (bkz. [Roller](#roller)).
5. Yönetim > Firmalar ekranında üretici ve tedarikçi firmaları kontrol edin.
6. Yönetim > Ayarlar ekranında parça numarası desenlerini ve satın alınan montajları kontrol edin.

Yönetici hesabı varsayılan değerlerle yalnızca veritabanında hiç kullanıcı yokken oluşturulur.
Sonradan `.env` değiştirmek mevcut şifreyi değiştirmez.

**Yönetici şifresi unutulursa:**

```bash
docker compose exec backend python -m app.cli create-admin --username admin --password YeniSifre123
```

Kullanıcı yoksa oluşturulur. Varsa aktif yönetici yapılır ve şifresi sıfırlanır.

**Deneme verisi (isteğe bağlı):** Örnek BOM ve T-35 listesiyle iki demo proje oluşturur:

```bash
docker compose exec backend python -m app.cli seed
```

Gerçek kullanımda demo projeleri arşivleyin veya bu komutu çalıştırmayın.

## Yedekleme ve geri yükleme

### Otomatik yedek

`backup` servisi her gün `ERP_BACKUP_TIME` saatinde (varsayılan 02:00) yedek alır.
Son `ERP_BACKUP_KEEP_DAYS` gün (varsayılan 14) saklanır, daha eskiler silinir. En son yedek hiçbir zaman silinmez.

Her yedek tek bir dosyadır: `erp_YYYYMMDD_HHMMSS.tar`. İçinde şunlar vardır:

- `db.dump`: veritabanı dökümü (`pg_dump` özel biçim)
- `data/`: yüklenen BOM dosyaları, teknik resimler ve küçük resimler
- `manifest.json`: yedek tarihi, uygulama sürümü, dosya sayısı

Yedekler varsayılan olarak `erpbackups` Docker volume'unda durur. **Disk arızasına karşı yedekleri
başka bir diske de alın.** Bunun için `.env` dosyasında `ERP_BACKUP_PATH` değerine bir klasör yolu
yazın (örneğin `/srv/erp-yedek` veya `D:/ERP-Yedek`) ve `docker compose up -d` çalıştırın.
Linux'ta bu klasör konteyner kullanıcısına (uid 1000) yazılabilir olmalıdır:
`sudo mkdir -p /srv/erp-yedek && sudo chown 1000:1000 /srv/erp-yedek`.

### Elle yedek

- Arayüzden: Yönetim > Yedekleme > "Şimdi yedek al". Aynı ekrandan yedekler indirilebilir.
- Komutla:

```bash
deploy/backup.sh               # yeni yedek al
deploy/backup.sh /mnt/usb      # yedek al ve USB diske kopyala
deploy/backup.sh --list        # yedekleri listele
```

```powershell
powershell -ExecutionPolicy Bypass -File deploy\backup.ps1 -CopyTo E:\Yedek
```

### Geri yükleme

Geri yükleme mevcut veritabanının ve dosyaların **üzerine yazar**. Önce o anki durumun yedeğini alın.

```bash
# 1. Kullanıcıların işlem yapmaması için backend ve backup servislerini durdurun
docker compose stop backend backup frontend

# 2. Dışarıdan getirilen bir yedek varsa önce yedek klasörüne kopyalayın
#    (yedek zaten listedeyse bu adımı atlayın)
docker compose run --rm --no-deps -v "$PWD:/import" backend cp /import/erp_20261102_020000.tar /backups/

# 3. Geri yükleyin (dosya adı /backups içindeki yedek)
docker compose run --rm backend python -m app.cli restore /backups/erp_20261102_020000.tar --yes

# 4. Servisleri başlatın (şema farkı varsa backend açılışta günceller)
docker compose up -d
```

Windows PowerShell'de 2. adımda `$PWD` yerine `${PWD}` yazın.

Yedek dosyasının içeriğini görmek için: `tar -tf erp_20261102_020000.tar`.

## Güncelleme

Güncellemeden önce mutlaka elle bir yedek alın (`deploy/backup.sh`).

**İnternetli sunucuda:**

```bash
# Yeni sürüm dosyalarını proje klasörüne kopyalayın (veya git pull), sonra:
docker compose up -d --build
```

**Offline sunucuda:**

1. İnternetli bilgisayarda yeni sürümle `deploy/offline_export.sh 1.1.0` çalıştırın.
2. `dist-offline` klasörünü sunucuya kopyalayın. Sunucudaki `.env` dosyasını koruyun.
3. Sunucuda `deploy/offline_import.sh` (Windows: `deploy\offline_import.ps1`) çalıştırın.

Backend her açılışta veritabanı şemasını otomatik günceller (`alembic upgrade head`), elle işlem gerekmez.
Veriler volume'larda durduğu için konteynerlerin yeniden oluşturulması veri kaybettirmez.

Sorun çıkarsa eski sürüme dönmek için `.env` içindeki `ERP_TAG` değerini eski sürüme çevirin,
`docker compose up -d` çalıştırın ve güncelleme öncesi yedeği geri yükleyin.

**Dikkat:** `docker compose down -v` komutu volume'ları, yani **tüm verileri siler**. `-v` kullanmayın.

## Roller

| Rol | Yapabildikleri |
|---|---|
| **Admin** | Her şey. Kullanıcı, firma, ayar yönetimi; denetim kaydı (audit log); yedekleme. |
| **Tasarımcı** | Proje açma, BOM yükleme ve onaylama, teknik resim yükleme, durum güncelleme. |
| **Planlama / Satın alma** | Üretim ve malzeme durumunu güncelleme, T-35 listesi aktarma, bağlantı elemanı siparişi. |
| **İzleyici** | Sadece görüntüleme ve dışa aktarma. Değişiklik yapamaz. |

Kurallar:

- Kullanıcılar silinmez, pasif yapılır. Böylece denetim kaydında isimleri kalır.
- Son aktif yönetici pasif yapılamaz ve rolü değiştirilemez.
- Yönetici kendi hesabını pasif yapamaz ve kendi yönetici rolünü kaldıramaz.
- Her değişiklik denetim kaydına yazılır: kim, ne zaman, hangi alan, eski ve yeni değer.

## Ayarlar (.env)

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `ERP_HTTP_PORT` | `80` | Arayüzün yayınlandığı port |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `erp` / `erp` / `erp` | Veritabanı bilgileri. Şifrede `@ : / ?` karakterlerini kullanmayın. |
| `ERP_JWT_SECRET` | `change-me` | Oturum anahtarı. Uzun ve rastgele olmalı. Değişirse herkes yeniden giriş yapar. |
| `ERP_ADMIN_USER` / `ERP_ADMIN_PASSWORD` | `admin` / `admin` | İlk yönetici (yalnızca ilk açılışta) |
| `ERP_BACKUP_TIME` | `02:00` | Günlük yedek saati |
| `ERP_BACKUP_KEEP_DAYS` | `14` | Kaç günlük yedek saklanır |
| `ERP_BACKUP_PATH` | `erpbackups` | Yedeklerin yeri: volume adı veya klasör yolu |
| `ERP_MAX_UPLOAD_MB` | `2048` | En büyük yükleme |
| `ERP_UPDATE_FEED_URL` | boş | Yerel ağdaki sürüm bilgisi adresi (güncelleme bildirimi) |
| `TZ` | `Europe/Istanbul` | Saat dilimi |
| `ERP_IMAGE_PREFIX` / `ERP_TAG` | `parca-takip` / `latest` | İmaj adı ve sürümü |

`POSTGRES_PASSWORD` ilk kurulumda veritabanına yazılır. Sonradan `.env` içinde değiştirmek yetmez.
Önce veritabanında da değiştirin:
`docker compose exec db psql -U erp -c "ALTER USER erp PASSWORD 'yeni'"`.

## Sorun giderme

```bash
docker compose ps                 # servis durumları
docker compose logs -f backend    # backend günlükleri
docker compose logs --tail 50 backup
curl http://localhost/api/health  # sağlık kontrolü, {"status": "ok"} döner
```

- **Arayüz açılıyor ama giriş yapılamıyor:** `docker compose logs backend` çıktısını kontrol edin.
  Veritabanı bağlantı hatası varsa `.env` içindeki `POSTGRES_*` değerlerini kontrol edin.
- **Büyük dosya yüklenmiyor:** `ERP_MAX_UPLOAD_MB` değerini ve diskteki boş alanı kontrol edin.
- **Yedek alınmıyor:** `docker compose logs backup` çıktısına bakın. Yönetim > Yedekleme ekranı
  son yedek tarihini ve boş disk alanını gösterir.
- **Port 80 dolu:** `.env` içinde `ERP_HTTP_PORT=8080` yapın ve `docker compose up -d` çalıştırın.

## Geliştirme

```bash
# Backend (SQLite ile, PostgreSQL gerekmez)
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
ERP_DATABASE_URL=sqlite:///./dev.db ERP_DATA_DIR=./data ERP_BACKUP_DIR=./backups \
  .venv/bin/uvicorn app.main:app --reload
.venv/bin/python -m pytest -q

# Frontend (http://localhost:5173, /api isteklerini backend'e yönlendirir)
cd frontend
npm ci && npm run dev
```

Komut satırı araçları (`python -m app.cli`):

| Komut | Açıklama |
|---|---|
| `seed [--force]` | Örnek dosyalarla demo projeler oluşturur |
| `backup [--daemon --at 02:00]` | Yedek alır; `--daemon` ile her gün aynı saatte |
| `restore DOSYA [--yes]` | Yedekten geri yükler |
| `create-admin --username U --password P` | Yönetici oluşturur veya şifresini sıfırlar |

Veritabanı şeması değişikliği: `backend/app/models.py` düzenlendikten sonra
`cd backend && .venv/bin/alembic revision --autogenerate -m "aciklama"` ile migration oluşturun.
Ayrıntılı gereksinimler: `docs/SPEC.md`.
