plugins {
    id("com.android.application") version "8.5.0" apply false
    id("org.jetbrains.kotlin.android") version "1.9.24" apply false
    // FCM push notifications — requires a real google-services.json from the
    // Firebase console to actually deliver anything; see app/google-services.json.
    id("com.google.gms.google-services") version "4.4.2" apply false
}
