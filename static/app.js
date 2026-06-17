// ViroFeed AI Personal - logica de la interfaz (flujo en 2 pasos)

const $ = (id) => document.getElementById(id);

const formCard = $("form-card");
const progressCard = $("progress-card");
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
const attempts = {};          // cuenta de regeneraciones por escena

function show(card) {
  [formCard, progressCard, reviewCard, resultCard, errorCard].forEach((c) => c.classList.add("hidden"));
  card.classList.remove("hidden");
}

function setProgress(pct, msg) {
  progressFill.style.width = (pct || 0) + "%";
  if (msg) progressMsg.textContent = msg;
}

// ----------------------------------------------------------------------
//  PASO 1: preparar
// ----------------------------------------------------------------------
async function startPrepare() {
  const url = $("url").value.trim();
  if (!url) {
    alert("Pega la URL de una noticia primero.");
    return;
  }

  imageSourceChosen = $("image_source").value;
  const payload = {
    url,
    duration: $("duration").value,
    style: $("style").value,
    voice: $("voice").value,
    subtitle_color: $("subtitle_color").value,
    subtitle_position: $("subtitle_position").value,
    image_source: imageSourceChosen,
    cta: $("cta").value,
    use_avatar: $("use_avatar").checked,
  };

  generateBtn.disabled = true;
  progressTitle.textContent = "Preparando tu video...";
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
//  Pantalla de revision de imagenes
// ----------------------------------------------------------------------
function imgUrl(file) {
  return `/preview/${currentJob}/${encodeURIComponent(file)}?t=${Date.now()}`;
}

function renderReview(review) {
  generateBtn.disabled = false;
  const grid = $("scenes-grid");
  grid.innerHTML = "";

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
      <p class="scene-text">${scene.index + 1}. ${escapeHtml(scene.text)}</p>
      <textarea class="scene-prompt" id="prompt-${scene.index}" rows="2"
        title="Descripcion de la imagen (puedes editarla)">${escapeHtml(scene.image_prompt)}</textarea>
      <div class="scene-actions">
        <button class="btn-mini" data-act="ai" data-i="${scene.index}">🎨 Regenerar IA</button>
        <button class="btn-mini" data-act="stock" data-i="${scene.index}">🔁 Foto real</button>
        <button class="btn-mini" data-act="upload" data-i="${scene.index}">⬆️ Subir</button>
      </div>
      <input type="file" accept="image/*" class="hidden" id="file-${scene.index}">
    `;
    grid.appendChild(card);
  });

  // Conectar botones
  grid.querySelectorAll(".btn-mini").forEach((btn) => {
    const i = parseInt(btn.dataset.i, 10);
    const act = btn.dataset.act;
    if (act === "ai" || act === "stock") {
      btn.addEventListener("click", () => regenerate(i, act));
    } else if (act === "upload") {
      btn.addEventListener("click", () => $(`file-${i}`).click());
    }
  });
  grid.querySelectorAll('input[type="file"]').forEach((inp) => {
    const i = parseInt(inp.id.split("-")[1], 10);
    inp.addEventListener("change", () => uploadImage(i, inp.files[0]));
  });

  show(reviewCard);
}

function setSceneLoading(i, on) {
  $(`loading-${i}`).classList.toggle("hidden", !on);
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
    if (!resp.ok) { alert(data.error || "No se pudo regenerar la imagen"); return; }
    $(`img-${i}`).src = imgUrl(data.image_file);
    $(`badge-${i}`).textContent = data.source;
  } catch (e) {
    alert("Error al regenerar: " + e);
  } finally {
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
    if (!resp.ok) { alert(data.error || "No se pudo subir la imagen"); return; }
    $(`img-${i}`).src = imgUrl(data.image_file);
    $(`badge-${i}`).textContent = data.source;
  } catch (e) {
    alert("Error al subir: " + e);
  } finally {
    setSceneLoading(i, false);
  }
}

// ----------------------------------------------------------------------
//  PASO 2: ensamblar el video final
// ----------------------------------------------------------------------
async function startAssemble() {
  progressTitle.textContent = "Generando el video final...";
  show(progressCard);
  setProgress(5, "Preparando ensamblaje...");
  try {
    const resp = await fetch("/api/assemble", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: currentJob }),
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

// ----------------------------------------------------------------------
//  Eventos
// ----------------------------------------------------------------------
generateBtn.addEventListener("click", startPrepare);
assembleBtn.addEventListener("click", startAssemble);
$("cancel-review-btn").addEventListener("click", () => show(formCard));
$("new-btn").addEventListener("click", () => show(formCard));
$("retry-btn").addEventListener("click", () => show(formCard));
