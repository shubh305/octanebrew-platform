function loadStream() {
  const key = document.getElementById("stream-key-input").value.trim();
  if (!key) return;

  // Update Player
  const player = videojs("live-player");
  const src = `https://octanebrew.dev/video/live/${key}.m3u8`;

  console.log(`Loading stream: ${src}`);
  player.src({ type: "application/x-mpegURL", src: src });
  player.play();
}

window.addEventListener('DOMContentLoaded', () => {
  const params = new URLSearchParams(window.location.search);
  const streamKey = params.get("stream");

  if (streamKey) {
    document.getElementById("stream-key-input").value = streamKey;
    setTimeout(() => loadStream(), 500);
  }

  // --- Dynamic Footer Logic & Standby Overlay ---
  const player = videojs("live-player");
  const statusEl = document.getElementById("spec-status");
  const codecEl = document.getElementById("spec-codec");
  const timeEl = document.getElementById("spec-time");
  const overlay = document.getElementById("standby-overlay");
  const led = document.getElementById("status-led");

  function setLed(state) {
    if (!led) return;
    led.classList.remove("status-red", "status-green");
    if (state === "active") led.classList.add("status-green");
    else led.classList.add("status-red");
  }

  // Clock
  setInterval(() => {
    const now = new Date();
    timeEl.innerText = "UTC: " + now.toISOString().split("T")[1].split(".")[0];
  }, 1000);

  player.on("playing", () => {
    statusEl.innerHTML = 'STATUS: <span class="blink" style="color: var(--accent)">RECEIVING</span>';
    codecEl.innerText = "CODEC: H.264/AAC";
    overlay.classList.add("hidden");
    setLed("active");
  });

  player.on("pause", () => {
    statusEl.innerHTML = 'STATUS: <span style="color: #888">PAUSED</span>';
    setLed("idle");
  });

  player.on("error", () => {
    statusEl.innerHTML = 'STATUS: <span style="color: red">SIGNAL LOST</span>';
    codecEl.innerText = "CODEC: ERR";
    overlay.classList.remove("hidden");
    setLed("idle");
  });

  player.on("waiting", () => {
    statusEl.innerHTML = 'STATUS: <span class="blink" style="color: yellow">BUFFERING</span>';
  });

});

function togglePower() {
    window.location.reload();
}

document.getElementById('stream-key-input').addEventListener('keypress', function (e) {
    if (e.key === 'Enter') loadStream();
});
