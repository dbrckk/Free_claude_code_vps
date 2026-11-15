"use strict";

const byId = (id) => document.getElementById(id);
const probe = byId("probe");
const workspace = byId("workspace");
const refreshButton = byId("refresh");
let modelAvailable = false;
let modelChecking = false;
let refreshTimer;
let refreshDelay = 3000;
let refreshDeadline = Date.now() + 120000;

function retryRefresh() {
  if (Date.now() >= refreshDeadline) {
    byId("connection").textContent = "Le serveur tarde à répondre. Clique sur Actualiser pour vérifier de nouveau.";
    return;
  }
  refreshTimer = setTimeout(refresh, refreshDelay);
  refreshDelay = Math.min(refreshDelay * 2, 15000);
}

async function refresh() {
  clearTimeout(refreshTimer);
  refreshButton.disabled = true;
  try {
    const response = await fetch("/_diagnostics/state", {signal: AbortSignal.timeout(12000)});
    if (!response.ok) throw new Error();
    const state = await response.json();
    byId("provider").textContent = state.provider;
    byId("model").textContent = state.model;
    byId("key").textContent = state.keyConfigured ? "Configurée" : "À configurer";
    byId("harness").textContent = state.harnessReady ? "Prêt" : "Démarrage en cours";
    byId("proxy").textContent = state.proxyReady ? "Prêt" : "Démarrage en cours";

    byId("provider-link").href = state.providerSetupUrl;
    if (state.renderEnvironmentUrl) byId("render-link").href = state.renderEnvironmentUrl;
    byId("render-key").textContent = state.keyName;
    byId("vps-key").textContent = state.keyName;
    byId("render-help").hidden = !state.renderEnvironmentUrl;
    byId("vps-help").hidden = Boolean(state.renderEnvironmentUrl);
    byId("setup").hidden = state.keyConfigured;
    byId("open").hidden = !state.harnessReady;
    workspace.disabled = workspace.getAttribute("aria-busy") === "true";

    const ready = state.proxyReady && state.harnessReady;
    modelAvailable = state.keyConfigured && ready;
    byId("connection").textContent = ready ? "" : "Le serveur démarre. Cette page se met à jour automatiquement.";
    if (!ready) retryRefresh();
  } catch {
    modelAvailable = false;
    byId("open").hidden = true;
    byId("connection").textContent = "Connexion momentanément indisponible. Nouvelle tentative en cours.";
    retryRefresh();
  } finally {
    probe.disabled = modelChecking || !modelAvailable;
    refreshButton.disabled = false;
  }
}

async function runCheck(button, path, result) {
  if (button === probe) modelChecking = true;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  result.textContent = "Vérification en cours…";
  try {
    const response = await fetch("/_diagnostics/" + path, {
      method: "POST",
      signal: AbortSignal.timeout(30000),
    });
    const report = await response.json();
    result.textContent = report.message;
  } catch {
    result.textContent = "Le serveur n’a pas pu terminer la vérification. Réessaie.";
  } finally {
    button.removeAttribute("aria-busy");
    if (button === probe) modelChecking = false;
    button.disabled = button === probe && !modelAvailable;
  }
}

refreshButton.addEventListener("click", () => {
  refreshDelay = 3000;
  refreshDeadline = Date.now() + 120000;
  refresh();
});
workspace.addEventListener("click", () => runCheck(workspace, "workspace", byId("workspace-result")));
probe.addEventListener("click", () => runCheck(probe, "model", byId("model-result")));
refresh();
