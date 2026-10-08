# TikTok LIVE TTS CLI — Made by CJVM (HoJ)

Este proyecto se distribuye bajo la licencia GNU GPL versión 3 o posterior;
consulta [LICENSE](./LICENSE).

Aplicación ligera para Windows que lee en voz alta los comentarios de una
transmisión de TikTok LIVE. Toda la interacción es por consola, con un menú
seleccionable por número o comando (`conectar`, `ajustes`, `salir`). Usa voces
de Windows ya instaladas y no pide la contraseña de TikTok.

## Requisitos y consumo

- Windows 10/11 y Python 3.11.
- Windows PowerShell; no hace falta instalar una voz SAPI si se elige Piper
  o ElevenLabs.
- Internet y una cuenta LIVE pública/visible para el conector.
- El motor Piper se instala con el programa; los modelos de voz Piper se
  descargan de forma opcional y solo si el usuario los elige.
- El sintetizador local solo se inicia al hablar y el cliente de TikTok solo se
  importa al solicitar una conexión.
- El menú ofrece voces Piper en español (España y México) e inglés, con niveles
  de calidad/tamaño. Los modelos se guardan en `data\voices` y funcionan offline.
  Cada modelo tiene una ficha y licencia propias: revísalas antes de usarlo,
  especialmente para emisiones monetizadas.

## Primera instalación

1. Instala Python 3.11 desde python.org y habilita el lanzador `py`.
2. Ejecuta `setup.bat`. Crea `.venv` e instala el conector de TikTok, Piper y
   su runtime de inferencia.
3. Ejecuta `run.bat` o `cli.bat`. En la primera configuración eliges voces
   de Windows, descargas solo los modelos locales que quieras o conectas una
   cuenta gratuita ElevenLabs.
4. En las preguntas que muestran `[Enter = ...]`, pulsa Enter para aceptar el
   valor sugerido y avanzar. El usuario y una voz activa son necesarios; la
   descarga de voces Piper sí se puede saltar.
5. Selecciona `conectar` para iniciar la lectura. Haz clic en la ventana de la
   consola y pulsa `R` para repetir el último comentario leído en voz alta, `S` para
   saltar el siguiente comentario pendiente o `Ctrl+C` para detener la conexión,
   cancelar el audio actual y volver al menú. Las teclas no son atajos globales
   y no se reciben desde otras ventanas.
   Los cambios se guardan al instante.

La configuración se guarda en `data\config.json`, dentro de la carpeta del
programa. Si existe una configuración antigua en `%APPDATA%`, se migra una vez
a la carpeta local. Ejecuta el programa desde una carpeta donde tengas permiso
de escritura. No se guardan credenciales de TikTok; la API key opcional de
ElevenLabs se guarda cifrada en `data\elevenlabs.key` mediante DPAPI de Windows.

## Voces, perfiles y volumen

En **Ajustes** puedes cambiar proveedor, administrar voces descargadas o
disponibles, elegir un perfil por voz (Natural/Ágil/Pausada/Energética),
repartir voces, cambiar volumen (0–100), lectura de nombres, longitud máxima y
capacidad de cola (1–100; predeterminada en 10). El perfil afecta la velocidad
de cada voz. Los nombres decorativos se normalizan antes de leerlos en voz alta
para evitar que símbolos y alfabetos estilizados se pronuncien como ruido.

### Instalar más voces paso a paso

1. En el menú principal, elige `3` (Ajustes) y después `2` (Gestionar voces).
2. Si todavía no usas Piper, elige `2` para instalar y usar voces Piper. Si
   Piper ya es el motor, elige `1` para descargar más voces.
3. La lista indica idioma, calidad y tamaño. Escribe un número o varios
   separados por coma (por ejemplo `1,3`) y confirma con `s`. Pulsa Enter en la
   selección para omitir la descarga en ese momento.
4. Cuando termine, elige qué voces quieres activar. Las descargas se guardan
   en `data\voices`; una voz que ya está instalada no necesita descargarse otra
   vez. Usa Ajustes > Gestionar voces > `2` para cambiar las voces Piper
   activas o la opción `3` para desinstalar una.
   Si omites la descarga y todavía no hay una voz Piper instalada, vuelve a
   elegir el motor de Windows o descarga al menos una voz antes de activar Piper.

En todos los menús, escribe el número de la opción y pulsa Enter. Las preguntas
con `[Enter = ...]` conservan el valor mostrado. En el menú principal, la
opción `5` abre la ayuda rápida con estos pasos y los controles durante LIVE.

### ElevenLabs gratuito

La opción ElevenLabs guía al usuario a crear una cuenta y una API key, la valida
contra la cuenta y enumera solo voces que la API marque disponibles para Free.
La clave debe tener permisos de cuenta, lectura de voces y texto-a-voz.
La key se cifra con DPAPI de Windows para el usuario actual; no se guarda en
`config.json`. Al probar voz o leer chat, el texto se envía al servicio y
consume los créditos compartidos de la cuenta. El programa exige tier `free` y
excedentes deshabilitados, pero no convierte la cuota en ilimitada.

El plan Free mostrado por ElevenLabs incluye una cuota mensual (actualmente
10.000 créditos; consulta [precios actuales](https://elevenlabs.io/pricing)) y
no incluye licencia comercial. Revisa sus [términos](https://elevenlabs.io/terms)
antes de emitir contenido monetizado. La configuración y la lectura con Piper
permanecen locales; la opción cloud no es necesaria para usar el programa.

Si eliges voces SAPI, solo aparecerán las instaladas en Windows. Piper permite
descargar individualmente modelos de voz gratuitos de terceros, sin enviar el
chat a un servicio remoto.

## OBS y TikTok LIVE Studio

La salida de voz va al dispositivo de reproducción predeterminado de Windows.
El menú **Audio en OBS / TikTok LIVE Studio** incluye los pasos básicos.

- En OBS, añade una fuente de captura de salida de audio para ese dispositivo.
  Si tu versión admite captura de audio por aplicación, puedes probar con el
  proceso de PowerShell para mantener la voz separada del resto del escritorio.
- En TikTok LIVE Studio, activa la captura del sonido del escritorio/dispositivo.
- Ajusta el volumen en este programa y en el mezclador del software de emisión.
- Para escuchar localmente y emitir la voz, activa el monitoreo de audio en OBS.
  Comprueba que no se capture dos veces para evitar eco.
- Para separar completamente esta voz de otros sonidos, se puede instalar y
  configurar por separado un cable de audio virtual y seleccionarlo como salida
  predeterminada. Es opcional; esta app no lo descarga ni lo instala.

La selección de un endpoint de audio por nombre no está incluida aún; el motor
usa el dispositivo predeterminado que Windows tenga configurado.

## Crear un ejecutable

Abre PowerShell en la carpeta del proyecto y ejecuta:

```powershell
.\build.ps1
```

El script reutiliza `.venv`, instala PyInstaller solo al solicitar la
compilación y crea `dist\TikTok-LIVE-Reader\`, una carpeta portable con el
ejecutable y sus dependencias. Ejecuta
`dist\TikTok-LIVE-Reader\TikTok-LIVE-Reader.exe` desde una carpeta con permiso
de escritura; su configuración se conserva en la subcarpeta `data`. Las voces
Piper no se incluyen en el ejecutable: se descargan a `data\voices` solo cuando
las seleccionas. SAPI usa las voces que Windows tenga instaladas. Al reconstruir
la aplicación, `build.ps1` conserva la subcarpeta `data` del paquete portable.

El runtime Piper está publicado bajo GPL-3.0-or-later. La carpeta de build
incluye su licencia; si redistribuyes el ejecutable, revisa y cumple las
obligaciones GPL aplicables al programa y al runtime incluido.

### Preparar una descarga de un solo archivo

Para conservar la aplicación de desarrollo y crear aparte la versión para
compartir, ejecuta en PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build-release.ps1
```

El resultado es `distros\TikTok-LIVE-Reader.exe`, con consola e icono musical
original, estilo nota de música en cian y magenta. La consola se restaura y
maximiza al iniciar. Este build no reemplaza `dist\TikTok-LIVE-Reader` ni el
código fuente, para que puedas seguir depurando y probando en paralelo.

El archivo incluye el runtime, dependencias y licencia de Piper; no incluye
modelos de voz ni preferencias tuyas. Al lado del EXE, la primera ejecución
creará `data` para guardar las preferencias y las voces que tu amigo elija
descargar. Para probar localmente: `.\.venv\Scripts\python.exe main.py`.
Para verificar cambios: `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`.
El ejecutable está pensado para Windows x64 y puede tardar unos segundos al
abrir mientras extrae sus componentes temporales.

### Compartirlo gratis con un amigo

1. Compila el EXE anterior y revisa que `distros` contenga únicamente
   `TikTok-LIVE-Reader.exe`. No envíes `data\config.json` ni
   `data\elevenlabs.key`; el build nuevo no los incorpora.
2. Para publicarlo con GitHub Releases, crea un repositorio público en GitHub
   (el contenido del repositorio será público), sube el código fuente y las
   licencias correspondientes, crea una etiqueta/release y adjunta
   `distros\TikTok-LIVE-Reader.exe` como archivo de descarga. Comparte el
   enlace de la página del Release, no una captura de pantalla.
3. Si no quieres hacer público el código, usa un enlace restringido de Google
   Drive u otro servicio similar y comparte con tu amigo tanto el EXE como los
   materiales fuente/licencias que debas proporcionar. Verifica el acceso en
   una ventana privada antes de mandárselo.
4. Tu amigo descarga el archivo, elige **Conservar/Keep** si Microsoft Defender
   SmartScreen muestra una advertencia y confía en el origen, luego lo ejecuta.
   En el asistente ingresa su propio usuario de LIVE y elige SAPI o descarga
   bajo demanda una voz Piper. No necesita instalar Python.

El runtime Piper incluido y este proyecto se distribuyen bajo GPL-3.0-or-later.
El repositorio público debe incluir el código fuente correspondiente y los
avisos/licencias de dependencias; consulta también las licencias de los modelos
de voz descargados, que pueden variar. No afirmes que el EXE es oficial de
TikTok ni uses su marca como si estuviera avalado por TikTok. Windows puede
mostrar una advertencia de aplicación desconocida porque el archivo no está
firmado digitalmente; no indiques a tus amigos que ignoren alertas de antivirus.

Para que tu amigo compruebe la descarga, puedes enviarle también este hash:

```powershell
Get-FileHash .\distros\TikTok-LIVE-Reader.exe -Algorithm SHA256
```

## Alcance y limitaciones

- Solo lee comentarios; no envía mensajes ni procesa regalos.
- La cola de voz es limitada (10 comentarios por defecto); si se llena, se
  descarta el comentario entrante para no acumular retraso indefinidamente.
- Al reconectar se ignoran IDs de comentarios ya vistos en la sesión y no se
  solicita el historial del chat. La caché de IDs está limitada a 2048 entradas.
- El conector `TikTokLive` es una biblioteca no oficial y su propia documentación
  advierte que no es una API de producción. TikTok puede cambiar su servicio o
  limitar conexiones. La reconexión automática aplica esperas de 2 a 60 segundos,
  pero no puede reparar cambios incompatibles del servicio.
- Comentarios de salas privadas, restricciones de región/cuenta, CAPTCHA,
  usuario inexistente o sala sin LIVE visible pueden impedir la conexión.
- No se elude CAPTCHA ni se solicitan datos de acceso. La configuración solo
  contiene preferencias locales y usuario público de LIVE.
- El conector se importa únicamente al conectar, y el sintetizador de Windows
  solo se inicia al hablar, para reducir el consumo cuando la app está inactiva.
- Las voces Piper provienen de un repositorio externo y sus licencias pueden
  variar por modelo. Los archivos no se redistribuyen dentro del ejecutable.
- ElevenLabs procesa el texto que se le envía según sus términos y configuración
  de cuenta; la API gratuita no garantiza cero retención ni uso comercial.

## Desarrollo y comprobaciones

La aplicación y el guardado usan la biblioteca estándar de Python. Las pruebas
unitarias no necesitan conectar con TikTok. Para correrlas:

```powershell
py -3.11 -m unittest discover -s tests -v
```

Los archivos fuente usan una estructura pequeña: `main.py` y `cli_main.py`
inician la CLI; `livevoice\app.py` implementa los menús; `livevoice\connector.py`
conecta, evita duplicados y reintenta; `livevoice\speech.py` integra SAPI, Piper
y ElevenLabs; `livevoice\piper_voices.py` administra los modelos descargables;
`livevoice\elevenlabs.py` llama a la API y `livevoice\secrets_store.py` cifra
la key del proveedor en Windows.
