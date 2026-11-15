"use strict";

const byId = (id) => document.getElementById(id);
const result = byId("result");
const probe = byId("probe");
let modelAvailable = false;

async function refresh() {
  probe.disabled = true;
  try {
    const response = await fetch("/_diagnostics/state");
    if (!response.ok) throw new Error();
    const state = await response.json();
    byId("provider").textContent = state.provider;
    byId("model").textContent = state.model;
    byId("key").textContent = state.keyConfigured ? "Configurée" : "À configurer";
    byId("harness").textContent = state.harnessReady ? "Prêt" : "Démarrage en cours";
    byId("proxy").textContent = state.proxyReady ? "Prêt" : "Démarrage en cours";
    byId("setup").hidden = state.keyConfigured;
    modelAvailable = state.keyConfigured && state.proxyReady && state.harnessReady;
    probe.disabled = !modelAvailable;
    result.textContent = "";
  } catch {
    modelAvailable = false;
    result.textContent = "Diagnostic indisponible. Attends le démarrage du serveur, puis actualise.";
  }
}

async function runCheck(button, path) {
  button.disabled = true;
  result.textContent = "Vérification en cours…";
  try {
    const response = await fetch("/_diagnostics/" + path, {method: "POST"});
    const report = await response.json();
    result.textContent = report.message;
  } catch {
    result.textContent = "Le serveur n’a pas pu terminer la vérification. Réessaie.";
  } finally {
    button.disabled = button === probe && !modelAvailable;
  }
}

byId("refresh").addEventListener("click", refresh);
byId("workspace").addEventListener("click", (event) => runCheck(event.currentTarget, "workspace"));
probe.addEventListener("click", () => runCheck(probe, "model"));
refresh();
