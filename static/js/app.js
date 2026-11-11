document.addEventListener("DOMContentLoaded", () => {
  const toggle = document.querySelector(".menu-toggle");
  const nav = document.querySelector(".nav-links");
  if (toggle && nav) toggle.addEventListener("click", () => nav.classList.toggle("open"));

  // Display-only countdown helper for elements carrying data-countdown.
  // Server-side session validation remains authoritative.
  document.querySelectorAll("[data-countdown]").forEach((node) => {
    const target = new Date(node.dataset.countdown).getTime();
    const update = () => {
      const diff = target - Date.now();
      if (diff <= 0) { node.textContent = "Session time reached"; return; }
      const h = Math.floor(diff / 3600000);
      const m = Math.floor((diff % 3600000) / 60000);
      const s = Math.floor((diff % 60000) / 1000);
      node.textContent = `${h}h ${m}m ${s}s`;
    };
    update();
    setInterval(update, 1000);
  });
});
