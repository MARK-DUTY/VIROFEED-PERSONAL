// ViroFeed AI Personal - logica de la interfaz (flujo en 2 pasos)

const $ = (id) => document.getElementById(id);

const formCard = $("form-card");
const progressCard = $("progress-card");
const draftCard = $("draft-card");
const reviewCard = $("review-card");
const resultCard = $("result-card");
const errorCard = $("error-card");

const generateBtn = $("generate-btn");
const assembleBtn = $("assemble-btn");
const progressFill = $("progress-fill");
const progressMsg = $("progress-msg");
const progressTitle = $("progress-title");

let pollTimer = null;
let currentJob = null;       // job_id actual
let imageSourceChosen = "hybrid";
let activeTab = "url";        // "url" | "story"
const attempts = {};          // cuenta de regeneraciones por escena

function show(card) {
  [formCard, progressCard, draftCard, reviewCard, resultCard, errorCard].forEach((c) => c.classList.add("hidden"));
  card.classList.remove("hidden");
}

// ----------------------------------------------------------------------
//  Pestanas: Noticia (URL) / Mi historia
// ----------------------------------------------------------------------
function switchTab(tab) {
  activeTab = tab;
  $("tab-btn-url").classList.toggle("active", tab === "url");
  $("tab-btn-story").classList.toggle("active", tab === "story");
  $("tab-btn-youtube").classList.toggle("active", tab === "youtube");
  $("tab-url").classList.toggle("hidden", tab !== "url");
  $("tab-story").classList.toggle("hidden", tab !== "story");
  $("tab-youtube").classList.toggle("hidden", tab !== "youtube");
  // El estilo de guion aplica a Noticia y a YouTube (no al modo Historia)
  $("style-field").style.display = tab === "story" ? "none" : "";
  // El boton cambia segun el modo
  generateBtn.textContent = tab === "story" ? "✍️ Generar guion y prompts" : "🎬 Preparar video";
}

function setProgress(pct, msg) {
  progressFill.style.width = (pct || 0) + "%";
  if (msg) progressMsg.textContent = msg;
}

// Opciones compartidas (duracion, voz, subtitulos, etc.) para ambos modos
function sharedOptions() {
  imageSourceChosen = $("image_source").value;
  return {
    duration: $("duration").value,
    n_images: $("n_images") ? $("n_images").value : "auto",
    aspect: $("aspect") ? $("aspect").value : "9:16",
    style: $("style").value,
    voice: $("voice").value,
    subtitle_color: $("subtitle_color").value,
    subtitle_position: $("subtitle_position").value,
    image_source: imageSourceChosen,
    cta: $("cta").value,
    use_avatar: $("use_avatar").checked,
  };
}

// Muestra un aviso cuando el usuario elige un video largo (2 min o mas),
// porque en su PC (sin tarjeta grafica) tardara varios minutos en armarse.
function refreshLongVideoWarning() {
  const warn = $("long-video-warning");
  if (!warn) return;
  const secs = parseInt($("duration").value, 10) || 0;
  warn.classList.toggle("hidden", secs < 120);
}

// El boton principal decide segun la pestana activa
function onGenerate() {
  if (activeTab === "story") {
    startDraft();
  } else if (activeTab === "youtube") {
    startYoutube();
  } else {
    startPrepare();
  }
}

// Convierte el texto de un campo (con un enlace por renglon) en una lista limpia
function parseLinks(value) {
  return (value || "")
    .split(/[\r\n]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

// ----------------------------------------------------------------------
//  PASO 1 (URL): preparar
// ----------------------------------------------------------------------
async function startPrepare() {
  const urls = parseLinks($("url").value);
  if (urls.length === 0) {
    alert("Pega la URL de una noticia primero.");
    return;
  }

  const payload = { urls, url: urls.join("\n"), ...sharedOptions() };

  generateBtn.disabled = true;
  progressTitle.textContent = urls.length > 1 ? "Leyendo las noticias..." : "Preparando tu video...";
  show(progressCard);
  setProgress(3, "Iniciando...");

  try {
    const resp = await fetch("/api/prepare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok) { showError(data.error || "Error desconocido"); return; }
    currentJob = data.job_id;
    pollStatus();
  } catch (e) {
    showError("No pude contactar al programa. ¿Sigue abierta la ventana negra?\n" + e);
  }
}

// ----------------------------------------------------------------------
//  PASO 1 (YOUTUBE): preparar desde un link de video de YouTube
// ----------------------------------------------------------------------
async function startYoutube() {
  const urls = parseLinks($("youtube_url").value);
  if (urls.length === 0) {
    alert("Pega el enlace de un video de YouTube primero.");
    return;
  }

  const payload = { urls, url: urls.join("\n"), ...sharedOptions() };

  generateBtn.disabled = true;
  progressTitle.textContent = urls.length > 1 ? "Leyendo los videos de YouTube..." : "Leyendo el video de YouTube...";
  show(progressCard);
  setProgress(3, "Iniciando...");

  try {
    const resp = await fetch("/api/prepare_youtube", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok) { showError(data.error || "Error desconocido"); return; }
    currentJob = data.job_id;
    pollStatus();
  } catch (e) {
    showError("No pude contactar al programa. ¿Sigue abierta la ventana negra?\n" + e);
  }
}
async function startDraft() {
  const story = $("story").value.trim();
  if (story.length < 30) {
    alert("Escribe tu historia con un poco mas de detalle (al menos unas frases).");
    return;
  }

  const payload = {
    story,
    ...sharedOptions(),
  };

  generateBtn.disabled = true;
  progressTitle.textContent = "Escribiendo el guion y los prompts...";
  show(progressCard);
  setProgress(5, "Iniciando...");

  try {
    const resp = await fetch("/api/draft_story", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok) { showError(data.error || "Error desconocido"); return; }
    currentJob = data.job_id;
    pollStatus();
  } catch (e) {
    showError("No pude contactar al programa. ¿Sigue abierta la ventana negra?\n" + e);
  }
}

// ----------------------------------------------------------------------
//  Sondeo de estado (sirve para preparar y para ensamblar)
// ----------------------------------------------------------------------
function pollStatus() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const resp = await fetch(`/api/status/${currentJob}`);
      const job = await resp.json();
      setProgress(job.percent, job.message);

      if (job.status === "error") {
        clearInterval(pollTimer);
        showError(job.error || "Error durante el proceso");
        return;
      }
      if (job.phase === "draft" && job.status === "draft_ready") {
        clearInterval(pollTimer);
        renderDraft(job.draft);
        return;
      }
      if (job.phase === "review" && job.status === "ready") {
        clearInterval(pollTimer);
        renderReview(job.review);
        return;
      }
      if (job.phase === "done" && job.status === "done") {
        clearInterval(pollTimer);
        showResult(job.result);
        return;
      }
    } catch (e) {
      clearInterval(pollTimer);
      showError("Se perdio la conexion con el programa.\n" + e);
    }
  }, 1500);
}

// ----------------------------------------------------------------------
//  MODO HISTORIA - Pantalla de borrador (guion + prompts editables)
// ----------------------------------------------------------------------
function renderDraft(draft) {
  generateBtn.disabled = false;
  showWarning("draft-warning", draft.warning);
  const grid = $("draft-grid");
  grid.innerHTML = "";

  draft.scenes.forEach((scene) => {
    const card = document.createElement("div");
    card.className = "draft-scene";
    card.innerHTML = `
      <div class="draft-head">
        <span class="draft-num">Escena ${scene.index + 1}</span>
        <span class="scene-saved hidden" id="dsaved-${scene.index}">✔ Guardado</span>
      </div>
      <label class="scene-label">🎬 Diálogo (lo que se narra)</label>
      <textarea class="scene-dialogue" id="dtext-${scene.index}" rows="2">${escapeHtml(scene.text)}</textarea>
      <label class="scene-label">🖼️ Prompt de la imagen (en inglés)</label>
      <textarea class="scene-prompt" id="dprompt-${scene.index}" rows="3" spellcheck="false">${escapeHtml(scene.image_prompt)}</textarea>
    `;
    grid.appendChild(card);
  });

  // Guardar automaticamente cuando el usuario termina de editar
  grid.querySelectorAll(".scene-dialogue, .scene-prompt").forEach((ta) => {
    const i = parseInt(ta.id.split("-")[1], 10);
    ta.addEventListener("change", () => saveDraftScene(i));
  });

  show(draftCard);
}

async function saveDraftScene(i) {
  const text = $(`dtext-${i}`).value.trim();
  const prompt = $(`dprompt-${i}`).value.trim();
  if (!prompt) { alert("La descripción de la imagen no puede quedar vacía."); return; }
  try {
    const resp = await fetch("/api/update_prompt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: currentJob, index: i, prompt, text }),
    });
    const data = await resp.json();
    if (!resp.ok) { alert(data.error || "No se pudo guardar"); return; }
    const saved = $(`dsaved-${i}`);
    if (saved) {
      saved.classList.remove("hidden");
      setTimeout(() => saved.classList.add("hidden"), 1500);
    }
  } catch (e) {
    alert("Error al guardar: " + e);
  }
}

// Aprobar el borrador -> generar voz + imagenes
async function generateFromDraft() {
  progressTitle.textContent = "Generando voz e imágenes...";
  show(progressCard);
  setProgress(5, "Iniciando...");
  try {
    const resp = await fetch("/api/generate_from_draft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: currentJob }),
    });
    const data = await resp.json();
    if (!resp.ok) { showError(data.error || "Error al generar"); return; }
    pollStatus();
  } catch (e) {
    showError("No pude contactar al programa.\n" + e);
  }
}

// ----------------------------------------------------------------------
//  Pantalla de revision de imagenes
// ----------------------------------------------------------------------
function imgUrl(file) {
  return `/preview/${currentJob}/${encodeURIComponent(file)}?t=${Date.now()}`;
}

function renderReview(review) {
  generateBtn.disabled = false;
  showWarning("review-warning", review.warning);
  const grid = $("scenes-grid");
  grid.innerHTML = "";

  // Inicializar los controles de voz y avatar segun el estado actual del trabajo
  if ($("review-avatar")) $("review-avatar").checked = !!review.use_avatar;
  if ($("review-voice")) $("review-voice").value = "";  // por defecto: mantener la voz actual

  review.scenes.forEach((scene) => {
    const card = document.createElement("div");
    card.className = "scene-card";
    card.id = `scene-${scene.index}`;

    card.innerHTML = `
      <div class="scene-img-wrap">
        <img class="scene-img" id="img-${scene.index}" src="${imgUrl(scene.image_file)}" alt="escena ${scene.index + 1}">
        <span class="scene-badge" id="badge-${scene.index}">${scene.source}</span>
        <div class="scene-loading hidden" id="loading-${scene.index}">Generando...</div>
      </div>
      <label class="scene-label">🎬 Escena ${scene.index + 1} · Diálogo (lo que se narra)</label>
      <textarea class="scene-dialogue" id="dialogue-${scene.index}" rows="3"
        title="Edita lo que se dice en esta escena">${escapeHtml(scene.text)}</textarea>
      <span class="scene-saved hidden" id="saved-${scene.index}">✔ Guardado</span>
      <label class="scene-label">🖼️ Descripción de la imagen (en inglés)</label>
      <textarea class="scene-prompt" id="prompt-${scene.index}" rows="2" spellcheck="false"
        title="Describe la imagen que quieres (en inglés). Luego pulsa 'Crear con mi texto (IA)'.">${escapeHtml(scene.image_prompt)}</textarea>
      <div class="scene-actions">
        <button class="btn-mini btn-ai" data-act="ai" data-i="${scene.index}">🎨 Crear con mi texto (IA)</button>
        <button class="btn-mini" data-act="stock" data-i="${scene.index}">🔁 Otra foto real</button>
        <button class="btn-mini" data-act="upload" data-i="${scene.index}">⬆️ Subir</button>
        <button class="btn-mini btn-danger" data-act="delete" data-i="${scene.index}">🗑️ Eliminar</button>
      </div>
      <input type="file" accept="image/*" class="hidden" id="file-${scene.index}">
    `;
    grid.appendChild(card);
  });

  // Conectar botones
  grid.querySelectorAll(".btn-mini").forEach((btn) => {
    const i = parseInt(btn.dataset.i, 10);
    const act = btn.dataset.act;
    if (act === "ai") {
      btn.addEventListener("click", () => regenerate(i, "ai"));
    } else if (act === "stock") {
      btn.addEventListener("click", () => regenerate(i, "stock"));
    } else if (act === "upload") {
      btn.addEventListener("click", () => $(`file-${i}`).click());
    } else if (act === "delete") {
      btn.addEventListener("click", () => deleteScene(i));
    }
  });
  // Guardar el dialogo automaticamente cuando el usuario termina de editar
  grid.querySelectorAll(".scene-dialogue").forEach((ta) => {
    const i = parseInt(ta.id.split("-")[1], 10);
    ta.addEventListener("change", () => saveDialogue(i));
  });
  grid.querySelectorAll('input[type="file"]').forEach((inp) => {
    const i = parseInt(inp.id.split("-")[1], 10);
    inp.addEventListener("change", () => uploadImage(i, inp.files[0]));
  });

  show(reviewCard);
}

// Guardar el dialogo editado de una escena
async function saveDialogue(i) {
  const text = $(`dialogue-${i}`).value.trim();
  if (!text) return;
  try {
    const resp = await fetch("/api/update_scene", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: currentJob, index: i, text }),
    });
    const data = await resp.json();
    if (!resp.ok) { alert(data.error || "No se pudo guardar el dialogo"); return; }
    const saved = $(`saved-${i}`);
    if (saved) {
      saved.classList.remove("hidden");
      setTimeout(() => saved.classList.add("hidden"), 1500);
    }
  } catch (e) {
    alert("Error al guardar el dialogo: " + e);
  }
}

// Eliminar una escena completa (imagen + dialogo)
async function deleteScene(i) {
  if (!confirm("¿Eliminar esta escena por completo (imagen y dialogo)?")) return;
  try {
    const resp = await fetch("/api/delete_scene", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: currentJob, index: i }),
    });
    const data = await resp.json();
    if (!resp.ok) { alert(data.error || "No se pudo eliminar la escena"); return; }
    // Re-dibujar la lista (los numeros de escena se reordenan)
    renderReview(data.review);
  } catch (e) {
    alert("Error al eliminar la escena: " + e);
  }
}

function setSceneLoading(i, on) {
  const loading = $(`loading-${i}`);
  if (loading) loading.classList.toggle("hidden", !on);
  const img = $(`img-${i}`);
  if (img) img.classList.toggle("is-loading", on);
  document.querySelectorAll(`#scene-${i} .btn-mini`).forEach((b) => (b.disabled = on));
}

async function regenerate(i, mode) {
  attempts[i] = (attempts[i] || 0) + 1;
  const prompt = $(`prompt-${i}`).value.trim();
  setSceneLoading(i, true);
  try {
    const resp = await fetch("/api/regenerate_image", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: currentJob, index: i, mode, prompt, attempt: attempts[i] }),
    });
    const data = await resp.json();
    if (!resp.ok) { alert(data.error || "No se pudo regenerar la imagen"); setSceneLoading(i, false); return; }
    // Dejamos el girito hasta que la NUEVA foto se vea (asi notas el cambio).
    const img = $(`img-${i}`);
    img.onload = () => setSceneLoading(i, false);
    img.onerror = () => setSceneLoading(i, false);
    img.src = imgUrl(data.image_file);
    $(`badge-${i}`).textContent = data.source;
  } catch (e) {
    alert("Error al regenerar: " + e);
    setSceneLoading(i, false);
  }
}

async function uploadImage(i, file) {
  if (!file) return;
  setSceneLoading(i, true);
  try {
    const fd = new FormData();
    fd.append("job_id", currentJob);
    fd.append("index", i);
    fd.append("image", file);
    const resp = await fetch("/api/upload_image", { method: "POST", body: fd });
    const data = await resp.json();
    if (!resp.ok) { alert(data.error || "No se pudo subir la imagen"); setSceneLoading(i, false); return; }
    const img = $(`img-${i}`);
    img.onload = () => setSceneLoading(i, false);
    img.onerror = () => setSceneLoading(i, false);
    img.src = imgUrl(data.image_file);
    $(`badge-${i}`).textContent = data.source;
  } catch (e) {
    alert("Error al subir: " + e);
    setSceneLoading(i, false);
  }
}

// ----------------------------------------------------------------------
//  Musica de fondo (3 opciones: automatica / propia / sin musica)
// ----------------------------------------------------------------------
function currentMusicMode() {
  const el = document.querySelector('input[name="music-mode"]:checked');
  return el ? el.value : "auto";
}

function setupMusicControls() {
  const fileInput = $("music-file");
  const vol = $("music-volume");
  const volLabel = $("music-vol-label");
  const status = $("music-status");
  const ownBox = $("music-own");
  const volBox = $("music-vol-box");

  function refresh() {
    const mode = currentMusicMode();
    ownBox.classList.toggle("hidden", mode !== "own");
    volBox.classList.toggle("hidden", mode === "off");
  }

  document.querySelectorAll('input[name="music-mode"]').forEach((r) => {
    r.addEventListener("change", refresh);
  });
  refresh();

  vol.addEventListener("input", () => { volLabel.textContent = vol.value + "%"; });

  fileInput.addEventListener("change", async () => {
    const file = fileInput.files[0];
    if (!file) return;
    status.textContent = "Subiendo música...";
    try {
      const fd = new FormData();
      fd.append("job_id", currentJob);
      fd.append("music", file);
      const resp = await fetch("/api/upload_music", { method: "POST", body: fd });
      const data = await resp.json();
      if (!resp.ok) { status.textContent = "❌ " + (data.error || "No se pudo subir"); return; }
      status.textContent = "✔ Música lista: " + data.music_file;
    } catch (e) {
      status.textContent = "❌ Error al subir la música.";
    }
  });
}

// ----------------------------------------------------------------------
//  PASO 2: ensamblar el video final
// ----------------------------------------------------------------------
async function startAssemble() {
  const mode = currentMusicMode();

  // Si eligio su propia musica pero no subio archivo, avisamos
  if (mode === "own") {
    const status = $("music-status").textContent || "";
    if (!status.startsWith("✔")) {
      if (!confirm("Elegiste 'Mi propia música' pero no veo un archivo subido. Si continúas, el programa pondrá música automática. ¿Seguir así?")) {
        return;
      }
    }
  }

  progressTitle.textContent = "Generando el video final...";
  show(progressCard);
  setProgress(5, "Preparando ensamblaje...");

  const payload = {
    job_id: currentJob,
    music_mode: mode,
    music_volume: parseInt($("music-volume").value, 10) / 100,
    voice: $("review-voice") ? $("review-voice").value : "",
    use_avatar: $("review-avatar") ? $("review-avatar").checked : false,
  };

  try {
    const resp = await fetch("/api/assemble", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok) { showError(data.error || "Error al ensamblar"); return; }
    pollStatus();
  } catch (e) {
    showError("No pude contactar al programa.\n" + e);
  }
}

// ----------------------------------------------------------------------
//  Resultado final
// ----------------------------------------------------------------------
function showResult(result) {
  const video = $("result-video");
  video.src = `/video/${encodeURIComponent(result.video_file)}`;
  $("download-link").href = `/download/${encodeURIComponent(result.video_file)}`;

  const titlesList = $("titles-list");
  titlesList.innerHTML = "";
  (result.titles || []).forEach((t) => {
    const li = document.createElement("li");
    li.textContent = t;
    titlesList.appendChild(li);
  });

  $("hashtags-text").textContent = (result.hashtags || []).map((h) => "#" + h).join("  ");
  $("narration-text").textContent = result.narration || "";
  show(resultCard);
}

function showError(msg) {
  generateBtn.disabled = false;
  $("error-msg").textContent = msg;
  show(errorCard);
}

function escapeHtml(s) {
  return (s || "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

// Muestra (u oculta) un aviso amarillo. Se usa para "necesito mas informacion"
// cuando el guion no alcanzo la duracion pedida por falta de material.
function showWarning(elId, msg) {
  const el = $(elId);
  if (!el) return;
  if (msg && msg.trim()) {
    el.textContent = msg;
    el.classList.remove("hidden");
  } else {
    el.textContent = "";
    el.classList.add("hidden");
  }
}

// ----------------------------------------------------------------------
//  Eventos
// ----------------------------------------------------------------------
$("tab-btn-url").addEventListener("click", () => switchTab("url"));
$("tab-btn-story").addEventListener("click", () => switchTab("story"));
$("tab-btn-youtube").addEventListener("click", () => switchTab("youtube"));

generateBtn.addEventListener("click", onGenerate);
assembleBtn.addEventListener("click", startAssemble);
$("generate-draft-btn").addEventListener("click", generateFromDraft);
$("redraft-btn").addEventListener("click", () => { switchTab("story"); show(formCard); });
$("cancel-review-btn").addEventListener("click", () => show(formCard));
$("new-btn").addEventListener("click", () => show(formCard));
$("retry-btn").addEventListener("click", () => show(formCard));

setupMusicControls();

// Aviso de video largo: revisar al cargar y cada vez que cambie la duracion
if ($("duration")) {
  $("duration").addEventListener("change", refreshLongVideoWarning);
  refreshLongVideoWarning();
}
