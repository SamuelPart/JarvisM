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

Al iniciar se anuncia «Activando protocolos de seguridad...» y se pide una confirmación inicial, guardada en `.jarvis-state.json`. Borre este archivo para volver a solicitarla. Escriba un mensaje o `/voz` para hablar, `/actualizar` para actualizar y `/salir` para cerrar. Las respuestas se muestran por texto y se intenta reproducirlas por voz. Una autorización opcional permite de una vez búsquedas, música, abrir sitios y aplicaciones compatibles, agenda, archivos, volumen y brillo, Gmail, resumen inicial y actualizaciones automáticas. Los comandos de terminal, control directo de interfaz e imágenes siguen requiriendo autorización por acción. Las herramientas se ejecutan con los permisos del usuario; no lo ejecute como administrador. Revise cada comando y ruta: no hay sandbox ni lista negra capaz de hacer seguro un shell arbitrario. Los resultados de herramientas y archivos pueden contener información privada enviada a Gemini, y las instrucciones maliciosas en datos externos siguen siendo un riesgo. La búsqueda web devuelve fragmentos no confiables para que el modelo los resuma; no descarga páginas completas.

## Administración en Kali

Pide instalar un paquete APT por su nombre exacto o actualizar el sistema. JARVIS sigue ejecutándose como usuario normal y solicita aprobación para cada operación administrativa. Después `pkexec` pide autenticación mediante el agente gráfico del sistema; nunca escribas la contraseña en el chat. Para actualizar ejecuta `apt-get update` y después `apt-get upgrade`, que pueden pedir autenticación por separado; no ejecuta `dist-upgrade`. Requiere APT, polkit, repositorios configurados y permisos administrativos. Puede fallar o necesitar intervención si hay conflictos o paquetes que requieren interacción. La instalación se limita a un único nombre de paquete APT y no admite comandos arbitrarios. No se ha probado en todas las instalaciones de Kali.

## Actualizaciones

`/actualizar` o «Jarvis, busca actualizaciones» pide confirmación y realiza `git fetch` del remoto de seguimiento. Se actualiza únicamente mediante fast-forward, sin borrar cambios locales ni resolver divergencias, y se bloquea si el árbol contiene cambios o archivos sin seguimiento. Si cambió `requirements.txt`, instala las dependencias con el Python activo. Tras una actualización correcta reinicia el programa. Si falla pip, el código ya actualizado permanece en disco: repare el entorno manualmente antes de iniciar de nuevo. `.env` y el estado local no se modifican por el actualizador.

La autorización amplia activa la comprobación automática al iniciar tanto la interfaz como la consola. También se puede habilitar con `JARVIS_AUTO_UPDATE=1`. Esto permite ejecutar código y dependencias nuevos del remoto sin confirmación adicional: úselo solo con repositorios, ramas y mantenedores de plena confianza. Proteja la rama y revise las dependencias; Git no verifica por sí solo que el código sea seguro. Se necesita red y autenticación Git ya configurada. Las conversaciones completadas permanecen en SQLite tras reiniciar.

## Personalizar la voz

Por defecto, Edge TTS usa `es-MX-JorgeNeural`. En `.env`, cambie `JARVIS_TTS_VOICE` a otra voz disponible, por ejemplo `es-ES-AlvaroNeural` o `es-ES-ElviraNeural`. Para consultar el catálogo actual ejecute `venv/bin/edge-tts --list-voices` (en Windows `venv\Scripts\edge-tts.exe --list-voices`). La disponibilidad depende del servicio externo. Reinicie JARVIS para aplicar los cambios.

El texto pronunciado se envía a Microsoft: no use el modo neuronal con información que no desee compartir. Para no enviar texto a ese servicio, configure `JARVIS_VOICE_MODE=local`; para desactivar la voz, `JARVIS_VOICE_MODE=off`. Las respuestas se seguirán mostrando en consola. La reproducción es secuencial y se realiza en segundo plano; al salir del programa puede interrumpirse.

## Interfaz de escritorio

En Linux, el instalador crea **JARVIS** en el escritorio (cuando existe) y en el menú de aplicaciones. Al abrirlo se muestra la interfaz gráfica sin terminal. También se actualiza el acceso al iniciar la interfaz; no sobrescribe un archivo ajeno con el mismo nombre. Para una instalación existente, después de actualizar ejecuta una vez `venv/bin/python desktop_launcher.py`. Algunos escritorios pueden pedir que marques el acceso como confiable antes de abrirlo. Si mueves el proyecto, vuelve a crear el acceso.

Después de instalar las dependencias, inicie `venv/bin/python gui.py` en Linux o `venv\Scripts\python.exe gui.py` en Windows. La ventana funciona por voz: pulse el icono de micrófono, diga «Jarvis» seguido de su orden o espere la respuesta «Le escucho» y diga su orden; diga exactamente «autorizo» para aprobar las herramientas que no tengan permiso permanente. Cualquier otra respuesta, silencio, error de reconocimiento o fallo de voz rechaza la acción. Pulse de nuevo el icono de micrófono para detener la escucha; puede tardar mientras termina la captura o solicitud en curso. La clave y la voz se configuran en el mismo `.env` que usa la consola; el texto hablado puede enviarse a Microsoft si está activado Edge TTS. El audio capturado se envía a Google para transcribirlo. La interfaz también busca actualizaciones al iniciar si se autorizó la automatización amplia o `JARVIS_AUTO_UPDATE=1`; tras actualizar se reinicia antes de abrir el chat. Las conversaciones completadas se conservan localmente. Se necesita una sesión gráfica. Para actualizar desde consola, salga de la interfaz primero.

### Animación del núcleo

El núcleo central es la esfera clásica azul de puntos dibujada por Qt, creada por código, sin GIF. Se mueve continuamente y con mayor intensidad cuando JARVIS habla. La animación de voz es decorativa y no mide el audio real.

La confirmación por voz **no verifica la identidad**: otra persona, una grabación o el reconocimiento erróneo podrían decir «autorizo». No use este modo en entornos compartidos ni para acciones que no pueda supervisar. JARVIS lee los argumentos de la acción, pero los comandos y rutas pueden pronunciarse de forma ambigua; no apruebe si no los ha entendido. Para mayor seguridad use la consola y revise cada comando en pantalla. Al desactivar el micrófono se rechazan autorizaciones pendientes, pero no se interrumpe una acción ya iniciada. La primera autorización de instalación sigue siendo una confirmación gráfica.

La activación por «Jarvis» usa reconocimiento de voz de Google, no detección local: con el micrófono activado, cada frase capturada se envía a Google aunque no contenga la palabra. Requiere Internet y puede reconocerla incorrectamente. El botón apaga la escucha.

El chat comienza oculto: pulse 💬 para mostrarlo u ocultarlo. Pulse 🎙 para activar o detener el micrófono. En Chat, escriba y pulse Enviar; las herramientas sin permiso permanente requieren autorización en el chat, que muestra los argumentos completos; responda AUTORIZO o NO. Puede desactivar la lectura en voz alta con la casilla. El envío de mensajes se desactiva durante la sesión de voz y el micrófono se desactiva durante una solicitud escrita. Las conversaciones completadas se guardan en memoria local.

### Preparar un mensaje de WhatsApp

Pida a JARVIS que prepare el mensaje e indique el número con código de país. En modo voz JARVIS lee el número y el texto completo (hasta 700 caracteres) y pregunta si autoriza abrir el borrador; en chat muestra los datos para aprobar. Esto se solicita para cada mensaje. Tras confirmarlo abre un borrador mediante `wa.me` en el navegador. Requiere WhatsApp Web o la aplicación vinculada. **No envía el mensaje por sí sola**: revise destinatario y contenido y pulse Enviar. JARVIS no tiene acceso a sus contactos y no debe inventar números. La apertura del navegador tampoco confirma que el mensaje haya sido entregado.

Si aparece un error Gemini, la interfaz muestra su código HTTP y una explicación general sin exponer la clave ni el contenido de la respuesta. El código no demuestra por sí solo la causa exacta; compruebe modelo, acceso y cuota de la cuenta según el caso.

## Clima visual

Pide por voz o chat «dime el clima en Trujillo, Perú» o «clima en Perú». JARVIS muestra la esfera transformándose con pulsos y destellos durante al menos tres segundos, acompañada de un breve sonido electrónico original (desactivable en Ajustes) mientras busca y, al obtener datos, reduce la esfera hacia la parte inferior izquierda de su ventana y muestra el clima en un cuadro con tarjetas de colores e iconos; **Volver** restaura la vista habitual. La pantalla muestra temperatura, sensación, condiciones, humedad, viento, precipitación, probabilidad de lluvia, máxima, mínima, UV, amanecer, atardecer y el pronóstico de tres días cuando el proveedor los incluye. La espera mínima solo se aplica a resultados correctos en la interfaz de escritorio; los errores se muestran sin demora artificial. La hora en la tarjeta es la hora local del dato del proveedor. No todos los datos están disponibles en todas las ubicaciones.

La lista de países y capitales se incluye localmente (datos de [mledoze/countries](https://github.com/mledoze/countries), licencia ODbL en `data/COUNTRIES-LICENSE.txt`). Las consultas envían la ubicación indicada a OpenStreetMap Nominatim (geolocalización) y Open-Meteo (coordenadas para el pronóstico). Se usa el permiso persistente de búsquedas y música, o se pide autorización individual. Si se indicó solo un país se muestra el clima de su capital y se señala explícitamente; no representa todo el país. Si hay ubicaciones ambiguas se solicita aclaración. Con el permiso persistente y la vista abierta, se intenta actualizar cada diez minutos; si falla, se conservan los datos anteriores marcados como tales. Open-Meteo proporciona datos modelados recientes, no garantiza observaciones instantáneas ni exactitud en toda la región. Requiere Internet.

## Correos programados con Gmail

Pide por voz o chat, por ejemplo: «Programa un correo para [dirección], asunto [asunto], mensaje [texto], dentro de diez minutos». También admite horas, días, semanas, meses y años o una fecha y hora concretas. JARVIS debe pedir los datos que falten y no enviar el mensaje en el momento de programarlo. Las duraciones de meses y años usan calendario, no meses de treinta días; si la fecha no existe o la hora es ambigua por cambio horario, pide otra fecha.

La primera programación solicita autorización persistente, separada del permiso general de Gmail: permite programar y enviar correos sin preguntar cada vez. Incluye envíos futuros que podrían ser erróneos o inducidos por datos maliciosos. Puedes detener futuros envíos en **Ajustes → Permitir programar y enviar correos**; un envío ya iniciado no se interrumpe. La cuenta Gmail debe estar configurada previamente. Los mensajes se envían con la cuenta configurada en JARVIS en el momento del envío; si cambias de cuenta antes, podrían salir desde la cuenta nueva. La programación es **local**, no es la función Programar envío de Google: **JARVIS debe estar abierto, conectado y autorizado cuando llegue la hora**. Si estaba cerrado, intentará enviar el correo vencido cuando vuelva a abrirse; puede enviarse tarde. El sistema y su reloj deben funcionar correctamente.

Los destinatarios, asuntos, mensajes y fechas pendientes se guardan sin cifrar en `.jarvis-scheduled-email.sqlite3`, con permisos del usuario, excluido de Git. No incluyas información que no quieras guardar en ese equipo. Puedes pedir «¿qué correos tengo programados?» o «cancela el correo programado de [asunto]» antes de que empiece el envío. Los estados `sending` o `uncertain` indican resultado desconocido: **revisa Gmail Enviados antes de reintentar**. Para evitar duplicados, JARVIS no reintenta automáticamente si el envío falló o se interrumpió y podría haberse enviado. El texto se conserva localmente en esos casos; cancelar o confirmar el envío lo elimina de la cola. No se garantiza entrega ni una hora exacta, y esta función no sustituye un servicio de programación siempre activo.

## Proveedor NVIDIA NIM

Puede seleccionar NVIDIA en vez de Gemini, tanto en chat como en voz. Cree una clave nueva en NVIDIA y añada en su `.env` local:

```dotenv
JARVIS_PROVIDER=nvidia
NVIDIA_API_KEY=su_clave_nueva
NVIDIA_MODEL=nvidia/nemotron-3.5-bolt-e4b
```

No comparta ni suba la clave. Si se expone, revóquela y cree otra. Reinicie JARVIS tras editar `.env`. El modelo y sus herramientas dependen de la disponibilidad y los permisos de su cuenta NVIDIA; el ejemplo no garantiza acceso ni cuota gratuita. Se envían conversación y resultados de herramientas a NVIDIA. Los permisos de herramientas son los mismos que con Gemini. Para regresar a Gemini, use `JARVIS_PROVIDER=gemini`. **No hay cambio automático entre proveedores**, y la memoria local de conversaciones es compartida entre proveedores. WhatsApp abre un borrador; no lo envía automáticamente.

### Núcleo expresivo

La esfera clásica indica el estado mediante color y movimiento: paleta elegida en espera, violeta al procesar, cian al hablar y ámbar cuando espera autorización. Si una solicitud está pendiente, el color ámbar tiene prioridad sobre la voz. La animación de voz es decorativa, no sigue el volumen real.

### Modo compacto flotante

Pulse «Modo compacto» para mantener una ventana pequeña sobre las demás con el núcleo, el estado y los iconos de chat y micrófono. Pulse «Abrir chat» para volver a la ventana completa sin perder la conversación de la sesión. El ajuste «Siempre visible» se conserva para el modo completo; la ventana compacta solicita estar siempre visible, sujeto al gestor de ventanas. Si hay una solicitud de chat en curso, el botón de micrófono queda desactivado hasta que termine. Las acciones críticas siguen requiriendo confirmación.

### Ajustes visuales

En la ventana completa pulse «Ajustes» para elegir el color en espera, su tamaño y animación normal o reducida. La esfera se mueve siempre; una preferencia antigua de animación desactivada se convierte a reducida. Pulse Guardar para conservar los cambios entre reinicios; Cancelar no los aplica. El color ámbar de autorización se mantiene independientemente de la paleta. Las preferencias locales se guardan en `.jarvis-ui.json` (ignorado por Git); no contienen claves. En modo compacto, abra el chat para acceder a Ajustes.

### Memoria entre sesiones

JARVIS guarda localmente los pares de mensajes y respuestas completadas en `.jarvis-memory.sqlite3`, ignorado por Git. En la ventana completa, pulse **Memoria** para escribir preferencias explícitas (por ejemplo, «prefiero respuestas breves») y guardarlas; no se extraen preferencias automáticamente. El botón de borrado elimina conversaciones y preferencias locales y limpia el contexto de la sesión. No borra ajustes visuales, `.env`, copias de seguridad ni información que ya hayan recibido servicios externos.

Al iniciar, el chat muestra hasta 20 mensajes recientes. Antes de cada nueva petición se envían al proveedor seleccionado los últimos 20 mensajes y las preferencias, además del nuevo mensaje; la base no está cifrada. Evite introducir claves o datos que no desee almacenar o transmitir; proteja su equipo y sus copias de seguridad. SQLite usa `secure_delete`, pero no se garantiza borrado forense en discos, copias o servicios externos. Las llamadas/resultados internos de herramientas y tareas incompletas no se guardan como tal, por lo que una tarea interrumpida no se reanuda exactamente. Las peticiones fallidas no se guardan como turno completado.

### Agenda y recordatorios

En la ventana completa pulse **Agenda**, escriba una descripción y seleccione la fecha y hora local; también puede seleccionar y eliminar avisos de la lista. Los avisos se guardan en `.jarvis-agenda.sqlite3`, ignorado por Git. Puede pedir a JARVIS que cree uno: consultará la hora y pedirá autorización antes de guardarlo. Verifique la fecha, hora y zona horaria en la solicitud.

La ventana de JARVIS debe estar abierta para recibir los avisos a tiempo. Se comprueban aproximadamente cada 5 segundos y, si el programa estaba cerrado, los vencidos aparecen al volver a abrirlo; no es un servicio de sistema ni suena con el equipo apagado. Los avisos ya reclamados no se repiten; una interrupción inesperada justo al mostrarlos puede hacer que se pierdan, por lo que no es adecuado para alertas críticas. Hay aviso visual y se intenta reproducir la voz. Si el micrófono está activo, se encola el aviso para decirlo entre capturas, sin interrumpir una autorización; puede demorarse mientras termina la escucha o la solicitud. El texto hablado se envía a Microsoft si Edge TTS está activo. La agenda no está cifrada y no se borra al borrar la memoria de conversación; elimine los recordatorios desde Agenda. Para eliminar uno, di o escribe «elimina el recordatorio de tomar agua». La primera vez se solicita una autorización persistente específica para eliminar recordatorios locales; al aceptarla se recuerda y puede revocarse en **Ajustes**. Si hay varios parecidos, JARVIS pregunta de qué hora es y espera la respuesta por voz o chat. Si siguen coincidiendo, pide solo el dato adicional necesario; no borra ninguno hasta identificarlo. No elimina eventos de Google Calendar. La hora depende del reloj y la zona horaria del equipo. Admite expresiones sencillas como «recuérdame tomar agua dentro de diez minutos»; otras fechas pueden requerir aclaración.

### Búsqueda web con fuentes

Al pedir información actual, JARVIS usa `web_search`, con permiso individual o con la autorización previa de búsquedas. Se envía la consulta mediante `ddgs` a DuckDuckGo; si falla o no tiene resultados se prueban Brave y Yahoo y se devuelven hasta seis títulos, enlaces y fragmentos; el proveedor de IA recibe esos datos para resumirlos y citar los enlaces. No se descargan ni verifican las páginas completas: los fragmentos pueden estar desactualizados o ser erróneos y las respuestas del modelo pueden equivocarse o citar mal. Abre las fuentes para comprobar información importante. Si los buscadores están bloqueados, no hay conexión o no hay resultados, JARVIS debe informarlo en lugar de inventar una respuesta. El texto web es contenido no confiable y puede contener instrucciones maliciosas; Los comandos arbitrarios e imágenes requieren autorización individual; los archivos pueden autorizarse de manera persistente mediante automatización amplia.

### Música automática y enlaces

Para música en **Linux con Google Chrome**, JARVIS busca el primer resultado de YouTube con `yt-dlp` y solicita abrirlo en una pestaña nueva de Chrome, sin extensiones ni Playwright. Chrome puede abrir una ventana si no hay ninguna abierta y elige el perfil según su propia configuración. JARVIS no puede verificar si la pestaña se abrió o el video se reproduce, ni pausarlo: pausa el video directamente en YouTube. La música puede seguir sonando después de cerrar JARVIS.

Playwright ya no se necesita para música. Para eliminar **solo los navegadores descargados por Playwright** en la cuenta actual, revisa primero `ls ~/.cache/ms-playwright` y, si no los necesitan otros proyectos, ejecuta `rm -rf ~/.cache/ms-playwright`. Esto no desinstala Google Chrome ni borra su perfil. En el entorno virtual de JARVIS puedes retirar también la biblioteca con `venv/bin/python -m pip uninstall playwright`; no elimina dependencias de otros entornos.

Las fuentes aparecen como enlaces clicables en el chat y no se leen en voz alta. Solo se abren cuando el usuario pulsa el enlace. La búsqueda usa fragmentos, no el contenido completo de las páginas.

### Autorización única limitada

Al iniciar se ofrece una sola autorización amplia persistente. Incluye búsquedas y música, apertura de sitios y aplicaciones compatibles, hora y agenda (incluidos recordatorios nuevos), lectura, creación, modificación y movimiento de archivos, control de volumen y brillo, lectura y envío de Gmail, resumen inicial y actualización automática de código y dependencias. Una instrucción mal entendida o datos maliciosos podrían provocar envío de correos, sobrescritura o movimiento de archivos; los datos pueden enviarse a proveedores externos. No concede terminal arbitraria, control directo de ratón y teclado, imágenes, administración del sistema ni borradores de WhatsApp: esas acciones siguen pidiendo autorización. WhatsApp sigue siendo un borrador y requiere pulsar Enviar. Los permisos se guardan en `.jarvis-state.json`; pueden cambiarse en **Ajustes**. Al desactivar automatización, desactiva también las casillas independientes de Gmail, búsquedas, agenda y resumen si quieres revocarlas: estas conservan su propia decisión. Si `JARVIS_AUTO_UPDATE=1` está configurado, la actualización seguirá activada aunque desactives automatización.

**Rutina:** pide «configura mi rutina con Chrome y Firefox» y después «buenos días». La rutina ofrece el resumen y solicita abrir las aplicaciones configuradas. En Linux solo admite Chrome, Firefox, WhatsApp para Linux y Archivos, según disponibilidad en PATH; no puede confirmar que se abrieron. Sin configuración muestra solo el resumen. Puedes decir «configura mi rutina sin aplicaciones». Recordatorios, búsquedas, controles y Gmail dependen de sus instalaciones, conexiones y permisos externos; la autorización de JARVIS no configura OAuth ni instala aplicaciones.

### Analizar imágenes mediante chat o voz

Pida, por ejemplo, «Analiza la imagen /home/usuario/Imágenes/foto.png». JARVIS puede buscar un archivo por nombre y después proponer su análisis. La búsqueda de archivos requiere autorización individual o el permiso amplio; sus resultados pueden enviarse al proveedor del chat. `inspect_image` acepta PNG, JPEG o WebP de hasta 10 MB y, tras autorización explícita por chat o voz, lee el archivo y envía una copia y la pregunta a NVIDIA. La descripción puede enviarse al proveedor del chat y guardarse en la memoria local.

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

Puede consultar recordatorios de la agenda local con permiso individual o con el permiso persistente de consulta de agenda. Para consultar también eventos del **calendario principal de Google**, habilite Google Calendar API en el mismo proyecto de Google Cloud y ejecute `venv/bin/python calendar_access.py` (Windows: `venv\Scripts\python.exe calendar_access.py`). Se abrirá Google para autorizar acceso de solo lectura al calendario, separado de Gmail. La cuenta usada para el calendario puede ser distinta; seleccione la deseada. Se guarda `.jarvis-calendar-token.json`, excluido de Git; no comparta el archivo. Cada consulta requiere permiso en JARVIS salvo que active el permiso persistente de consulta; sus eventos pueden enviarse al proveedor de IA. Puede consultar hasta 31 días y 100 eventos por petición; indica si hay más. No crea ni modifica eventos de Google Calendar. Para revocar el acceso, hágalo en Google y elimine el token local.

La integración de ElevenLabs se retiró. Si una instalación anterior conserva `JARVIS_VOICE_MODE=elevenlabs`, JARVIS usará Edge TTS; cambie la línea a `JARVIS_VOICE_MODE=edge` y retire las líneas `ELEVENLABS_` de `.env` si ya no las necesita. El texto de voz se envía a Microsoft.

Si hay un reproductor mpv registrado por la versión anterior, JARVIS puede intentar detenerlo verificando su identidad. La pausa de la nueva ventana controlada no cierra otras pestañas. El registro heredado `.jarvis-music.json` no se sube a Git.

JARVIS muestra de inmediato que está procesando la solicitud, pero no puede garantizar respuestas en menos de dos segundos: dependen del proveedor de IA, la red, la voz y las herramientas usadas.

#### Permiso persistente de consulta de agenda

JARVIS pregunta una vez si autoriza consultar hora, recordatorios locales y Google Calendar sin pedir permiso para cada herramienta. Si acepta, puede preguntar por sus pendientes sin repetir esas autorizaciones; los datos pueden enviarse al proveedor de IA. Puede activar o desactivar esta opción en **Ajustes**. Rechazarla mantiene la confirmación individual. Crear recordatorios y archivos pueden estar incluidos en la automatización amplia; terminal, capturas e imágenes siguen teniendo permisos separados. Google Calendar requiere su autorización OAuth aparte y Gmail mantiene su propia opción persistente.

### Saludo y revisión al iniciar

Con el permiso persistente **Resumen automático al iniciar**, JARVIS saluda según la hora y pregunta cómo está; después consulta en segundo plano los recordatorios pendientes de hoy o anteriores, los eventos que quedan hoy del calendario principal de Google (si está conectado), batería si existe, memoria y espacio libre. Resume hasta dos nombres de cada fuente e indica si hay más. Muestra avisos de memoria o disco al 90 % y una disminución de al menos 5 GiB desde la última revisión. Puede tardar si Google Calendar no responde. En la ventana muestra el resumen en el chat e intenta leerlo si la voz del chat está activada; si hay una sesión de voz o chat en curso, no lo interrumpe y deja el resumen en el chat. En consola el saludo puede leerse en voz alta y el resumen se imprime sin voz.

En Linux cuenta hasta 101 registros de gravedad error o superior disponibles mediante `journalctl` desde la revisión anterior, con un máximo de siete días. Un registro de error **no implica necesariamente una anomalía nueva**, y los permisos o el registro pueden impedir ver todos los eventos. En Windows no se consultan esos registros. La primera ejecución solo crea la referencia: no puede decir qué pasó antes. El sistema no vigila mientras está cerrado, no revisa todos los archivos, no diagnostica malware y no garantiza detectar anomalías. Se guardan únicamente la hora y espacio libre de la revisión en `.jarvis-briefing.json`, excluido de Git. Si pide detalles de esos registros, JARVIS puede consultar hasta 10 mensajes del intervalo anterior; pueden contener datos privados y enviarse al proveedor del chat. El texto leído con Edge TTS se envía a Microsoft.

JARVIS pregunta una sola vez si activa este resumen; al aceptarlo o rechazarlo recuerda la decisión aunque cierre y abra la aplicación. Puede cambiarla en **Ajustes → Resumen automático al iniciar**. El permiso incluye consultar los registros detallados si se solicitan, no incluye modificar archivos, ejecutar comandos arbitrarios ni acciones destructivas. Google Calendar requiere la autorización OAuth ya descrita. El resumen no se envía al modelo de chat por sí mismo; al pedir detalles, los resultados de herramientas sí pueden enviarse al proveedor de IA.

Para órdenes directas como «pon la canción de Cristo Rata» o «pausa la música», JARVIS ejecuta la herramienta correspondiente sin depender de que el modelo elija llamarla. Respeta los permisos de música y responde según el resultado comprobado; no asegura que se oiga el sonido. Otras expresiones pueden seguir siendo interpretadas por el modelo.

Cuando el modelo llama a la herramienta de música, JARVIS usa su resultado real para responder; las solicitudes de música sin ninguna llamada no se presentan como reproducciones exitosas. La verificación corresponde solo al instante de la comprobación.
