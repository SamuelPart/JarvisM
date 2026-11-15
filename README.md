# JARVIS — asistente Gemini para Windows y Linux

JARVIS separa la conversación y las herramientas Gemini (`brain.py`), las operaciones locales (`system_control.py`), la consola y voz (`main.py`) y las actualizaciones (`updater.py`). La API recibe las conversaciones y resultados de herramientas; el historial vive en memoria durante la ejecución y no se guarda entre reinicios.

## Requisitos

- Python 3.11+, Git y una clave de Google Gemini con acceso al modelo seleccionado.
- Windows o Linux con sesión gráfica para automatización de interfaz.
- En Debian/Ubuntu, para compilar PyAudio y disponer de voz, instale por ejemplo `sudo apt install build-essential python3-venv python3-dev portaudio19-dev espeak-ng`; pueden ser necesarias dependencias gráficas de PyAutoGUI. En Linux, volumen y brillo usan respectivamente `pactl` y `brightnessctl`. En Windows el brillo usa WMI si el hardware lo admite; el volumen no tiene implementación directa (puede usarse GUI bajo confirmación).
- Reconocimiento de voz mediante SpeechRecognition/Google requiere micrófono e Internet; el audio se envía a Google. La voz neuronal predeterminada usa Edge TTS y envía el texto hablado al servicio de Microsoft por Internet; requiere salida de audio. Si falla, se intenta `pyttsx3` local, que necesita un motor TTS instalado.

## Subir a GitHub

Cree un repositorio en GitHub, añada estos archivos, revise `git status`, cree un commit y configure su remoto y rama de seguimiento con Git. No incluya `.env`, `venv/` ni `.jarvis-state.json`; están ignorados. La actualización requiere una rama con upstream configurado y acceso al remoto.

## Instalación

Clone el repositorio confiable en su máquina. Desde la carpeta clonada:

**Linux**
```bash
chmod +x install.sh
./install.sh
venv/bin/python main.py
```

**Windows (CMD)**
```bat
install.bat
venv\Scripts\python.exe main.py
```

Los instaladores crean `venv`, instalan `requirements.txt` y solicitan la clave solo si no existe `.env`. También puede crear ese archivo manualmente:

```dotenv
GEMINI_API_KEY=su_clave
GEMINI_MODEL=gemini-2.5-flash
JARVIS_NAME=Señor
JARVIS_AUTO_UPDATE=0
JARVIS_VOICE_MODE=edge
JARVIS_TTS_VOICE=es-MX-JorgeNeural
```

Se puede usar `gemini-2.5-pro` si está disponible para su cuenta. La clave es local y debe protegerse como un secreto; no la distribuya en un ejecutable ni la suba al repositorio. No hay autenticación remota ni proxy incluidos.

## Uso y seguridad

Al iniciar se anuncia «Activando protocolos de seguridad...» y se pide una confirmación inicial, guardada en `.jarvis-state.json`. Borre este archivo para volver a solicitarla. Escriba un mensaje o `/voz` para hablar, `/actualizar` para actualizar y `/salir` para cerrar. Las respuestas se muestran por texto y se intenta reproducirlas por voz. El asistente solicita confirmación separada con `SI` para **cada** herramienta, incluidas lecturas, apertura de sitios y comandos destructivos. Las herramientas se ejecutan con los permisos del usuario; no lo ejecute como administrador. Revise cada comando y ruta: no hay sandbox ni lista negra capaz de hacer seguro un shell arbitrario. Los resultados de herramientas y archivos pueden contener información privada enviada a Gemini, y las instrucciones maliciosas en datos externos siguen siendo un riesgo. La función de búsqueda abre el navegador: no lee ni resume resultados web.

## Actualizaciones

`/actualizar` o «Jarvis, busca actualizaciones» pide confirmación y realiza `git fetch` del remoto de seguimiento. Se actualiza únicamente mediante fast-forward, sin borrar cambios locales ni resolver divergencias, y se bloquea si el árbol contiene cambios o archivos sin seguimiento. Si cambió `requirements.txt`, instala las dependencias con el Python activo. Tras una actualización correcta reinicia el programa. Si falla pip, el código ya actualizado permanece en disco: repare el entorno manualmente antes de iniciar de nuevo. `.env` y el estado local no se modifican por el actualizador.

Para comprobar automáticamente al iniciar, configure `JARVIS_AUTO_UPDATE=1`. Esto permite ejecutar código y dependencias nuevos del remoto sin confirmación adicional: úselo solo con repositorios, ramas y mantenedores de plena confianza. Proteja la rama y revise las dependencias; Git no verifica por sí solo que el código sea seguro. Se necesita red y autenticación Git ya configurada. El historial de conversación en memoria se pierde al reiniciar.

## Personalizar la voz

Por defecto, Edge TTS usa `es-MX-JorgeNeural`. En `.env`, cambie `JARVIS_TTS_VOICE` a otra voz disponible, por ejemplo `es-ES-AlvaroNeural` o `es-ES-ElviraNeural`. Para consultar el catálogo actual ejecute `venv/bin/edge-tts --list-voices` (en Windows `venv\Scripts\edge-tts.exe --list-voices`). La disponibilidad depende del servicio externo. Reinicie JARVIS para aplicar los cambios.

El texto pronunciado se envía a Microsoft: no use el modo neuronal con información que no desee compartir. Para no enviar texto a ese servicio, configure `JARVIS_VOICE_MODE=local`; para desactivar la voz, `JARVIS_VOICE_MODE=off`. Las respuestas se seguirán mostrando en consola. La reproducción es secuencial y se realiza en segundo plano; al salir del programa puede interrumpirse.

## Interfaz de escritorio

Después de instalar las dependencias, inicie `venv/bin/python gui.py` en Linux o `venv\Scripts\python.exe gui.py` en Windows. La ventana funciona por voz: pulse «Activar micrófono», diga «Jarvis» seguido de su orden o espere la respuesta «Le escucho» y diga su orden; diga exactamente «autorizo» para aprobar cada herramienta. Cualquier otra respuesta, silencio, error de reconocimiento o fallo de voz rechaza la acción. Pulse «Apagar micrófono» para detener la escucha; puede tardar mientras termina la captura o solicitud en curso. La clave y la voz se configuran en el mismo `.env` que usa la consola; el texto hablado puede enviarse a Microsoft si está activado Edge TTS. El audio capturado se envía a Google para transcribirlo. El actualizador sigue disponible en consola (`python main.py`); la conversación no persiste tras cerrarla. Se necesita una sesión gráfica. Para actualizar desde consola, salga de la interfaz primero.

### Animación del núcleo

El núcleo central es una esfera de puntos dibujada mediante Qt, inspirada en la referencia, sin GIF ni descarga externa. Sus puntos se animan mientras se reproduce una respuesta por voz y se detienen al terminar; son un efecto visual, no una medición de la amplitud real del audio. Si la voz está desactivada o falla, las ondas no se activan.

La confirmación por voz **no verifica la identidad**: otra persona, una grabación o el reconocimiento erróneo podrían decir «autorizo». No use este modo en entornos compartidos ni para acciones que no pueda supervisar. JARVIS lee los argumentos de la acción, pero los comandos y rutas pueden pronunciarse de forma ambigua; no apruebe si no los ha entendido. Para mayor seguridad use la consola y revise cada comando en pantalla. Al desactivar el micrófono se rechazan autorizaciones pendientes, pero no se interrumpe una acción ya iniciada. La primera autorización de instalación sigue siendo una confirmación gráfica.

La activación por «Jarvis» usa reconocimiento de voz de Google, no detección local: con el micrófono activado, cada frase capturada se envía a Google aunque no contenga la palabra. Requiere Internet y puede reconocerla incorrectamente. El botón apaga la escucha.

La interfaz tiene pestañas **Chat** y **Voz**. En Chat, escriba y pulse Enviar; las herramientas requieren autorización en un cuadro que muestra los argumentos completos. Puede desactivar la lectura en voz alta con la casilla. Para cambiar de pestaña, espere a que termine la solicitud o apague el micrófono. Las conversaciones solo permanecen en memoria durante la ejecución.

### Preparar un mensaje de WhatsApp

Pida a JARVIS que prepare el mensaje e indique el número con código de país. La herramienta pide autorización mostrando número y texto y abre un borrador mediante `wa.me` en el navegador. Requiere WhatsApp Web o la aplicación vinculada. **No envía el mensaje por sí sola**: revise destinatario y contenido y pulse Enviar. JARVIS no tiene acceso a sus contactos y no debe inventar números. La apertura del navegador tampoco confirma que el mensaje haya sido entregado.

Si aparece un error Gemini, la interfaz muestra su código HTTP y una explicación general sin exponer la clave ni el contenido de la respuesta. El código no demuestra por sí solo la causa exacta; compruebe modelo, acceso y cuota de la cuenta según el caso.

## Proveedor NVIDIA NIM

Puede seleccionar NVIDIA en vez de Gemini, tanto en chat como en voz. Cree una clave nueva en NVIDIA y añada en su `.env` local:

```dotenv
JARVIS_PROVIDER=nvidia
NVIDIA_API_KEY=su_clave_nueva
NVIDIA_MODEL=nvidia/nemotron-3.5-bolt-e4b
```

No comparta ni suba la clave. Si se expone, revóquela y cree otra. Reinicie JARVIS tras editar `.env`. El modelo y sus herramientas dependen de la disponibilidad y los permisos de su cuenta NVIDIA; el ejemplo no garantiza acceso ni cuota gratuita. Se envían conversación y resultados de herramientas a NVIDIA. Las herramientas requieren confirmación como con Gemini. Para regresar a Gemini, use `JARVIS_PROVIDER=gemini`. **No hay cambio automático entre proveedores**, ni historial compartido entre reinicios. WhatsApp abre un borrador; no lo envía automáticamente.
