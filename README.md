# JARVIS — asistente Gemini para Windows y Linux

JARVIS separa la conversación y las herramientas Gemini (`brain.py`), las operaciones locales (`system_control.py`), la consola y voz (`main.py`) y las actualizaciones (`updater.py`). La API recibe las conversaciones y resultados de herramientas; las conversaciones completadas se guardan localmente entre reinicios.

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

Al iniciar se anuncia «Activando protocolos de seguridad...» y se pide una confirmación inicial, guardada en `.jarvis-state.json`. Borre este archivo para volver a solicitarla. Escriba un mensaje o `/voz` para hablar, `/actualizar` para actualizar y `/salir` para cerrar. Las respuestas se muestran por texto y se intenta reproducirlas por voz. Al iniciar se puede autorizar de una vez únicamente las búsquedas y la música; las demás herramientas, incluidas lecturas, apertura de sitios y comandos, siguen requiriendo confirmación separada. Las herramientas se ejecutan con los permisos del usuario; no lo ejecute como administrador. Revise cada comando y ruta: no hay sandbox ni lista negra capaz de hacer seguro un shell arbitrario. Los resultados de herramientas y archivos pueden contener información privada enviada a Gemini, y las instrucciones maliciosas en datos externos siguen siendo un riesgo. La búsqueda web devuelve fragmentos no confiables para que el modelo los resuma; no descarga páginas completas.

## Actualizaciones

`/actualizar` o «Jarvis, busca actualizaciones» pide confirmación y realiza `git fetch` del remoto de seguimiento. Se actualiza únicamente mediante fast-forward, sin borrar cambios locales ni resolver divergencias, y se bloquea si el árbol contiene cambios o archivos sin seguimiento. Si cambió `requirements.txt`, instala las dependencias con el Python activo. Tras una actualización correcta reinicia el programa. Si falla pip, el código ya actualizado permanece en disco: repare el entorno manualmente antes de iniciar de nuevo. `.env` y el estado local no se modifican por el actualizador.

Para comprobar automáticamente al iniciar, configure `JARVIS_AUTO_UPDATE=1`. Esto permite ejecutar código y dependencias nuevos del remoto sin confirmación adicional: úselo solo con repositorios, ramas y mantenedores de plena confianza. Proteja la rama y revise las dependencias; Git no verifica por sí solo que el código sea seguro. Se necesita red y autenticación Git ya configurada. Las conversaciones completadas permanecen en SQLite tras reiniciar.

## Personalizar la voz

Por defecto, Edge TTS usa `es-MX-JorgeNeural`. En `.env`, cambie `JARVIS_TTS_VOICE` a otra voz disponible, por ejemplo `es-ES-AlvaroNeural` o `es-ES-ElviraNeural`. Para consultar el catálogo actual ejecute `venv/bin/edge-tts --list-voices` (en Windows `venv\Scripts\edge-tts.exe --list-voices`). La disponibilidad depende del servicio externo. Reinicie JARVIS para aplicar los cambios.

El texto pronunciado se envía a Microsoft: no use el modo neuronal con información que no desee compartir. Para no enviar texto a ese servicio, configure `JARVIS_VOICE_MODE=local`; para desactivar la voz, `JARVIS_VOICE_MODE=off`. Las respuestas se seguirán mostrando en consola. La reproducción es secuencial y se realiza en segundo plano; al salir del programa puede interrumpirse.

## Interfaz de escritorio

Después de instalar las dependencias, inicie `venv/bin/python gui.py` en Linux o `venv\Scripts\python.exe gui.py` en Windows. La ventana funciona por voz: pulse el icono de micrófono, diga «Jarvis» seguido de su orden o espere la respuesta «Le escucho» y diga su orden; diga exactamente «autorizo» para aprobar las herramientas que no tengan permiso permanente. Cualquier otra respuesta, silencio, error de reconocimiento o fallo de voz rechaza la acción. Pulse de nuevo el icono de micrófono para detener la escucha; puede tardar mientras termina la captura o solicitud en curso. La clave y la voz se configuran en el mismo `.env` que usa la consola; el texto hablado puede enviarse a Microsoft si está activado Edge TTS. El audio capturado se envía a Google para transcribirlo. El actualizador sigue disponible en consola (`python main.py`); las conversaciones completadas se conservan localmente. Se necesita una sesión gráfica. Para actualizar desde consola, salga de la interfaz primero.

### Animación del núcleo

El núcleo central es una esfera de puntos dibujada mediante Qt, inspirada en la referencia, sin GIF ni descarga externa. Sus puntos se animan mientras se reproduce una respuesta por voz y se detienen al terminar; son un efecto visual, no una medición de la amplitud real del audio. Si la voz está desactivada o falla, las ondas no se activan.

La confirmación por voz **no verifica la identidad**: otra persona, una grabación o el reconocimiento erróneo podrían decir «autorizo». No use este modo en entornos compartidos ni para acciones que no pueda supervisar. JARVIS lee los argumentos de la acción, pero los comandos y rutas pueden pronunciarse de forma ambigua; no apruebe si no los ha entendido. Para mayor seguridad use la consola y revise cada comando en pantalla. Al desactivar el micrófono se rechazan autorizaciones pendientes, pero no se interrumpe una acción ya iniciada. La primera autorización de instalación sigue siendo una confirmación gráfica.

La activación por «Jarvis» usa reconocimiento de voz de Google, no detección local: con el micrófono activado, cada frase capturada se envía a Google aunque no contenga la palabra. Requiere Internet y puede reconocerla incorrectamente. El botón apaga la escucha.

El chat comienza oculto: pulse 💬 para mostrarlo u ocultarlo. Pulse 🎙 para activar o detener el micrófono. En Chat, escriba y pulse Enviar; las herramientas sin permiso permanente requieren autorización en el chat, que muestra los argumentos completos; responda AUTORIZO o NO. Puede desactivar la lectura en voz alta con la casilla. El envío de mensajes se desactiva durante la sesión de voz y el micrófono se desactiva durante una solicitud escrita. Las conversaciones completadas se guardan en memoria local.

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

No comparta ni suba la clave. Si se expone, revóquela y cree otra. Reinicie JARVIS tras editar `.env`. El modelo y sus herramientas dependen de la disponibilidad y los permisos de su cuenta NVIDIA; el ejemplo no garantiza acceso ni cuota gratuita. Se envían conversación y resultados de herramientas a NVIDIA. Los permisos de herramientas son los mismos que con Gemini. Para regresar a Gemini, use `JARVIS_PROVIDER=gemini`. **No hay cambio automático entre proveedores**, y la memoria local de conversaciones es compartida entre proveedores. WhatsApp abre un borrador; no lo envía automáticamente.

### Núcleo expresivo

La esfera indica el estado: azul quieto en espera; gira al procesar una solicitud; pulsa durante la reproducción de voz; y pasa a ámbar cuando espera autorización. Si una solicitud está pendiente, el color ámbar tiene prioridad sobre la voz. La animación de voz es decorativa, no sigue el volumen real.

### Modo compacto flotante

Pulse «Modo compacto» para mantener una ventana pequeña sobre las demás con el núcleo, el estado y los iconos de chat y micrófono. Pulse «Abrir chat» para volver a la ventana completa sin perder la conversación de la sesión. El ajuste «Siempre visible» se conserva para el modo completo; la ventana compacta solicita estar siempre visible, sujeto al gestor de ventanas. Si hay una solicitud de chat en curso, el botón de micrófono queda desactivado hasta que termine. Las acciones críticas siguen requiriendo confirmación.

### Ajustes visuales

En la ventana completa pulse «Ajustes» para elegir el color de la esfera, su tamaño y animación normal, reducida o desactivada. Pulse Guardar para conservar los cambios entre reinicios; Cancelar no los aplica. El color ámbar de autorización se mantiene independientemente de la paleta. Las preferencias locales se guardan en `.jarvis-ui.json` (ignorado por Git); no contienen claves. En modo compacto, abra el chat para acceder a Ajustes.

### Memoria entre sesiones

JARVIS guarda localmente los pares de mensajes y respuestas completadas en `.jarvis-memory.sqlite3`, ignorado por Git. En la ventana completa, pulse **Memoria** para escribir preferencias explícitas (por ejemplo, «prefiero respuestas breves») y guardarlas; no se extraen preferencias automáticamente. El botón de borrado elimina conversaciones y preferencias locales y limpia el contexto de la sesión. No borra ajustes visuales, `.env`, copias de seguridad ni información que ya hayan recibido servicios externos.

Al iniciar, el chat muestra hasta 20 mensajes recientes. Antes de cada nueva petición se envían al proveedor seleccionado los últimos 20 mensajes y las preferencias, además del nuevo mensaje; la base no está cifrada. Evite introducir claves o datos que no desee almacenar o transmitir; proteja su equipo y sus copias de seguridad. SQLite usa `secure_delete`, pero no se garantiza borrado forense en discos, copias o servicios externos. Las llamadas/resultados internos de herramientas y tareas incompletas no se guardan como tal, por lo que una tarea interrumpida no se reanuda exactamente. Las peticiones fallidas no se guardan como turno completado.

### Agenda y recordatorios

En la ventana completa pulse **Agenda**, escriba una descripción y seleccione la fecha y hora local; también puede seleccionar y eliminar avisos de la lista. Los avisos se guardan en `.jarvis-agenda.sqlite3`, ignorado por Git. Puede pedir a JARVIS que cree uno: consultará la hora y pedirá autorización antes de guardarlo. Verifique la fecha, hora y zona horaria en la solicitud.

La ventana de JARVIS debe estar abierta para recibir los avisos a tiempo. Se comprueban aproximadamente cada 5 segundos y, si el programa estaba cerrado, los vencidos aparecen al volver a abrirlo; no es un servicio de sistema ni suena con el equipo apagado. Los avisos ya reclamados no se repiten; una interrupción inesperada justo al mostrarlos puede hacer que se pierdan, por lo que no es adecuado para alertas críticas. Hay aviso visual y se intenta reproducir la voz, excepto mientras la sesión del micrófono está activa: en ese caso se muestra solo visualmente para evitar que JARVIS escuche su propio aviso. El texto hablado se envía a Microsoft si Edge TTS está activo. La agenda no está cifrada y no se borra al borrar la memoria de conversación; elimine los recordatorios desde Agenda. La hora depende del reloj y la zona horaria del equipo.

### Búsqueda web con fuentes

Al pedir información actual, JARVIS usa `web_search`, con permiso individual o con la autorización previa de búsquedas. Se envía la consulta mediante `ddgs` a DuckDuckGo; si falla o no tiene resultados se prueban Brave y Yahoo y se devuelven hasta seis títulos, enlaces y fragmentos; el proveedor de IA recibe esos datos para resumirlos y citar los enlaces. No se descargan ni verifican las páginas completas: los fragmentos pueden estar desactualizados o ser erróneos y las respuestas del modelo pueden equivocarse o citar mal. Abre las fuentes para comprobar información importante. Si los buscadores están bloqueados, no hay conexión o no hay resultados, JARVIS debe informarlo en lugar de inventar una respuesta. El texto web es contenido no confiable y puede contener instrucciones maliciosas; Los comandos, archivos y otras acciones críticas siguen requiriendo autorización explícita.

### Música automática y enlaces

Para reproducción automática instale `mpv` (Kali/Debian: `sudo apt install mpv`) y las dependencias de Python de `requirements.txt`. JARVIS busca en YouTube con `yt-dlp` y solicita a `mpv` reproducir automáticamente el primer resultado; depende de la red, la disponibilidad del contenido y la salida de audio. En Windows debe instalar `mpv` y ponerlo en PATH. No usa una cuenta de Spotify para reproducción automática. También puede pedir «detén la música». La selección automática puede no ser la versión deseada; JARVIS no verifica que se escuche realmente.

Las fuentes aparecen como enlaces clicables en el chat y no se leen en voz alta. Solo se abren cuando el usuario pulsa el enlace. La búsqueda usa fragmentos, no el contenido completo de las páginas.

### Autorización única limitada

Tras la confirmación inicial, JARVIS pregunta una vez si permite búsquedas web y música sin preguntar cada vez. Las consultas se envían a servicios externos y los contenidos web pueden inducir acciones no deseadas; active esta opción solo si acepta ese riesgo. Puede cambiarla en **Ajustes**. La autorización de búsqueda/música no incluye Gmail, terminal, archivos, interfaz, recordatorios, WhatsApp ni otras acciones: estas requieren confirmación cada vez. Si rechaza el permiso único, búsquedas y música también requieren confirmación individual. El estado se guarda en `.jarvis-state.json`.

### Analizar imágenes mediante chat o voz

Pida, por ejemplo, «Analiza la imagen /home/usuario/Imágenes/foto.png». JARVIS puede buscar un archivo por nombre y después proponer su análisis. La búsqueda de archivos requiere autorización y sus resultados pueden enviarse al proveedor del chat. `inspect_image` acepta PNG, JPEG o WebP de hasta 10 MB y, tras autorización explícita por chat o voz, lee el archivo y envía una copia y la pregunta a NVIDIA. La descripción puede enviarse al proveedor del chat y guardarse en la memoria local.

Para una imagen abierta en WhatsApp, Gmail u otra aplicación, pida «Analiza la imagen visible en mi pantalla». `inspect_screen` solicita permiso para capturar la **pantalla completa** y enviarla a NVIDIA; puede incluir otros datos privados. No accede directamente a cuentas, mensajes o adjuntos. La imagen debe estar visible; capturar puede fallar en Wayland o sesiones sin pantalla, y la ventana de JARVIS puede tapar el contenido. Alternativamente, guarde el adjunto localmente e indique su ruta.

Requiere conexión, `NVIDIA_VISION_API_KEY` o `NVIDIA_API_KEY` en `.env`, y acceso al modelo `mistralai/mistral-large-4-1t-a52b`; puede cambiarse con `NVIDIA_VISION_MODEL`. Cada envío de imagen o captura requiere aprobación separada y no se incluye en los permisos únicos de búsqueda/música. No comparta claves ni imágenes privadas sin entender que se envían a NVIDIA. Las capturas no se guardan como archivos en disco.

Si aparece un error de conexión, el detalle distingue TLS, tiempo de espera, conexión de red y respuesta HTTP cuando sea posible, sin mostrar la clave. La llamada de visión no usa variables de proxy ni sigue redirecciones; redes que requieren proxy podrían no funcionar. Una falla de conexión no confirma que la clave o la ruta sean incorrectas.

### Gmail: buscar, leer, enviar y organizar

Esta integración es de la aplicación instalada, independiente de cualquier cuenta conectada en Arena. Usa la API oficial de Gmail con permisos para **leer y modificar todo el buzón y enviar correos**. Un permiso permanente opcional permite buscar, leer, enviar, responder y clasificar sin confirmar cada acción; no elimina correos de forma permanente. Para configurarla una sola vez:

1. En Google Cloud cree un proyecto, active Gmail API y configure la pantalla de consentimiento OAuth. Cree un ID OAuth de tipo **aplicación de escritorio**. Si la aplicación está en modo de pruebas, añada su cuenta como usuario de prueba. Google podría limitar o advertir sobre aplicaciones no verificadas; usted controla el proyecto y los permisos que concede.
2. Descargue el JSON de ese cliente desde Google Cloud, póngalo en la carpeta de JARVIS y nómbrelo `gmail-credentials.json`. No lo comparta ni lo suba a Git.
3. En la carpeta de JARVIS instale las dependencias con `venv/bin/python -m pip install -r requirements.txt` en Linux (`venv\Scripts\python.exe -m pip install -r requirements.txt` en Windows). Ejecute `venv/bin/python gmail_access.py` (Windows: `venv\Scripts\python.exe gmail_access.py`). Se abrirá el navegador para iniciar sesión con Google y autorizar la lectura. No escriba contraseñas en JARVIS ni en el chat.
4. Inicie JARVIS y pida, por ejemplo, «Busca el correo de Ana sobre el recibo y analiza la imagen adjunta». Autorice la búsqueda si no ha concedido permiso permanente y luego autorice el envío de la imagen seleccionada a NVIDIA. Si hay varias coincidencias, indique cuál desea.

La búsqueda consulta hasta 10 correos, descargando sus datos para identificar imágenes; solo devuelve al modelo metadatos (remitente, asunto, fecha y nombres/IDs de imágenes), que pueden ser privados y guardarse en la memoria de chat. El adjunto aprobado se lee en memoria y se envía a NVIDIA junto con la pregunta; la descripción puede enviarse al proveedor del chat. El permiso de búsqueda/música no cubre estas acciones. La autorización se guarda en `.jarvis-gmail-token.json`, excluida de Git; protege la cuenta. Para revocar, retire el acceso de la aplicación desde su cuenta de Google y elimine el archivo de token local. La captura de pantalla sigue disponible como alternativa, pero no equivale a acceso directo a Gmail.

WhatsApp de escritorio no ofrece aquí una API personal integrada para leer mensajes o adjuntos. JARVIS no accede directamente a esa cuenta: puede analizar la pantalla visible con su permiso, o una imagen guardada localmente. No se solicitan contraseñas ni se usan datos privados de sesión de WhatsApp.

Para habilitar envío y organización después de una configuración anterior de solo lectura, actualice, instale dependencias y vuelva a ejecutar `venv/bin/python gmail_access.py` (en Windows use `venv\Scripts\python.exe`). Autorice los nuevos permisos en Google; si no se conceden, el envío y la clasificación no funcionarán. Los permisos OAuth concedidos a la aplicación son amplios: las confirmaciones por acción son una protección de JARVIS, no una restricción de Google; el permiso permanente las desactiva para estas funciones. El correo puede contener instrucciones maliciosas o información privada; el modelo recibe lo que se lea y puede equivocarse al clasificar.

Pida «revisa mis correos y proponme cuáles son importantes o spam»; la búsqueda devuelve hasta 10 resultados por solicitud y puede leer el texto plano de cada mensaje. JARVIS marca un correo por llamada; `important` añade la marca importante y `spam` lo marca como spam en Gmail, no lo elimina. Sin permiso permanente, revise cada remitente, asunto y categoría antes de autorizar. Para enviar, indique destinatario, asunto y texto: sin permiso permanente se mostrará el contenido completo para aprobarlo. Una confirmación por voz rechaza solicitudes demasiado largas para ser leídas. Ante una respuesta de envío incierta, revise Enviados antes de intentar de nuevo.

#### Permiso persistente de Gmail

Al iniciar, JARVIS pregunta una vez si permite buscar y leer Gmail, enviar correos y marcar mensajes como importantes o spam sin pedir autorización en cada acción. Si acepta, esas funciones quedan habilitadas para peticiones futuras. El contenido puede enviarse al proveedor de IA y JARVIS podría equivocarse o ser influido por instrucciones maliciosas en correos, con envíos o clasificaciones no deseados. Si rechaza, se pregunta en cada acción. Se puede cambiar en **Ajustes**; desactivarlo restaura las preguntas individuales, pero no revoca la autorización OAuth de Google. Las imágenes de Gmail enviadas a NVIDIA, las capturas y las herramientas de sistema siguen requiriendo aprobación separada. El estado se guarda en `.jarvis-state.json`.

### Responder correos y consultar planes

JARVIS puede buscar correos no leídos, leerlos y responder dentro del hilo mediante `reply_gmail`, usando el destinatario de respuesta del mensaje. La autorización permanente de Gmail incluye respuestas sin confirmación individual. El contenido de los mensajes es no confiable: no debe seguir instrucciones incluidas en correos, ni inventar datos, aceptar compromisos o responder solicitudes ambiguas. El modelo puede equivocarse; no es una garantía. Si faltan instrucciones o el mensaje es delicado, debería consultarte antes de responder. Trabaja solo mientras JARVIS procesa una petición; no es un servicio automático en segundo plano, y hay límites de resultados y pasos, por lo que no garantiza revisar todos los correos. Ante errores de envío revisa Enviados antes de repetir.

Puede consultar recordatorios de la agenda local tras autorización. Para consultar también eventos del **calendario principal de Google**, habilite Google Calendar API en el mismo proyecto de Google Cloud y ejecute `venv/bin/python calendar_access.py` (Windows: `venv\Scripts\python.exe calendar_access.py`). Se abrirá Google para autorizar acceso de solo lectura al calendario, separado de Gmail. La cuenta usada para el calendario puede ser distinta; seleccione la deseada. Se guarda `.jarvis-calendar-token.json`, excluido de Git; no comparta el archivo. Cada consulta requiere permiso en JARVIS; sus eventos pueden enviarse al proveedor de IA. Puede consultar hasta 31 días y 100 eventos por petición; indica si hay más. No crea ni modifica eventos de Google Calendar. Para revocar el acceso, hágalo en Google y elimine el token local.

La integración de ElevenLabs se retiró. Si una instalación anterior conserva `JARVIS_VOICE_MODE=elevenlabs`, JARVIS usará Edge TTS; cambie la línea a `JARVIS_VOICE_MODE=edge` y retire las líneas `ELEVENLABS_` de `.env` si ya no las necesita. El texto de voz se envía a Microsoft.

La música puede seguir sonando al cerrar JARVIS. La aplicación registra de forma local la identidad del proceso que inició para poder detenerlo después de volver a abrirla o tras un cierre inesperado; verifica PID, hora de inicio y marca antes de terminarlo, sin cerrar reproductores ajenos. La recuperación no reconoce reproductores iniciados por versiones anteriores ni está garantizada si el sistema no permite verificar el proceso. El registro `.jarvis-music.json` no se sube a Git.
