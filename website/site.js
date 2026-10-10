(() => {
  const config = window.PINOVA_CONFIG || {};
  const repo = (config.githubRepository || "").trim();
  const version = (config.version || "v5.1.0").trim();
  const validRepo = repo && !repo.includes("YOUR-GITHUB-USERNAME") && /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repo);
  document.querySelectorAll("[data-version]").forEach(el => el.textContent = version);
  const customBase = (config.downloadBaseUrl || "").trim();
  let latestBase = "";
  if (customBase) {
    const baseUrl = new URL(customBase, window.location.href).href;
    latestBase = baseUrl.endsWith("/") ? baseUrl : baseUrl + "/";
  } else if (validRepo) {
    latestBase = `https://github.com/${repo}/releases/latest/download/`;
  }
  document.querySelectorAll("[data-asset]").forEach(link => {
    const asset = link.getAttribute("data-asset");
    if (latestBase) {
      link.href = latestBase + encodeURIComponent(asset).replace(/%2F/g, "/");
      link.setAttribute("aria-label", `Download ${asset}`);
    } else {
      link.href = "#download";
      link.addEventListener("click", event => {
        event.preventDefault();
        alert("Download links will activate after you set website/site-config.js to your GitHub repository and publish a release tag.");
      });
    }
  });
  document.querySelectorAll("[data-repo-link]").forEach(link => {
    if (validRepo) link.href = `https://github.com/${repo}/releases`;
    else if (customBase) link.href = new URL(customBase, window.location.href).href;
    else link.href = "https://github.com/";
  });
  const year = document.getElementById("year");
  if (year) year.textContent = new Date().getFullYear();
})();
