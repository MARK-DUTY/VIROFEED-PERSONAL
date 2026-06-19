# 🎬 ViroFeed AI Personal — Guía de uso

Tu propio programa para convertir una **noticia (URL)** en un **video corto viral**
(Reels / TikTok / Shorts) automáticamente. Gratis y en tu PC.

---

## ✨ ¿Qué hace?

Pegas la URL de una noticia → el programa solo:
1. Lee la noticia
2. Escribe un guión viral con IA (en español)
3. Genera la voz
4. Descarga imágenes
5. Pone subtítulos sincronizados
6. (Opcional) Añade un avatar hablando
7. Te entrega el video `.mp4` listo + títulos y hashtags

---

## 🧩 Lo que necesitas (todo gratis)

| Cosa | Para qué | Dónde se consigue |
|---|---|---|
| **Python** | Motor del programa | https://www.python.org/downloads/ |
| **FFmpeg** | Arma el video | El instalador intenta ponerlo solo |
| **Clave de Groq** | Escribe el guión (IA) | https://console.groq.com |
| **Clave de Pexels** | Imágenes | https://www.pexels.com/api/ |

> 💡 Las claves son gratis y **no piden tarjeta de crédito**.

---

## 🚀 Instalación (SOLO la primera vez)

### Paso 1 — Instalar Python
1. Entra a https://www.python.org/downloads/ y descarga Python.
2. Al instalarlo, **marca la casilla que dice "Add Python to PATH"** (¡muy importante!).
3. Termina la instalación.

### Paso 2 — Conseguir tus 2 claves gratis
- **Groq:** entra a https://console.groq.com → crea cuenta → "API Keys" → "Create API Key" → copia la clave.
- **Pexels:** entra a https://www.pexels.com/api/ → crea cuenta → copia tu "API Key".

### Paso 3 — Instalar el programa
1. Descomprime esta carpeta donde quieras (por ejemplo, en el Escritorio).
2. Haz **doble clic en `setup_windows.bat`**.
3. Espera a que termine (instala todo solo). Si te pide permiso para FFmpeg, acepta.

### Paso 4 — Pegar tus claves
1. En la carpeta verás que apareció un archivo llamado **`.env`**.
2. Ábrelo con el **Bloc de notas**.
3. Pega tus claves donde dice `PEGA_AQUI...`:
   ```
   GROQ_API_KEY=tu_clave_de_groq
   PEXELS_API_KEY=tu_clave_de_pexels
   ```
4. **Guarda** el archivo (Archivo → Guardar).

✅ ¡Listo! Eso fue solo una vez.

---

## ▶️ Cómo usar el programa (cada vez)

1. Haz **doble clic en `run_windows.bat`**.
2. Se abre una ventana negra (no la cierres) y luego tu navegador en `http://localhost:5000`.
3. **Pega la URL** de una noticia.
4. Elige duración, estilo, voz, color de subtítulos.
5. Clic en **🚀 Crear video**.
6. Espera 1–4 minutos. Cuando termine, podrás **ver y descargar** el video, y copiar los títulos y hashtags.

Los videos se guardan también en la carpeta **`output`**.

Para cerrar el programa: cierra la ventana negra.

---

## 🧑‍🎤 Activar el avatar hablando (opcional)

Por defecto el programa hace videos **faceless** (sin cara): gratis e ilimitado.

Si quieres el avatar hablando:
1. Crea una cuenta gratis en https://www.d-id.com y copia tu API key.
2. En el archivo `.env` pon:
   ```
   AVATAR_ENABLED=true
   DID_API_KEY=tu_clave_de_did
   ```
3. Pon una foto tuya (cara visible) en `assets/avatar.jpg`.
4. En la página, activa el interruptor **"Avatar hablando"**.

> ⚠️ El plan gratis de D-ID tiene un límite de videos al mes. Úsalo cuando de verdad lo necesites.

---

## 🆘 Problemas comunes

| Problema | Solución |
|---|---|
| "No tienes Python instalado" | Reinstala Python marcando **Add Python to PATH** |
| "No encontré FFmpeg" | Instálalo: en la ventana negra escribe `winget install Gyan.FFmpeg` o descárgalo de gyan.dev |
| "Faltan claves en .env" | Abre `.env`, pega Groq y Pexels, guarda y recarga la página |
| "Groq rechazó la clave (401)" | Revisa que copiaste bien la clave de Groq |
| El video no tiene imágenes | Revisa tu clave de Pexels y tu internet |
| La voz no se genera | Edge TTS necesita internet; revisa tu conexión |

---

## 💰 Costo

| Pieza | Costo |
|---|---|
| Guión (Groq) | Gratis |
| Voz (Edge TTS) | Gratis e ilimitado |
| Imágenes (Pexels/Pixabay) | Gratis |
| Video (FFmpeg) | Gratis |
| Avatar (D-ID) | Gratis con límite mensual |

**Total en modo faceless: $0** 🎉



---

## ✍️ NUEVO: Modo Historia (crea un video desde tu propia historia)

Ya no solo funciona con URLs de noticias. Ahora puedes **escribir tu propia historia**
y el programa la convierte en video.

**Cómo se usa:**
1. En la página principal, arriba hay dos pestañas: **📰 Noticia (URL)** y **✍️ Mi historia**.
2. Entra a **✍️ Mi historia** y escribe tu historia con todos los detalles que
   quieras que aparezcan (mientras más detalle, mejores imágenes).
3. Elige el **número de imágenes** (mínimo 8) y la duración.
4. Pulsa **"✍️ Generar guion y prompts"**.
5. El programa te muestra el **guion dividido en escenas** y, por cada escena, el
   **prompt de la imagen** (en inglés). Puedes:
   - ✏️ Editar el **diálogo** (lo que se narra).
   - 🎨 Editar el **prompt** de cualquier imagen.
   - ✍️ Pulsar **"Reescribir mi historia"** si quieres cambiarla por completo.
6. Cuando te gusten, pulsa **"🎨 Generar voz e imágenes"**.
7. Te lleva a la pantalla de siempre para revisar/regenerar las imágenes y, por
   último, **generar el video final**.

> 💡 La ventaja del Modo Historia: **apruebas los prompts antes** de que el programa
> gaste tiempo generando imágenes.

---

## 🎵 NUEVO: Música de fondo (3 opciones)

Ahora el programa **le pone música automáticamente** a tus videos, pero tú decides.
En la pantalla de revisión (antes de generar el video final) eliges una de **3 opciones**:

1. **🎵 Automática** *(viene activada por defecto)*: el programa le pone una música
   instrumental suave. Esta música la **crea el propio programa** con sonidos
   generados (no es de nadie), así que es **100% libre de derechos de autor** — nunca
   tendrás un reclamo de copyright.
2. **⬆️ Mi propia música**: subes tu archivo (MP3, WAV, etc.). Lo más seguro es
   descargarla de la **Biblioteca de audio de YouTube** (YouTube Studio → Biblioteca
   de audio).
3. **🔇 Sin música**: el video va solo con la voz.

En "Automática" y "Mi propia música" puedes ajustar el **volumen** (la voz siempre se
escucha por encima; la música baja sola y hace *fade out* al final).

> 💡 La primera vez que generes un video con música automática, el programa tardará
> unos segundos extra creando las pistas (solo pasa la primera vez; después quedan
> guardadas).

### ⚠️ Sobre los derechos de autor (copyright)
- La música **Automática** es generada por el programa → **imposible** que tenga
  copyright (no usa ninguna grabación de nadie).
- Si subes tu propia música, usa la **Biblioteca de audio de YouTube** o música
  **CC0 / dominio público** para no tener problemas.
- Si eliges **Sin música**, el video sale solo con la voz (100% sin problemas).

