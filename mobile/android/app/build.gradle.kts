import java.util.Properties

plugins {
    id("com.android.application")
}

// One version for the whole product: app_version in backend/app/config.py (CI checks the tag against it).
val appVersion: String = (findProperty("appVersion") as String?) ?: run {
    val cfg = rootDir.resolve("../../backend/app/config.py").readText()
    Regex("app_version: str = \"([^\"]+)\"").find(cfg)!!.groupValues[1]
}
val parts = appVersion.split(".").map { it.toInt() }

// Release signing: keystore.properties next to this file (local) or ERP_KEYSTORE_* env vars (CI).
// Without either the release build stops: the debug key is public, anyone could sign an update with it.
val ks = Properties().apply {
    val f = rootDir.resolve("keystore.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}
fun signing(key: String, env: String): String? = ks.getProperty(key) ?: System.getenv(env)

android {
    namespace = "com.erdevirlabs.parcatakip"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.erdevirlabs.parcatakip"
        minSdk = 26
        targetSdk = 36
        versionCode = parts[0] * 10000 + parts[1] * 100 + parts[2]
        versionName = appVersion
    }

    val storeFile = signing("storeFile", "ERP_KEYSTORE_FILE")
    signingConfigs {
        if (storeFile != null) {
            create("release") {
                this.storeFile = rootDir.resolve(storeFile)
                storePassword = signing("storePassword", "ERP_KEYSTORE_PASSWORD")
                keyAlias = signing("keyAlias", "ERP_KEY_ALIAS")
                keyPassword = signing("keyPassword", "ERP_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            if (storeFile != null) signingConfig = signingConfigs.getByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        buildConfig = true
    }

    // One APK per ABI plus a universal one; the in-app update check picks the one matching the phone.
    splits {
        abi {
            isEnable = true
            reset()
            include("arm64-v8a", "armeabi-v7a", "x86_64", "x86")
            isUniversalApk = true
        }
    }
}

dependencies {
    implementation("androidx.core:core:1.13.1")
}

// An unsigned release APK would install nowhere; say why instead of producing one
tasks.matching { it.name == "assembleRelease" || it.name == "bundleRelease" }.configureEach {
    doFirst {
        if (signing("storeFile", "ERP_KEYSTORE_FILE") == null) {
            throw GradleException("Release signing key missing: add keystore.properties or ERP_KEYSTORE_* variables")
        }
    }
}
