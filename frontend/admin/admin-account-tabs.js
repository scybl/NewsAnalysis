const accountTabs = Array.from(document.querySelectorAll("[data-account-tab]"));
const accountPanes = Array.from(document.querySelectorAll("[data-account-pane]"));

document.addEventListener("DOMContentLoaded", () => {
  accountTabs.forEach((button) => {
    button.addEventListener("click", () => activateAccountPane(button.dataset.accountTab || "accounts", true));
  });
  const initial = (window.location.hash || "#accounts").replace(/^#/, "") || "accounts";
  activateAccountPane(initial, false);
});

window.addEventListener("hashchange", () => {
  activateAccountPane((window.location.hash || "#accounts").replace(/^#/, "") || "accounts", false);
});

function activateAccountPane(name, updateHash) {
  const normalized = new Set(["accounts", "archives", "credentials"]).has(name) ? name : "accounts";
  accountTabs.forEach((button) => {
    button.classList.toggle("active", button.dataset.accountTab === normalized);
  });
  accountPanes.forEach((pane) => {
    pane.classList.toggle("active", pane.dataset.accountPane === normalized);
  });
  if (updateHash && window.location.hash !== `#${normalized}`) {
    history.replaceState(null, "", `#${normalized}`);
  }
}
