const governanceTabs = Array.from(document.querySelectorAll("[data-governance-tab]"));
const governancePanes = Array.from(document.querySelectorAll("[data-governance-pane]"));

document.addEventListener("DOMContentLoaded", () => {
  governanceTabs.forEach((button) => {
    button.addEventListener("click", () => activateGovernancePane(button.dataset.governanceTab || "ops", true));
  });
  const initial = (window.location.hash || "#ops").replace(/^#/, "") || "ops";
  activateGovernancePane(initial, false);
});

window.addEventListener("hashchange", () => {
  activateGovernancePane((window.location.hash || "#ops").replace(/^#/, "") || "ops", false);
});

function activateGovernancePane(name, updateHash) {
  const normalized = new Set(["ops", "data-audit", "audit-log"]).has(name) ? name : "ops";
  governanceTabs.forEach((button) => {
    button.classList.toggle("active", button.dataset.governanceTab === normalized);
  });
  governancePanes.forEach((pane) => {
    pane.classList.toggle("active", pane.dataset.governancePane === normalized);
  });
  if (updateHash && window.location.hash !== `#${normalized}`) {
    history.replaceState(null, "", `#${normalized}`);
  }
}
