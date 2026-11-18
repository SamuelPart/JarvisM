package ai.arena.jarvis;

import android.content.Context;
import android.content.Intent;
import android.os.BatteryManager;
import android.provider.Settings;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.text.DateFormat;
import java.util.Date;
import java.util.Locale;

/** Small independent Android assistant. No desktop controller is invoked. */
final class JarvisCore {
    private static final String NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions";
    private static final String NVIDIA_MODEL = "nvidia/nemotron-3.5-bolt-e4b";
    private static final String GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent";
    private static final String INSTRUCTION =
        "Eres JARVIS. Responde siempre en español, breve y con naturalidad, aunque la pregunta venga en otro idioma. " +
        "Eres una versión Android sin herramientas adicionales. Nunca afirmes haber realizado acciones, accedido a cuentas, " +
        "teléfono, ubicación o datos actuales. No inventes información en tiempo real. Si requiere una acción no disponible, dilo claramente.";

    /** HTTP error with the status code, so the UI can show a useful message. */
    private static final class HttpError extends Exception {
        final int code;
        HttpError(int code) { super("HTTP " + code); this.code = code; }
    }

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

        String provider = Secrets.provider(context);
        String service = "nvidia".equals(provider) ? "NVIDIA" : "Gemini";
        String apiKey;
        try { apiKey = new Secrets(context).load(provider); }
        catch (Exception ignored) { return "No pude leer la clave guardada. Vuelve a configurarla en Ajustes de JARVIS."; }
        if (apiKey.isEmpty()) return "Configura tu clave de " + service + " en Ajustes de JARVIS para conversar. No la envíes por el chat.";
        try {
            return "nvidia".equals(provider) ? askNvidia(question, apiKey) : askGemini(question, apiKey);
        } catch (HttpError e) {
            if (e.code == 401 || e.code == 403) return service + " rechazó la clave o sus permisos. Revísala en Ajustes de JARVIS.";
            if (e.code == 429) return service + " alcanzó un límite de uso. Inténtalo más tarde.";
            return service + " respondió con un error (HTTP " + e.code + "). Revisa tu clave, cuota o conexión.";
        } catch (java.net.SocketTimeoutException ignored) { return service + " tardó demasiado en responder."; }
        catch (java.io.IOException ignored) { return "No pude conectar con " + service + ". Revisa Internet e inténtalo de nuevo."; }
        catch (Exception ignored) { return "No pude interpretar la respuesta de " + service + "."; }
    }

    private String post(String url, JSONObject payload, String headerName, String headerValue) throws Exception {
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(url).openConnection();
            connection.setRequestMethod("POST");
            connection.setConnectTimeout(12000);
            connection.setReadTimeout(60000);
            connection.setInstanceFollowRedirects(false);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty(headerName, headerValue);
            connection.setDoOutput(true);
            try (OutputStream output = connection.getOutputStream()) { output.write(payload.toString().getBytes(StandardCharsets.UTF_8)); }
            int code = connection.getResponseCode();
            if (code < 200 || code >= 300) throw new HttpError(code);
            ByteArrayOutputStream buffer = new ByteArrayOutputStream();
            try (InputStream stream = connection.getInputStream()) {
                byte[] block = new byte[4096]; int count;
                while ((count = stream.read(block)) != -1) {
                    if (buffer.size() + count > 1024 * 1024) throw new IllegalStateException("Respuesta demasiado grande");
                    buffer.write(block, 0, count);
                }
            }
            return buffer.toString("UTF-8");
        } finally { if (connection != null) connection.disconnect(); }
    }

    private String askNvidia(String question, String apiKey) throws Exception {
        JSONObject system = new JSONObject().put("role", "system").put("content", INSTRUCTION);
        JSONObject user = new JSONObject().put("role", "user").put("content", question);
        JSONObject payload = new JSONObject().put("model", NVIDIA_MODEL).put("messages", new JSONArray().put(system).put(user))
                .put("temperature", 1).put("top_p", 0.95).put("max_tokens", 1024).put("stream", false);
        String body = post(NVIDIA_URL, payload, "Authorization", "Bearer " + apiKey);
        String content = new JSONObject(body).getJSONArray("choices").getJSONObject(0)
                .getJSONObject("message").optString("content", "").trim();
        if (content.isEmpty()) throw new IllegalStateException("Respuesta vacía");
        return content;
    }

    private String askGemini(String question, String apiKey) throws Exception {
        JSONObject instruction = new JSONObject().put("parts", new JSONArray().put(new JSONObject().put("text", INSTRUCTION)));
        JSONObject payload = new JSONObject().put("systemInstruction", instruction).put("contents", new JSONArray().put(
            new JSONObject().put("role", "user").put("parts", new JSONArray().put(new JSONObject().put("text", question)))));
        String body = post(GEMINI_URL, payload, "x-goog-api-key", apiKey);
        JSONArray parts = new JSONObject(body).getJSONArray("candidates").getJSONObject(0).getJSONObject("content").getJSONArray("parts");
        StringBuilder text = new StringBuilder();
        for (int i = 0; i < parts.length(); i++) text.append(parts.getJSONObject(i).optString("text", ""));
        String content = text.toString().trim();
        if (content.isEmpty()) throw new IllegalStateException("Respuesta vacía");
        return content;
    }
}
