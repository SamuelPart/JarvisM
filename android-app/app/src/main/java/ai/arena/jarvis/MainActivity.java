package ai.arena.jarvis;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.ScrollView;
import android.widget.TextView;
import java.util.ArrayList;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity implements RecognitionListener {
    private TextView history, status;
    private ScrollView chatScroll;
    private EditText input;
    private SpeechRecognizer recognizer;
    private TextToSpeech voice;
    private boolean voiceReady, busy, destroyed;
    private String pendingPermission;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private Orb orb;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(Color.rgb(7, 14, 27));
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL); root.setPadding(20, 20, 20, 20); root.setBackgroundColor(Color.rgb(7, 14, 27));
        TextView title = text("J  /  JARVIS", 20, 0xff8ae4ff);
        root.addView(title);
        orb = new Orb(); root.addView(orb, new LinearLayout.LayoutParams(-1, 160));
        status = text("Listo · funciona sin la laptop", 13, 0xffa6cddd); status.setGravity(Gravity.CENTER); root.addView(status);
        chatScroll = new ScrollView(this);
        history = text("JARVIS: Hola, señor. Puedo conversar, consultar la hora y la batería, y abrir algunas aplicaciones.\n", 15, Color.WHITE);
        history.setTextIsSelectable(true);
        chatScroll.addView(history); root.addView(chatScroll, new LinearLayout.LayoutParams(-1, 0, 1));
        input = new EditText(this); input.setSingleLine(false); input.setMaxLines(3); input.setHint("Escribe tu mensaje"); input.setTextColor(Color.WHITE); input.setHintTextColor(0xff8ca3b7); root.addView(input);
        LinearLayout row = new LinearLayout(this);
        Button send = button("Enviar"); send.setOnClickListener(v -> { if (busy) return; String text = input.getText().toString().trim(); input.setText(""); submit(text); });
        Button talk = button("Hablar"); talk.setOnClickListener(v -> requestAudio("talk"));
        Button settings = button("Ajustes"); settings.setOnClickListener(v -> showSettings());
        row.addView(send, new LinearLayout.LayoutParams(0, -2, 1)); row.addView(talk, new LinearLayout.LayoutParams(0, -2, 1)); row.addView(settings, new LinearLayout.LayoutParams(0, -2, 1)); root.addView(row);
        LinearLayout wakeRow = new LinearLayout(this);
        Button wake = button("Activar escucha de Jarvis"); wake.setOnClickListener(v -> discloseWake());
        Button stop = button("Detener escucha"); stop.setOnClickListener(v -> { stopService(new Intent(this, WakeService.class)); status.setText("Escucha en segundo plano detenida"); });
        wakeRow.addView(wake, new LinearLayout.LayoutParams(0, -2, 1)); wakeRow.addView(stop, new LinearLayout.LayoutParams(0, -2, 1)); root.addView(wakeRow);
        setContentView(root);
        voice = new TextToSpeech(this, result -> { voiceReady = result == TextToSpeech.SUCCESS; if (voiceReady) voice.setLanguage(new Locale("es")); });
    }
    private TextView text(String value, int size, int color) { TextView view = new TextView(this); view.setText(value); view.setTextSize(size); view.setTextColor(color); return view; }
    private Button button(String title) { Button button = new Button(this); button.setText(title); button.setAllCaps(false); return button; }
    private void showSettings() {
        LinearLayout form = new LinearLayout(this); form.setOrientation(LinearLayout.VERTICAL); form.setPadding(30, 10, 30, 0);
        TextView notice = text("La clave se guarda cifrada en Android Keystore. Tus preguntas se envían únicamente al proveedor que elijas; el reconocimiento de voz puede enviarse al proveedor de Android. La clave nunca se imprime ni se incluye en el APK. No la compartas en el chat.", 14, Color.DKGRAY);
        notice.setTextColor(Color.DKGRAY); form.addView(notice);
        RadioGroup provider = new RadioGroup(this);
        RadioButton nvidia = new RadioButton(this); nvidia.setId(1); nvidia.setText("NVIDIA (predeterminado)");
        RadioButton gemini = new RadioButton(this); gemini.setId(2); gemini.setText("Gemini");
        provider.addView(nvidia); provider.addView(gemini);
        boolean useNvidia = Secrets.provider(this).equals("nvidia");
        provider.check(useNvidia ? 1 : 2); form.addView(provider);
        EditText key = new EditText(this); key.setSingleLine(true);
        key.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        key.setHint(useNvidia ? "Clave de NVIDIA (build.nvidia.com)" : "Clave de Gemini (Google AI Studio)");
        provider.setOnCheckedChangeListener((group, checkedId) -> key.setHint(checkedId == 1 ? "Clave de NVIDIA (build.nvidia.com)" : "Clave de Gemini (Google AI Studio)"));
        form.addView(key);
        new AlertDialog.Builder(this).setTitle("Configurar JARVIS").setView(form)
          .setPositiveButton("Guardar", (dialog, which) -> {
              String slot = provider.getCheckedRadioButtonId() == 2 ? "gemini" : "nvidia";
              Secrets.provider(this, slot);
              String value = key.getText().toString().trim(); key.setText("");
              if (value.isEmpty()) { status.setText("Proveedor cambiado; no se cambió la clave"); return; }
              try { new Secrets(this).save(slot, value); status.setText("Clave de " + slot.toUpperCase() + " guardada de forma cifrada"); }
              catch (Exception ignored) { status.setText("No se pudo guardar la clave de forma segura"); }
          }).setNeutralButton("Borrar clave", (dialog, which) -> {
              String slot = provider.getCheckedRadioButtonId() == 2 ? "gemini" : "nvidia"; key.setText("");
              new Secrets(this).clear(slot); status.setText("Clave de " + slot.toUpperCase() + " eliminada");
          })
          .setNegativeButton("Cancelar", (dialog, which) -> key.setText("")) .show();
    }
    private void discloseWake() {
        new AlertDialog.Builder(this).setTitle("Escucha en segundo plano")
          .setMessage("Al activar esta opción, JARVIS mantendrá el micrófono activo con una notificación visible. El reconocimiento de voz del teléfono puede enviar audio a su proveedor. Android puede detenerlo o limitarlo por batería. Puedes apagarlo desde la notificación. ¿Continuar?")
          .setPositiveButton("Activar", (d, w) -> requestAudio("wake")) .setNegativeButton("Cancelar", null).show();
    }
    private void appendChat(String value) {
        history.append(value);
        chatScroll.post(() -> chatScroll.fullScroll(View.FOCUS_DOWN));
    }

    private void requestAudio(String action) {
        if (busy) { status.setText("Espera a que termine la respuesta…"); return; }
        pendingPermission = action;
        ArrayList<String> missing = new ArrayList<>();
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) missing.add(Manifest.permission.RECORD_AUDIO);
        if ("wake".equals(action) && Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) missing.add(Manifest.permission.POST_NOTIFICATIONS);
        if (!missing.isEmpty()) { requestPermissions(missing.toArray(new String[0]), 12); return; }
        startAction(action);
    }
    @Override public void onRequestPermissionsResult(int request, String[] permissions, int[] grants) {
        super.onRequestPermissionsResult(request, permissions, grants);
        if (request != 12) return;
        for (int grant : grants) if (grant != PackageManager.PERMISSION_GRANTED) { status.setText("Se necesita autorización de micrófono y notificación"); pendingPermission = null; return; }
        String action = pendingPermission; pendingPermission = null; if (action != null) startAction(action);
    }
    private void startAction(String action) {
        if (!SpeechRecognizer.isRecognitionAvailable(this)) { status.setText("No hay reconocimiento de voz disponible en este teléfono"); return; }
        if ("wake".equals(action)) {
            stopListening(); if (voice != null) voice.stop();
            try { startForegroundService(new Intent(this, WakeService.class)); status.setText("Activando escucha · revisa la notificación"); }
            catch (Exception ignored) { status.setText("Android no permitió activar la escucha en segundo plano"); }
        } else {
            stopService(new Intent(this, WakeService.class));
            if (voice != null) voice.stop();
            stopListening();
            try {
                recognizer = SpeechRecognizer.createSpeechRecognizer(this); recognizer.setRecognitionListener(this);
                Intent request = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM).putExtra(RecognizerIntent.EXTRA_LANGUAGE, "es-ES");
                recognizer.startListening(request); status.setText("Escuchando…");
            } catch (Exception ignored) { stopListening(); status.setText("No se pudo iniciar el micrófono"); }
        }
    }
    private void submit(String text) {
        if (text.isEmpty() || busy) return;
        stopService(new Intent(this, WakeService.class));
        if (voice != null) voice.stop();
        appendChat("\nTÚ: " + text + "\n"); input.setEnabled(false); busy = true; status.setText("Pensando…"); orb.setThinking(true);
        executor.execute(() -> {
            String answer = new JarvisCore(getApplicationContext()).answer(text, true);
            handler.post(() -> {
                if (destroyed) return;
                busy = false; input.setEnabled(true); orb.setThinking(false); status.setText("Listo"); appendChat("\nJARVIS: " + answer + "\n");
                if (voiceReady && voice != null) voice.speak(answer, TextToSpeech.QUEUE_FLUSH, null, "chat");
            });
        });
    }
    private void stopListening() { if (recognizer != null) { recognizer.cancel(); recognizer.destroy(); recognizer = null; } }
    @Override public void onResults(Bundle results) { ArrayList<String> phrases = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION); stopListening(); if (phrases != null && !phrases.isEmpty()) submit(phrases.get(0)); else status.setText("No entendí. Inténtalo de nuevo."); }
    @Override public void onError(int error) { stopListening(); status.setText("No pude reconocer la voz. Comprueba el micrófono o inténtalo de nuevo."); }
    @Override public void onReadyForSpeech(Bundle b) { }
    @Override public void onBeginningOfSpeech() { }
    @Override public void onRmsChanged(float rms) { }
    @Override public void onBufferReceived(byte[] b) { }
    @Override public void onEndOfSpeech() { }
    @Override public void onPartialResults(Bundle b) { }
    @Override public void onEvent(int e, Bundle b) { }
    @Override protected void onDestroy() { destroyed = true; stopListening(); if (voice != null) { voice.stop(); voice.shutdown(); } executor.shutdownNow(); handler.removeCallbacksAndMessages(null); super.onDestroy(); }

    private final class Orb extends View {
        private final Paint paint = new Paint(3); private float phase; private boolean thinking;
        Orb() { super(MainActivity.this); }
        void setThinking(boolean value) { thinking = value; }
        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas); float cx = getWidth()/2f, cy = getHeight()/2f, radius = Math.min(getWidth(), getHeight()) * .36f;
            for (int lat = 1; lat < 22; lat++) {
                double theta = Math.PI * lat / 22; int count = Math.max(10, (int)(40 * Math.sin(theta)));
                for (int lon = 0; lon < count; lon++) {
                    double angle = Math.PI * 2 * lon / count + phase;
                    float x = (float)(Math.sin(theta) * Math.cos(angle)), y = (float)Math.cos(theta), z = (float)(Math.sin(theta) * Math.sin(angle));
                    float pulse = thinking ? (float)(1 + .08 * Math.sin(phase * 4 + angle * 2 + theta * 5)) : 1;
                    paint.setColor(Color.argb((int)(80 + 100 * (z + 1)/2), 75, 150, 255));
                    canvas.drawCircle(cx + x * radius * pulse, cy + y * radius * pulse, 1.5f, paint);
                }
            }
            phase += thinking ? .07f : .025f; postInvalidateDelayed(40);
        }
    }
}
