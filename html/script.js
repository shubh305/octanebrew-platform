function loadStream() {
  const key = document.getElementById("stream-key-input").value.trim();
  if (!key) return;

  // Update Player
  const player = videojs("live-player");
  const src = `https://octanebrew.dev/video/live/${key}.m3u8`;

  const connectingOverlay = document.getElementById("connecting-overlay");
  const endedOverlay = document.getElementById("ended-overlay");
  if (connectingOverlay) connectingOverlay.classList.remove("hidden");
  if (endedOverlay) endedOverlay.classList.add("hidden");

  player.src({ type: "application/x-mpegURL", src: src });
  player.play();

  setTimeout(() => {
    if (player.paused() || player.error()) {
      player.trigger("error");
    }
  }, 15000);
}

window.addEventListener('DOMContentLoaded', () => {
  const params = new URLSearchParams(window.location.search);
  const streamKey = params.get("stream");

  if (streamKey) {
    document.getElementById("stream-key-input").value = streamKey;
    setTimeout(() => loadStream(), 500);
  }

  // --- Dynamic Stats & Standby Overlay ---
  const player = videojs("live-player");
  const timeEl = document.getElementById("spec-time");
  const overlay = document.getElementById("standby-overlay");

  // Clock
  setInterval(() => {
    const now = new Date();
    if (timeEl) {
      timeEl.innerText = now.toISOString().split("T")[1].split(".")[0];
    }
  }, 1000);

  player.on("playing", () => {
    if (overlay) overlay.classList.add("hidden");
    const connectingOverlay = document.getElementById("connecting-overlay");
    if (connectingOverlay) connectingOverlay.classList.add("hidden");
  });

  player.on("canplaythrough", () => {
    if (overlay) overlay.classList.add("hidden");
    const connectingOverlay = document.getElementById("connecting-overlay");
    if (connectingOverlay) connectingOverlay.classList.add("hidden");
  });

  player.on("error", () => {
    const connectingOverlay = document.getElementById("connecting-overlay");
    const endedOverlay = document.getElementById("ended-overlay");

    if (connectingOverlay) connectingOverlay.classList.add("hidden");
    if (endedOverlay) endedOverlay.classList.remove("hidden");
    if (overlay) overlay.classList.add("hidden");

    player.pause();
    player.src("");
  });
});

function togglePower() {
    window.location.reload();
}

document.getElementById('stream-key-input').addEventListener('keypress', function (e) {
    if (e.key === 'Enter') loadStream();
});
