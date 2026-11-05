"""Desktop shell localization (English, Spanish, German with Turkish fallback)."""
from __future__ import annotations

import locale
import sys

TEXT: dict[str, dict[str, str]] = {
    "en": {
        "Sunucu {0} portunda başlatılamadı": "Server could not be started on port {0}",
        "Bu işlem yalnızca ayarlar ekranından yapılabilir": "This operation can only be performed from the settings screen",
        "Bu sayfa uygulama işlemlerini kullanamaz": "This page cannot use application actions",
        "Sunucu adresini yazın": "Enter the server address",
        "{0} adresinde LAB ERP sunucusu bulunamadı": "LAB ERP server not found at {0}",
        "Kurulum sürüyor": "Installation in progress",
        "Port bir sayı olmalı": "Port must be a number",
        "Veri klasörünü seçin": "Select the data folder",
        "Port 1-65535 arasında olmalı": "Port must be between 1 and 65535",
        "Yönetici şifresi en az 8 karakter olmalı": "Administrator password must be at least 8 characters",
        "Çalışma şeklini seçin": "Select operating mode",
        "Geçersiz istek": "Invalid request",
        "İndirme başarısız ({0})": "Download failed ({0})",
        "Sunucuya ulaşılamadı: {0}": "Could not reach server: {0}",
        "Dosya yazılamadı: {0}": "Could not write file: {0}",
        "GÜVENLİK UYARISI: Sunucunun sertifikası değişmiş, bağlantı kesildi. Araya biri girmiş olabilir. "
        "Sertifikayı yönetici değiştirdiyse bu ekrandan sunucuyu yeniden kaydedin.":
            "SECURITY WARNING: The server certificate has changed, connection closed. There may be an attacker. "
            "If the administrator changed the certificate, re-register the server on this screen.",
        "{0} ile güvenli bağlantı kurulamadı: {1}": "Could not establish secure connection to {0}: {1}",
        "GÜVENLİK UYARISI: Sunucunun sertifikası değişmiş, bağlanılmadı. Araya biri girmiş olabilir. "
        "Sertifikayı yönetici değiştirdiyse bu ekrandan sunucuyu yeniden kaydedin.":
            "SECURITY WARNING: The server certificate has changed, not connected. There may be an attacker. "
            "If the administrator changed the certificate, re-register the server on this screen.",
        "Güvenli bağlantı": "Secure connection",
        "{0} sunucusuna ilk kez güvenli bağlanılıyor.\n\nParmak izi:\n{1}\n\nSunucuda Yönetim > HTTPS ekranındaki parmak iziyle aynıysa onaylayın.":
            "Connecting securely to {0} for the first time.\n\nFingerprint:\n{1}\n\nConfirm if it matches the fingerprint in Administration > HTTPS on the server.",
        "Sunucunun parmak izi onaylanmadı, bağlanılmadı.": "Server fingerprint not confirmed, connection aborted.",
        "{0} adresindeki sunucuya bağlanılamadı. Sunucu bilgisayarın açık, uygulamanın çalışır ve iki cihazın aynı ağda olduğunu kontrol edin.":
            "Could not connect to server at {0}. Check that the server computer is on, the application is running, and both devices are on the same network.",
        "Ağda birden fazla sunucu var, birini seçin.": "Multiple servers found on the network, select one.",
        "Sunucu adresi": "Server address",
        "{0} yanıt vermiyor. Ağda {1} adresinde bir sunucu bulundu.\n\nBu sizin sunucunuzsa ve adresi değiştiyse onaylayın.":
            "{0} is not responding. A server was found at {1} on the network.\n\nConfirm if this is your server and its address has changed.",
        "{0} adresindeki sunucuya bağlanılamadı.": "Could not connect to the server at {0}.",
        "{0} numaralı port başka bir program tarafından kullanılıyor. Ayarlardan başka bir port seçin.":
            "Port {0} is in use by another program. Select a different port in Settings.",
        "Sunucu başlatılamadı: {0}": "Could not start server: {0}",
        "{0} sunucusu çalışıyor": "{0} server is running",
        "{0} çalışıyor": "{0} is running",
        "Adres: {0}": "Address: {0}",
        "ağ bağlantısı yok": "no network connection",
        "{0} penceresini aç": "Open {0} window",
        "Sunucuyu durdur ve çık": "Stop server and exit",
        "Çık": "Exit",
        "Sunucu": "Server",
        "Uygulama": "Application",
        "{0} arka planda çalışmaya devam ediyor, bildirimler gelir. Kapatmak için saatin yanındaki gizli simgelerden {1} simgesine sağ tıklayın.":
            "{0} continues to run in the background, notifications will be delivered. To close, right-click the {1} icon next to the clock.",
        "Sunucu durur ve ağdaki diğer kullanıcıların bağlantısı kesilir. Kapatılsın mı?":
            "The server will stop and other network users will be disconnected. Close anyway?",
        "Bildirim testi": "Notification test",
        "Güncelleme sunucusuna ulaşılamadı.\n{0}": "Could not reach update server.\n{0}",
        "{0} güncel (sürüm {1}).": "{0} is up to date (version {1}).",
        "Yeni sürüm {0} hazır (kullandığınız sürüm {1}).": "New version {0} is ready (current version {1}).",
        "Güncelleme": "Update",
        "Şimdi indirip kurulsun mu?": "Download and install now?",
        "İndirme sayfası açılsın mı?": "Open download page?",
        "Bu güncellemenin imzası henüz yayımlanmamış. Birazdan yeniden deneyin.":
            "The signature for this update has not been published yet. Please try again later.",
        "Güncelleme indirilemedi.\n{0}": "Could not download update.\n{0}",
        "Güncelleme dosyasının imzası doğrulanamadı, dosya silindi ve kurulmadı.":
            "Update signature could not be verified; the file was deleted and not installed.",
        "Veri klasörü yalnızca sunucu modunda bu bilgisayardadır.":
            "The data folder is only on this computer in server mode.",
        "Bilinmeyen işlem: {0}": "Unknown action: {0}",
        "Uygulama kapanınca sunucu da durur ve ağdaki diğer kullanıcıların bağlantısı kesilir. Kapatılsın mı?":
            "Closing the application will also stop the server and disconnect other network users. Close anyway?",
    },
    "es": {
        "Sunucu {0} portunda başlatılamadı": "No se pudo iniciar el servidor en el puerto {0}",
        "Bu işlem yalnızca ayarlar ekranından yapılabilir": "Esta operación solo se puede realizar desde la pantalla de ajustes",
        "Bu sayfa uygulama işlemlerini kullanamaz": "Esta página no puede utilizar acciones de la aplicación",
        "Sunucu adresini yazın": "Introduzca la dirección del servidor",
        "{0} adresinde LAB ERP sunucusu bulunamadı": "No se encontró el servidor LAB ERP en {0}",
        "Kurulum sürüyor": "Instalación en curso",
        "Port bir sayı olmalı": "El puerto debe ser un número",
        "Veri klasörünü seçin": "Seleccione la carpeta de datos",
        "Port 1-65535 arasında olmalı": "El puerto debe estar entre 1 y 65535",
        "Yönetici şifresi en az 8 karakter olmalı": "La contraseña de administrador debe tener al menos 8 caracteres",
        "Çalışma şeklini seçin": "Seleccione el modo de funcionamiento",
        "Geçersiz istek": "Solicitud no válida",
        "İndirme başarısız ({0})": "Error de descarga ({0})",
        "Sunucuya ulaşılamadı: {0}": "No se pudo conectar con el servidor: {0}",
        "Dosya yazılamadı: {0}": "No se pudo escribir el archivo: {0}",
        "GÜVENLİK UYARISI: Sunucunun sertifikası değişmiş, bağlantı kesildi. Araya biri girmiş olabilir. "
        "Sertifikayı yönetici değiştirdiyse bu ekrandan sunucuyu yeniden kaydedin.":
            "ADVERTENCIA DE SEGURIDAD: El certificado del servidor ha cambiado, conexión cerrada. Podría haber un atacante. "
            "Si el administrador cambió el certificado, vuelva a guardar el servidor en esta pantalla.",
        "{0} ile güvenli bağlantı kurulamadı: {1}": "No se pudo establecer una conexión segura con {0}: {1}",
        "GÜVENLİK UYARISI: Sunucunun sertifikası değişmiş, bağlanılmadı. Araya biri girmiş olabilir. "
        "Sertifikayı yönetici değiştirdiyse bu ekrandan sunucuyu yeniden kaydedin.":
            "ADVERTENCIA DE SEGURIDAD: El certificado del servidor ha cambiado, no conectado. Podría haber un atacante. "
            "Si el administrador cambió el certificado, vuelva a guardar el servidor en esta pantalla.",
        "Güvenli bağlantı": "Conexión segura",
        "{0} sunucusuna ilk kez güvenli bağlanılıyor.\n\nParmak izi:\n{1}\n\nSunucuda Yönetim > HTTPS ekranındaki parmak iziyle aynıysa onaylayın.":
            "Conectando de forma segura a {0} por primera vez.\n\nHuella digital:\n{1}\n\nConfirme si coincide con la huella digital en Administración > HTTPS en el servidor.",
        "Sunucunun parmak izi onaylanmadı, bağlanılmadı.": "Huella digital del servidor no confirmada, conexión cancelada.",
        "{0} adresindeki sunucuya bağlanılamadı. Sunucu bilgisayarın açık, uygulamanın çalışır ve iki cihazın aynı ağda olduğunu kontrol edin.":
            "No se pudo conectar al servidor en {0}. Compruebe que el ordenador servidor esté encendido, la aplicación en ejecución y ambos dispositivos en la misma red.",
        "Ağda birden fazla sunucu var, birini seçin.": "Se encontraron varios servidores en la red, seleccione uno.",
        "Sunucu adresi": "Dirección del servidor",
        "{0} yanıt vermiyor. Ağda {1} adresinde bir sunucu bulundu.\n\nBu sizin sunucunuzsa ve adresi değiştiyse onaylayın.":
            "{0} no responde. Se encontró un servidor en la red en {1}.\n\nConfirme si este es su servidor y su dirección ha cambiado.",
        "{0} adresindeki sunucuya bağlanılamadı.": "No se pudo conectar al servidor en {0}.",
        "{0} numaralı port başka bir program tarafından kullanılıyor. Ayarlardan başka bir port seçin.":
            "El puerto {0} está siendo utilizado por otro programa. Seleccione otro puerto en Ajustes.",
        "Sunucu başlatılamadı: {0}": "No se pudo iniciar el servidor: {0}",
        "{0} sunucusu çalışıyor": "El servidor {0} está en ejecución",
        "{0} çalışıyor": "{0} está en ejecución",
        "Adres: {0}": "Dirección: {0}",
        "ağ bağlantısı yok": "sin conexión de red",
        "{0} penceresini aç": "Abrir ventana de {0}",
        "Sunucuyu durdur ve çık": "Detener servidor y salir",
        "Çık": "Salir",
        "Sunucu": "Servidor",
        "Uygulama": "Aplicación",
        "{0} arka planda çalışmaya devam ediyor, bildirimler gelir. Kapatmak için saatin yanındaki gizli simgelerden {1} simgesine sağ tıklayın.":
            "{0} continúa ejecutándose en segundo plano, se recibirán notificaciones. Para cerrar, haga clic derecho en el icono de {1} junto al reloj.",
        "Sunucu durur ve ağdaki diğer kullanıcıların bağlantısı kesilir. Kapatılsın mı?":
            "El servidor se detendrá y se desconectará a los demás usuarios de la red. ¿Cerrar?",
        "Bildirim testi": "Prueba de notificación",
        "Güncelleme sunucusuna ulaşılamadı.\n{0}": "No se pudo conectar con el servidor de actualizaciones.\n{0}",
        "{0} güncel (sürüm {1}).": "{0} está actualizado (versión {1}).",
        "Yeni sürüm {0} hazır (kullandığınız sürüm {1}).": "La nueva versión {0} está disponible (versión instalada {1}).",
        "Güncelleme": "Actualización",
        "Şimdi indirip kurulsun mu?": "¿Descargar e instalar ahora?",
        "İndirme sayfası açılsın mı?": "¿Abrir página de descargas?",
        "Bu güncellemenin imzası henüz yayımlanmamış. Birazdan yeniden deneyin.":
            "La firma de esta actualización aún no se ha publicado. Inténtelo de nuevo más tarde.",
        "Güncelleme indirilemedi.\n{0}": "No se pudo descargar la actualización.\n{0}",
        "Güncelleme dosyasının imzası doğrulanamadı, dosya silindi ve kurulmadı.":
            "No se pudo verificar la firma de la actualización; el archivo fue eliminado y no se instaló.",
        "Veri klasörü yalnızca sunucu modunda bu bilgisayardadır.":
            "La carpeta de datos solo está en este ordenador en modo servidor.",
        "Bilinmeyen işlem: {0}": "Acción desconocida: {0}",
        "Uygulama kapanınca sunucu da durur ve ağdaki diğer kullanıcıların bağlantısı kesilir. Kapatılsın mı?":
            "Al cerrar la aplicación, el servidor se detendrá y se desconectará a los demás usuarios de la red. ¿Cerrar?",
    },
    "de": {
        "Sunucu {0} portunda başlatılamadı": "Server konnte auf Port {0} nicht gestartet werden",
        "Bu işlem yalnızca ayarlar ekranından yapılabilir": "Dieser Vorgang kann nur über die Einstellungen ausgeführt werden",
        "Bu sayfa uygulama işlemlerini kullanamaz": "Diese Seite kann keine Anwendungsaktionen verwenden",
        "Sunucu adresini yazın": "Geben Sie die Serveradresse ein",
        "{0} adresinde LAB ERP sunucusu bulunamadı": "Kein LAB ERP-Server unter {0} gefunden",
        "Kurulum sürüyor": "Installation läuft",
        "Port bir sayı olmalı": "Der Port muss eine Zahl sein",
        "Veri klasörünü seçin": "Wählen Sie den Datenordner",
        "Port 1-65535 arasında olmalı": "Der Port muss zwischen 1 und 65535 liegen",
        "Yönetici şifresi en az 8 karakter olmalı": "Das Administratorpasswort muss mindestens 8 Zeichen lang sein",
        "Çalışma şeklini seçin": "Wählen Sie den Betriebsmodus",
        "Geçersiz istek": "Ungültige Anfrage",
        "İndirme başarısız ({0})": "Download fehlgeschlagen ({0})",
        "Sunucuya ulaşılamadı: {0}": "Server konnte nicht erreicht werden: {0}",
        "Dosya yazılamadı: {0}": "Datei konnte nicht geschrieben werden: {0}",
        "GÜVENLİK UYARISI: Sunucunun sertifikası değişmiş, bağlantı kesildi. Araya biri girmiş olabilir. "
        "Sertifikayı yönetici değiştirdiyse bu ekrandan sunucuyu yeniden kaydedin.":
            "SICHERHEITSWARNUNG: Das Serverzertifikat wurde geändert, Verbindung getrennt. Möglicherweise liegt ein Angriff vor. "
            "Falls der Administrator das Zertifikat geändert hat, speichern Sie den Server auf diesem Bildschirm erneut.",
        "{0} ile güvenli bağlantı kurulamadı: {1}": "Sichere Verbindung zu {0} konnte nicht hergestellt werden: {1}",
        "GÜVENLİK UYARISI: Sunucunun sertifikası değişmiş, bağlanılmadı. Araya biri girmiş olabilir. "
        "Sertifikayı yönetici değiştirdiyse bu ekrandan sunucuyu yeniden kaydedin.":
            "SICHERHEITSWARNUNG: Das Serverzertifikat wurde geändert, nicht verbunden. Möglicherweise liegt ein Angriff vor. "
            "Falls der Administrator das Zertifikat geändert hat, speichern Sie den Server auf diesem Bildschirm erneut.",
        "Güvenli bağlantı": "Sichere Verbindung",
        "{0} sunucusuna ilk kez güvenli bağlanılıyor.\n\nParmak izi:\n{1}\n\nSunucuda Yönetim > HTTPS ekranındaki parmak iziyle aynıysa onaylayın.":
            "Erstmalige sichere Verbindung zu {0}.\n\nFingerabdruck:\n{1}\n\nBestätigen Sie, wenn er mit dem Fingerabdruck unter Verwaltung > HTTPS auf dem Server übereinstimmt.",
        "Sunucunun parmak izi onaylanmadı, bağlanılmadı.": "Server-Fingerabdruck nicht bestätigt, Verbindung abgebrochen.",
        "{0} adresindeki sunucuya bağlanılamadı. Sunucu bilgisayarın açık, uygulamanın çalışır ve iki cihazın aynı ağda olduğunu kontrol edin.":
            "Verbindung zum Server unter {0} fehlgeschlagen. Stellen Sie sicher, dass der Servercomputer eingeschaltet ist, die Anwendung läuft und beide Geräte im selben Netzwerk sind.",
        "Ağda birden fazla sunucu var, birini seçin.": "Mehrere Server im Netzwerk gefunden, wählen Sie einen aus.",
        "Sunucu adresi": "Serveradresse",
        "{0} yanıt vermiyor. Ağda {1} adresinde bir sunucu bulundu.\n\nBu sizin sunucunuzsa ve adresi değiştiyse onaylayın.":
            "{0} antwortet nicht. Ein Server wurde unter {1} im Netzwerk gefunden.\n\nBestätigen Sie, wenn dies Ihr Server ist und sich seine Adresse geändert hat.",
        "{0} adresindeki sunucuya bağlanılamadı.": "Verbindung zum Server unter {0} fehlgeschlagen.",
        "{0} numaralı port başka bir program tarafından kullanılıyor. Ayarlardan başka bir port seçin.":
            "Port {0} wird von einem anderen Programm verwendet. Wählen Sie in den Einstellungen einen anderen Port.",
        "Sunucu başlatılamadı: {0}": "Server konnte nicht gestartet werden: {0}",
        "{0} sunucusu çalışıyor": "{0}-Server läuft",
        "{0} çalışıyor": "{0} läuft",
        "Adres: {0}": "Adresse: {0}",
        "ağ bağlantısı yok": "keine Netzwerkverbindung",
        "{0} penceresini aç": "{0}-Fenster öffnen",
        "Sunucuyu durdur ve çık": "Server beenden und schließen",
        "Çık": "Beenden",
        "Sunucu": "Server",
        "Uygulama": "Anwendung",
        "{0} arka planda çalışmaya devam ediyor, bildirimler gelir. Kapatmak için saatin yanındaki gizli simgelerden {1} simgesine sağ tıklayın.":
            "{0} läuft im Hintergrund weiter, Benachrichtigungen werden empfangen. Zum Beenden klicken Sie mit der rechten Maustaste auf das {1}-Symbol neben der Uhr.",
        "Sunucu durur ve ağdaki diğer kullanıcıların bağlantısı kesilir. Kapatılsın mı?":
            "Der Server wird angehalten und andere Netzwerkbenutzer werden getrennt. Schließen?",
        "Bildirim testi": "Benachrichtigungstest",
        "Güncelleme sunucusuna ulaşılamadı.\n{0}": "Update-Server konnte nicht erreicht werden.\n{0}",
        "{0} güncel (sürüm {1}).": "{0} ist aktuell (Version {1}).",
        "Yeni sürüm {0} hazır (kullandığınız sürüm {1}).": "Neue Version {0} ist verfügbar (installierte Version {1}).",
        "Güncelleme": "Update",
        "Şimdi indirip kurulsun mu?": "Jetzt herunterladen und installieren?",
        "İndirme sayfası açılsın mı?": "Download-Seite öffnen?",
        "Bu güncellemenin imzası henüz yayımlanmamış. Birazdan yeniden deneyin.":
            "Die Signatur für dieses Update wurde noch nicht veröffentlicht. Bitte versuchen Sie es später erneut.",
        "Güncelleme indirilemedi.\n{0}": "Update konnte nicht heruntergeladen werden.\n{0}",
        "Güncelleme dosyasının imzası doğrulanamadı, dosya silindi ve kurulmadı.":
            "Signatur der Update-Datei konnte nicht verifiziert werden; Datei wurde gelöscht und nicht installiert.",
        "Veri klasörü yalnızca sunucu modunda bu bilgisayardadır.":
            "Der Datenordner befindet sich nur im Server-Modus auf diesem Computer.",
        "Bilinmeyen işlem: {0}": "Unbekannte Aktion: {0}",
        "Uygulama kapanınca sunucu da durur ve ağdaki diğer kullanıcıların bağlantısı kesilir. Kapatılsın mı?":
            "Beim Schließen der Anwendung wird auch der Server beendet und andere Netzwerkbenutzer werden getrennt. Schließen?",
    },
}


def _detect_lang() -> str:
    try:
        if sys.platform == "win32":
            import ctypes
            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            loc = locale.windows_locale.get(lcid, "")
        else:
            loc = locale.getlocale()[0] or ""
        code = loc[:2].lower()
        if code in ("en", "es", "de"):
            return code
    except Exception:
        pass
    return "tr"


LANG = _detect_lang()


def st(text: str, *args: object) -> str:
    tmpl = TEXT.get(LANG, {}).get(text, text)
    if args:
        try:
            return tmpl.format(*args)
        except (IndexError, KeyError, ValueError):
            return tmpl
    return tmpl
