import { map, tileLayer } from "https://unpkg.com/leaflet@1.9.4/dist/leaflet-src.esm.js";

// Inject CSS once (ES modules don't auto-apply CSS URLs)
(function ensureLeafletCSS() {
  const id = "leaflet-css-anywidget";
  if (!document.getElementById(id)) {
    const link = document.createElement("link");
    link.id = id;
    link.rel = "stylesheet";
    link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
    document.head.appendChild(link);
  }
})();

function render({ model, el }) {
  // Create a unique container tied to this widget instance
  const container = document.createElement("div");
  container.style.height = model.get("height");
  container.style.width = "100%";
  container.style.borderRadius = "8px";
  container.style.overflow = "hidden";
  el.replaceChildren(container);

  // Build the map using the element (not a string id)
  const m = map(container).setView(model.get("center"), model.get("zoom"));

  tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors"
  }).addTo(m);

  // Keep map responsive when the output area is resized
  const ro = new ResizeObserver(() => m.invalidateSize());
  ro.observe(container);

  // Live update when Python traits change (optional)
  function onCenterChange() {
    const [lat, lng] = model.get("center");
    m.setView([lat, lng], model.get("zoom"));
  }
  model.on("change:center change:zoom", onCenterChange);

  // Cleanup to avoid leaks when the widget re-renders/disposes
  return {
    destroy() {
      ro.disconnect();
      m.remove(); // removes tile layers & listeners
    }
  };
}

export default { render };