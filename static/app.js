// ViroFeed AI Personal - logica de la interfaz

const $ = (id) => document.getElementById(id);

const formCard = $("form-card");
const progressCard = $("progress-card");
const resultCard = $("result-card");
const errorCard = $("error-card");

const generateBtn = $("generate-btn");
const progressFill = $("progress-fill");
const progressMsg = $("progress-msg");

let pollTimer = null;

function show(card) {
  [formCard, progressCard, resultCard, errorCard].forEach((c) => c.classList.add("hidden"));
  card.classList.remove("hidden");
}

async function startGeneration() {
  const url = $("url").value.trim();
  if (!url) {
    alert("Pega la URL de una noticia primero.");
    return;
  }

  const payload = {
    url,
    duration: $("duration").value,
    style: $("style").value,
    voice: $("voice").value,
    subtitle_color: $("subtitle_color").value,
    subtitle_position: $("subtitle_position").value,
    image_source: $("image_source").value,
    cta: $("cta").value,
    use_avatar: $("use_avatar").checked,
  };

  generateBtn.disabled = true;
  show(progressCard);
  setProgress(3, "Iniciando...");

  try {
    const resp = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok) {
      showError(data.error || "Error desconocido");
      return;
    }
    pollStatus(data.job_id);
  } catch (e) {
    showError("No pude contactar al programa. ¿Sigue abierta la ventana negra?\n" + e);
  }
}

function setProgress(pct, msg) {
  progressFill.style.width = pct + "%";
  if (msg) progressMsg.textContent = msg;
}

function pollStatus(jobId) {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const resp = await fetch(`/api/status/${jobId}`);
      const job = await resp.json();
      setProgress(job.percent || 0, job.message || "");

      if (job.status === "done") {
        clearInterval(pollTimer);
        showResult(job.result);
      } else if (job.status === "error") {
        clearInterval(pollTimer);
        showError(job.error || "Error durante la generacion");
      }
    } catch (e) {
      clearInterval(pollTimer);
      showError("Se perdio la conexion con el programa.\n" + e);
    }
  }, 1500);
}

function showResult(result) {
  generateBtn.disabled = false;
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

generateBtn.addEventListener("click", startGeneration);
$("new-btn").addEventListener("click", () => { show(formCard); });
$("retry-btn").addEventListener("click", () => { show(formCard); });
