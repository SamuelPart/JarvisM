package ai.arena.jarvis;

import android.content.Context;
import android.content.Intent;
import android.os.BatteryManager;
import android.provider.Settings;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.text.DateFormat;
import java.util.Date;
import java.util.Locale;

/** Small independent Android assistant. No desktop controller is invoked. */
final class JarvisCore {
    private final Context context;
    JarvisCore(Context context) { this.context = context.getApplicationContext(); }
    String answer(String input, boolean canOpenUi) {
        String question = input.trim();
        String q = question.toLowerCase(new Locale("es"));
        if (question.isEmpty()) return "Dime en qué te ayudo.";
        if (question.length() > 4000) return "El mensaje es demasiado largo.";
        if (q.matches(".*\\b(batería|bateria)\\b.*") && !q.matches(".*\\b(activa|desactiva|ahorro|configura)\\b.*")) {
            BatteryManager battery = (BatteryManager) context.getSystemService(Context.BATTERY_SERVICE);
            int value = battery == null ? -1 : battery.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY);
            return value >= 0 && value <= 100 ? "La batería está al " + value + " por ciento." : "No pude consultar la batería.";
        }
        if (q.matches(".*\\b(qué hora|que hora|dime la hora|hora actual|qué horas|que horas)\\b.*"))
            return "Son las " + DateFormat.getTimeInstance(DateFormat.SHORT, new Locale("es")).format(new Date()) + ".";
        if (q.matches(".*\\b(abre|abrir)\\b.*\\b(ajustes|configuración|configuracion)\\b.*")) {
            if (!canOpenUi) return "Para abrir Ajustes, abre JARVIS en la pantalla del teléfono y pídemelo de nuevo.";
            try {
                Intent intent = new Intent(Settings.ACTION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                context.startActivity(intent);
                return "Solicité abrir Ajustes.";
            } catch (Exception ignored) { return "No pude abrir Ajustes en este teléfono."; }
        }
        if (q.matches(".*\\b(abre|abrir)\\b.*")) {
            String packageName = q.contains("whatsapp") ? "com.whatsapp" : q.contains("youtube") ? "com.google.android.youtube" :
                    q.contains("chrome") ? "com.android.chrome" : null;
            if (packageName != null) {
                if (!canOpenUi) return "Abre JARVIS en el teléfono y vuelve a pedirme que abra la aplicación.";
                try {
                    Intent launch = context.getPackageManager().getLaunchIntentForPackage(packageName);
                    if (launch == null) return "No encontré esa aplicación instalada.";
                    context.startActivity(launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                    return "Solicité abrir la aplicación.";
                } catch (Exception ignored) { return "No pude abrir esa aplicación."; }
            }
        }
        // Do not let the model claim it performed actions it cannot execute.
        if (q.matches(".*\\b(abre|abrir|envía|envia|enviar|manda|mandar|borra|elimina|crea|instala|llama|programa|reproduce|pon|pausa|activa|desactiva|recuérdame|recuerdame|recordatorio|clima|correo|gmail|whatsapp|archivo)\\b.*"))
            return "Esa acción todavía no está disponible en esta versión de Android. Puedo conversar, consultar la hora o la batería y abrir algunas aplicaciones con JARVIS abierto.";
        String apiKey;
        try { apiKey = new Secrets(context).load(); }
        catch (Exception ignored) { return "No pude leer la clave guardada. Vuelve a configurarla en JARVIS."; }
        if (apiKey.isEmpty()) return "Configura tu clave Gemini en Ajustes de JARVIS para conversar. No la envíes por el chat.";
        HttpURLConnection connection = null;
        try {
            URL url = new URL("https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent");
            connection = (HttpURLConnection) url.openConnection();
            connection.setRequestMethod("POST");
            connection.setConnectTimeout(12000);
            connection.setReadTimeout(40000);
            connection.setInstanceFollowRedirects(false);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            connection.setRequestProperty("x-goog-api-key", apiKey);
            connection.setDoOutput(true);
            JSONObject instruction = new JSONObject().put("parts", new JSONArray().put(new JSONObject().put("text",
                "Eres JARVIS. Responde en español, breve y con naturalidad. Eres una versión Android sin herramientas adicionales. " +
                "Nunca afirmes haber realizado acciones, accedido a cuentas, teléfono, ubicación o datos actuales. " +
                "No inventes información en tiempo real. Si requiere una acción no disponible, dilo claramente.")));
            JSONObject payload = new JSONObject().put("systemInstruction", instruction).put("contents", new JSONArray().put(
                new JSONObject().put("role", "user").put("parts", new JSONArray().put(new JSONObject().put("text", question)))));
            try (java.io.OutputStream output = connection.getOutputStream()) { output.write(payload.toString().getBytes(StandardCharsets.UTF_8)); }
            int code = connection.getResponseCode();
            if (code == 401 || code == 403) return "Gemini rechazó la clave o sus permisos. Revísala en Ajustes de JARVIS.";
            if (code == 429) return "Gemini alcanzó un límite de uso. Inténtalo más tarde.";
            if (code < 200 || code >= 300) return "Gemini respondió con un error HTTP " + code + ".";
            ByteArrayOutputStream buffer = new ByteArrayOutputStream();
            try (InputStream stream = connection.getInputStream()) {
                byte[] block = new byte[4096]; int count;
                while ((count = stream.read(block)) != -1) {
                    if (buffer.size() + count > 1024 * 1024) return "Gemini devolvió una respuesta demasiado grande.";
                    buffer.write(block, 0, count);
                }
            }
            JSONObject result = new JSONObject(buffer.toString("UTF-8"));
            JSONArray parts = result.getJSONArray("candidates").getJSONObject(0).getJSONObject("content").getJSONArray("parts");
            StringBuilder answer = new StringBuilder();
            for (int i = 0; i < parts.length(); i++) answer.append(parts.getJSONObject(i).optString("text", ""));
            return answer.toString().trim().isEmpty() ? "Gemini no devolvió una respuesta de texto." : answer.toString().trim();
        } catch (java.net.SocketTimeoutException ignored) { return "Gemini tardó demasiado en responder."; }
        catch (java.io.IOException ignored) { return "No pude conectar con Gemini. Revisa Internet e inténtalo de nuevo."; }
        catch (Exception ignored) { return "No pude interpretar la respuesta de Gemini."; }
        finally { if (connection != null) connection.disconnect(); }
    }
}
