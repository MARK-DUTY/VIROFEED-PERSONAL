# 📌 ESTADO DEL PROYECTO — ViroFeed AI Personal

> **Para retomar en una sesión nueva de Kiro:** pega este archivo o pídele a Kiro
> que lo lea. Resume todo el proyecto y dónde vamos.

---

## 🎯 Objetivo
Crear un programa de escritorio (corre en Windows) que convierta la **URL de una
noticia** en un **video corto viral** en español (Reels / TikTok / Shorts),
automáticamente. Es una versión propia y barata de la herramienta de pago
**ViroFeed AI**.

## 👤 Contexto del usuario
- **No tiene experiencia en código** → todo se entrega con instaladores `.bat` y
  guía tipo receta de cocina.
- **Presupuesto mínimo** → proyecto de prueba, prioridad costo **$0**. Si funciona,
  invertirá más (Fase 2 / Fase 3).
- **PC:** Windows, Intel i5-6500, 16 GB RAM, **gráficos integrados Intel HD 530
  (SIN GPU NVIDIA)** → por eso el avatar con lip-sync se hace en la **nube**, no local.
- Idioma de los videos: **español (voces es-MX por defecto)**.

## 🛠️ Arquitectura (decidida y construida)
| Paso | Herramienta | Costo |
|---|---|---|
| Leer la noticia (URL) | trafilatura (local) | Gratis |
| Generar guión viral | **Groq** (Llama 3.3) API | Gratis |
| Voz en español | **Edge TTS** (Microsoft) | Gratis ∞ |
| Imágenes de fondo | **Pexels** + Pixabay | Gratis |
| Subtítulos sincronizados | generados con tiempos de Edge TTS (.ass) | Gratis |
| Avatar hablando (OPCIONAL) | **D-ID** (nube) — interruptor ON/OFF | Gratis con límite |
| Ensamblar video | **FFmpeg** (local, sin GPU) | Gratis |

**Modo por defecto = FACELESS (sin cara): $0 e ilimitado.** El avatar es un
interruptor activable (`AVATAR_ENABLED=true`).

## 🧱 Estructura del código
```
virofeed-personal/
├─ app.py                  # servidor web local (Flask) - la interfaz
├─ pipeline/
│  ├─ config.py            # lee el .env (claves y ajustes)
│  ├─ article.py           # paso 1: extraer texto de la URL
│  ├─ script_gen.py        # paso 2: guión viral con Groq
│  ├─ voice.py             # paso 3: voz + tiempos por palabra (Edge TTS)
│  ├─ images.py            # paso 4: descargar imágenes (Pexels/Pixabay)
│  ├─ subtitles.py         # paso 5: subtítulos .ass sincronizados
│  ├─ avatar.py            # paso opcional: avatar D-ID (nube)
│  ├─ assemble.py          # paso 6: ensamblar video con FFmpeg
│  └─ runner.py            # orquestador de todo el flujo
├─ templates/index.html    # página web
├─ static/                 # estilos y lógica del navegador
├─ setup_windows.bat       # instalador (1 sola vez)
├─ run_windows.bat         # arranca el programa
├─ config.example.env      # plantilla de configuración
├─ requirements.txt        # dependencias de Python
└─ GUIA_DE_USO.md          # manual paso a paso
```

## ✅ Hecho
- [x] Programa completo construido (faceless + interruptor de avatar).
- [x] Código verificado sin errores de sintaxis.
- [x] Instaladores y guía para Windows.
- [x] Subido a GitHub: github.com/MARK-DUTY/VIROFEED-PERSONAL
- [x] Instalado en el Windows del usuario (Python 3.14) y FUNCIONANDO.
- [x] Claves de Groq y Pexels configuradas en .env. La interfaz web abre OK.

## ⏳ Pendiente (siguiente paso)
- [ ] Generar el primer video de prueba real y revisar calidad (guion, voz,
      imagenes, subtitulos, ritmo).
- [ ] Ajustar a gusto: estilo de subtitulos, duracion, tono del guion.
- [ ] (Opcional) Activar avatar D-ID si lo quiere.
- [ ] Definir nicho/tema para la serie de videos.

## 🗺️ Fases del plan general
- **Fase 1 (actual):** programa local gratis → $0/mes.
- **Fase 2:** semi-automatizado → ~$14/mes.
- **Fase 3:** software propio completo → ~$40/mes.
