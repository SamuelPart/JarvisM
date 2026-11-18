package ai.arena.jarvis;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Encrypted preferences with non-exportable keys in Android Keystore. */
final class Secrets {
    private final Context context;
    Secrets(Context context) { this.context = context.getApplicationContext(); }
    private SecretKey key(String slot) throws Exception {
        String alias = "jarvis.android.key." + slot;
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (!store.containsAlias(alias)) {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
            generator.generateKey();
        }
        return (SecretKey) store.getKey(alias, null);
    }
    void save(String slot, String value) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key(slot));
        String iv = Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP);
        String data = Base64.encodeToString(cipher.doFinal(value.getBytes(StandardCharsets.UTF_8)), Base64.NO_WRAP);
        if (!context.getSharedPreferences("secrets", Context.MODE_PRIVATE).edit()
                .putString(slot + ".iv", iv).putString(slot + ".key", data).commit())
            throw new IllegalStateException("No se pudo guardar la configuración.");
    }
    String load(String slot) throws Exception {
        SharedPreferences prefs = context.getSharedPreferences("secrets", Context.MODE_PRIVATE);
        String iv = prefs.getString(slot + ".iv", null), data = prefs.getString(slot + ".key", null);
        if (iv == null || data == null) return "";
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(slot), new GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)));
        return new String(cipher.doFinal(Base64.decode(data, Base64.NO_WRAP)), StandardCharsets.UTF_8);
    }
    void clear(String slot) { context.getSharedPreferences("secrets", Context.MODE_PRIVATE).edit().remove(slot + ".iv").remove(slot + ".key").apply(); }
    static String provider(Context context) {
        return context.getSharedPreferences("settings", Context.MODE_PRIVATE).getString("provider", "nvidia");
    }
    static void provider(Context context, String value) {
        context.getSharedPreferences("settings", Context.MODE_PRIVATE).edit().putString("provider", value).apply();
    }
}
