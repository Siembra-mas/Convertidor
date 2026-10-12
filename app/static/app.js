const MAX_FILE_BYTES = 15 * 1024 * 1024;
const MAX_BATCH_BYTES = 512 * 1024 * 1024;
const MAX_BATCH_FILES = 500;

const fileInput = document.querySelector("#file-input");
const folderInput = document.querySelector("#folder-input");
const dropzone = document.querySelector("#dropzone");
const fileCard = document.querySelector("#file-card");
const fileName = document.querySelector("#file-name");
const fileSize = document.querySelector("#file-size");
const status = document.querySelector("#status");
const convertButton = document.querySelector("#convert");
const removeButton = document.querySelector("#remove-file");
const folderButton = document.querySelector("#choose-folder");
const progress = document.querySelector("#progress");
const download = document.querySelector("#download");
let selectedFiles = [];
let resultUrl = null;

function formatSize(bytes) {
  return bytes < 1024 * 1024
    ? `${(bytes / 1024).toFixed(0)} KB`
    : `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function clearResult() {
  if (resultUrl) URL.revokeObjectURL(resultUrl);
  resultUrl = null;
  download.removeAttribute("href");
  download.classList.remove("visible");
}

function setStatus(message, kind = "") {
  status.textContent = message;
  status.className = `status ${kind}`.trim();
}

async function chooseFiles(fileList) {
  clearResult();
  setStatus("");
  selectedFiles = [];
  const candidates = Array.from(fileList || []);
  fileCard.classList.remove("visible");
  convertButton.disabled = true;
  if (!candidates.length) return;
  if (candidates.length > MAX_BATCH_FILES) {
    fileInput.value = "";
    folderInput.value = "";
    setStatus(`Selecciona como máximo ${MAX_BATCH_FILES} archivos por lote.`, "error");
    return;
  }

  setStatus("Revisando archivos DICOM…");
  const checked = await Promise.all(candidates.map(async (file) => {
    if (file.size < 132) return null;
    const marker = new Uint8Array(await file.slice(128, 132).arrayBuffer());
    return marker[0] === 68 && marker[1] === 73 && marker[2] === 67 && marker[3] === 77
      ? file
      : null;
  }));
  const dicomFiles = checked.filter(Boolean);
  if (!dicomFiles.length) {
    fileInput.value = "";
    folderInput.value = "";
    setStatus("No se encontraron archivos con encabezado DICOM válido.", "error");
    return;
  }
  if (dicomFiles.some((file) => file.size > MAX_FILE_BYTES)) {
    fileInput.value = "";
    folderInput.value = "";
    setStatus("Cada archivo debe ocupar como máximo 15 MB.", "error");
    return;
  }
  const totalBytes = dicomFiles.reduce((total, file) => total + file.size, 0);
  if (totalBytes > MAX_BATCH_BYTES) {
    fileInput.value = "";
    folderInput.value = "";
    setStatus("El lote supera el límite total de 512 MB.", "error");
    return;
  }

  selectedFiles = dicomFiles;
  fileName.textContent = `${dicomFiles.length} ${dicomFiles.length === 1 ? "archivo" : "archivos"} seleccionados`;
  fileSize.textContent = `${formatSize(totalBytes)} en total`;
  fileCard.classList.add("visible");
  convertButton.disabled = false;
  setStatus(checked.length > dicomFiles.length
    ? `Se ignoraron ${checked.length - dicomFiles.length} archivos que no son DICOM.`
    : "");
}

fileInput.addEventListener("change", () => chooseFiles(fileInput.files));
folderInput.addEventListener("change", () => chooseFiles(folderInput.files));
folderButton.addEventListener("click", () => folderInput.click());
["dragenter", "dragover"].forEach((eventName) => {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.add("is-dragging");
  });
});
["dragleave", "drop"].forEach((eventName) => {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.remove("is-dragging");
  });
});
dropzone.addEventListener("drop", (event) => chooseFiles(event.dataTransfer.files));
removeButton.addEventListener("click", () => {
  selectedFiles = [];
  fileInput.value = "";
  folderInput.value = "";
  fileCard.classList.remove("visible");
  convertButton.disabled = true;
  clearResult();
  setStatus("");
});

convertButton.addEventListener("click", async () => {
  if (!selectedFiles.length) return;
  const formData = new FormData();
  selectedFiles.forEach((file) => formData.append("files", file));
  convertButton.disabled = true;
  progress.classList.add("visible");
  setStatus(`Convirtiendo ${selectedFiles.length} imágenes en secuencia…`);
  clearResult();
  try {
    const response = await fetch("/api/v1/convert/batch", { method: "POST", body: formData });
    if (!response.ok) {
      let message = "No se pudo convertir el lote.";
      try {
        const payload = await response.json();
        if (typeof payload.detail === "string") message = payload.detail;
      } catch {
        // Keep the generic message if the response is not JSON.
      }
      throw new Error(message);
    }
    const zip = await response.blob();
    if (!zip.type.includes("application/zip")) throw new Error("La respuesta no contiene un ZIP válido.");
    resultUrl = URL.createObjectURL(zip);
    download.href = resultUrl;
    download.classList.add("visible");
    setStatus("Conversión completada. El ZIP con imágenes PNG está listo para descargar.", "success");
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "Error de conexión al convertir el lote.", "error");
  } finally {
    progress.classList.remove("visible");
    convertButton.disabled = !selectedFiles.length;
  }
});
