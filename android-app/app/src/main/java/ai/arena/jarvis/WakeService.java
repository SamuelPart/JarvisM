package ai.arena.jarvis;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import java.util.ArrayList;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Explicit foreground microphone session. Never starts at boot or invisibly. */
public final class WakeService extends Service implements RecognitionListener {
    private static final String CHANNEL = "jarvis_listening";
    static final String STOP = "ai.arena.jarvis.STOP";
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private SpeechRecognizer recognizer;
    private TextToSpeech tts;
    private boolean active, waitingForOrder, ttsReady, speaking, processing;
    private int errors;
    private final Runnable restart = this::listen;

    @Override public void onCreate() {
        super.onCreate();
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(CHANNEL, "Escucha de JARVIS", NotificationManager.IMPORTANCE_LOW));
        tts = new TextToSpeech(this, status -> {
            ttsReady = status == TextToSpeech.SUCCESS;
            if (ttsReady) tts.setLanguage(new Locale("es"));
        });
        tts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
            @Override public void onStart(String id) { }
            @Override public void onDone(String id) { handler.post(() -> { speaking = false; schedule(700); }); }
            @Override public void onError(String id) { handler.post(() -> { speaking = false; schedule(1000); }); }
        });
    }
    private Notification notification(String text) {
        Intent stop = new Intent(this, WakeService.class).setAction(STOP);
        PendingIntent stopIntent = PendingIntent.getService(this, 1, stop, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        PendingIntent open = PendingIntent.getActivity(this, 2, new Intent(this, MainActivity.class), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this, CHANNEL).setSmallIcon(android.R.drawable.ic_btn_speak_now)
                .setContentTitle("JARVIS está escuchando")
                .setContentText(text).setContentIntent(open).setOngoing(true)
                .addAction(new Notification.Action.Builder(null, "Detener", stopIntent).build()).build();
    }
    @Override public int onStartCommand(Intent intent, int flags, int id) {
        if (intent != null && STOP.equals(intent.getAction())) { stopSelf(); return START_NOT_STICKY; }
        if (active) return START_NOT_STICKY;
        try { startForeground(104, notification("Di Jarvis y tu pedido. Puedes detener la escucha aquí.")); }
        catch (Exception ignored) { stopSelf(); return START_NOT_STICKY; }
        if (!SpeechRecognizer.isRecognitionAvailable(this)) { stopSelf(); return START_NOT_STICKY; }
        try {
            recognizer = SpeechRecognizer.createSpeechRecognizer(this);
            recognizer.setRecognitionListener(this);
            active = true;
            listen();
        } catch (Exception ignored) { stopSelf(); }
        return START_NOT_STICKY;
    }
    private void schedule(long delay) {
        handler.removeCallbacks(restart);
        if (active && !speaking && !processing) handler.postDelayed(restart, delay);
    }
    private void listen() {
        if (!active || speaking || processing || recognizer == null) return;
        Intent speech = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE, "es-ES")
                .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false);
        try { recognizer.startListening(speech); }
        catch (Exception ignored) { schedule(3000); }
    }
    private void say(String text) {
        if (!active) return;
        if (ttsReady && tts != null) {
            speaking = true;
            int result = tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "jarvis-reply");
            if (result == TextToSpeech.ERROR) { speaking = false; schedule(1000); }
        } else schedule(1000);
    }
    @Override public void onResults(Bundle results) {
        ArrayList<String> phrases = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
        String text = phrases == null || phrases.isEmpty() ? "" : phrases.get(0).trim();
        errors = 0;
        if (waitingForOrder) waitingForOrder = false;
        else {
            Matcher match = Pattern.compile("(?iu)\\bjarvis\\b[,:! ]*(.*)").matcher(text);
            if (!match.find()) { schedule(1000); return; }
            text = match.group(1).trim();
            if (text.isEmpty()) { waitingForOrder = true; say("Te escucho."); return; }
        }
        if (text.isEmpty()) { schedule(1000); return; }
        final String request = text;
        processing = true;
        executor.execute(() -> {
            String answer = new JarvisCore(getApplicationContext()).answer(request, false);
            handler.post(() -> { processing = false; if (active) say(answer); });
        });
    }
    @Override public void onError(int error) {
        if (!active) return;
        if (error == SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS || error == SpeechRecognizer.ERROR_CLIENT) {
            stopSelf(); return;
        }
        errors = Math.min(errors + 1, 5);
        schedule(Math.min(15000, 1200L * errors));
    }
    @Override public void onDestroy() {
        active = false;
        handler.removeCallbacksAndMessages(null);
        if (recognizer != null) { recognizer.cancel(); recognizer.destroy(); recognizer = null; }
        if (tts != null) { tts.stop(); tts.shutdown(); tts = null; }
        executor.shutdownNow();
        super.onDestroy();
    }
    @Override public IBinder onBind(Intent intent) { return null; }
    @Override public void onReadyForSpeech(Bundle p) { }
    @Override public void onBeginningOfSpeech() { }
    @Override public void onRmsChanged(float rms) { }
    @Override public void onBufferReceived(byte[] b) { }
    @Override public void onEndOfSpeech() { }
    @Override public void onPartialResults(Bundle b) { }
    @Override public void onEvent(int event, Bundle b) { }
}
