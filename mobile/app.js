/**
 * JARVIS mobile — the PWA front end.
 *
 * Talks to mobile_server.py over NDJSON streaming so the reply appears as it
 * is written. Voice input uses the browser's own speech recognition, so the
 * phone does the transcribing and the server never sees raw audio.
 */

const $ = (id) => document.getElementById(id);

const pairScreen = $("pair");
const appScreen = $("app");
const tokenInput = $("token-input");
const pairBtn = $("pair-btn");
const pairError = $("pair-error");
const log = $("log");
const input = $("input");
const sendBtn = $("send-btn");
const micBtn = $("mic-btn");
const resetBtn = $("reset-btn");
const statusDot = $("status-dot");
const appName = $("app-name");
const confirmSheet = $("confirm");
const confirmEffect = $("confirm-effect");
const confirmDetail = $("confirm-detail");
const confirmYes = $("confirm-yes");
const confirmNo = $("confirm-no");

let token = localStorage.getItem("jarvis-token") || "";
let busy = false;
let currentBubble = null;
let confirmTimer = null;
let spokenReply = "";

// -- pairing ----------------------------------------------------------------

async function connect(candidate) {
  pairError.textContent = "";
  try {
    const res = await fetch("/api/state", {
      headers: { "X-Jarvis-Token": candidate },
    });
    if (!res.ok) throw new Error("bad token");
    const state = await res.json();
    token = candidate;
    localStorage.setItem("jarvis-token", token);
    appName.textContent = state.name || "JARVIS";
    pairScreen.hidden = true;
    appScreen.hidden = false;
    statusDot.className = "bar__dot live";
    await loadHistory();
    pollState();
    setInterval(pollState, 2000);
    return true;
  } catch {
    pairError.textContent = "That token did not work. Check the terminal.";
    return false;
  }
}

pairBtn.addEventListener("click", () => connect(tokenInput.value.trim()));
tokenInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") connect(tokenInput.value.trim());
});

// -- rendering --------------------------------------------------------------

function addMessage(role, text) {
  const el = document.createElement("div");
  el.className = `msg msg--${role}`;
  el.textContent = text;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
  return el;
}

function addTool(name, ok, gated) {
  const el = document.createElement("div");
  el.className = "tool" + (ok ? "" : " tool--fail");
  el.textContent = gated ? `· ${name} → needs approval` : `· ${name} → ${ok ? "ok" : "failed"}`;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
}

function addError(text) {
  addMessage("error", text);
}

async function loadHistory() {
  try {
    const res = await fetch("/api/history", {
      headers: { "X-Jarvis-Token": token },
    });
    if (!res.ok) return;
    const data = await res.json();
    log.innerHTML = "";
    for (const m of data.messages) {
      addMessage(m.role === "user" ? "you" : "jarvis", m.content);
    }
  } catch {
    /* first run, nothing to load */
  }
}

// -- sending ----------------------------------------------------------------

async function send(text) {
  text = (text || "").trim();
  if (!text || busy) return;

  busy = true;
  statusDot.className = "bar__dot busy";
  spokenReply = "";
  addMessage("you", text);
  input.value = "";
  input.style.height = "auto";

  currentBubble = addMessage("jarvis", "");
  currentBubble.classList.add("cursor");

  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Jarvis-Token": token },
      body: JSON.stringify({ text }),
    });

    if (res.status === 401) {
      addError("Session expired — reconnect.");
      localStorage.removeItem("jarvis-token");
      location.reload();
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let nl;
      while ((nl = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl + 1);
        if (!line) continue;
        let obj;
        try {
          obj = JSON.parse(line);
        } catch {
          continue;
        }
        handleEvent(obj);
      }
    }
  } catch (err) {
    if (currentBubble && !currentBubble.textContent) currentBubble.remove();
    addError("Connection lost. Is the server still running?");
  } finally {
    if (currentBubble) currentBubble.classList.remove("cursor");
    currentBubble = null;
    busy = false;
    statusDot.className = "bar__dot live";
  }
}

function handleEvent(obj) {
  if (obj.type === "text") {
    spokenReply += obj.text;
    if (currentBubble) {
      currentBubble.textContent += obj.text;
      log.scrollTop = log.scrollHeight;
    }
  } else if (obj.type === "tool") {
    if (currentBubble && !currentBubble.textContent) {
      currentBubble.remove();
      currentBubble = addMessage("jarvis", "");
      currentBubble.classList.add("cursor");
    }
    addTool(obj.name, obj.ok, obj.gated);
  } else if (obj.type === "error") {
    if (currentBubble && !currentBubble.textContent) currentBubble.remove();
    addError(obj.error);
  } else if (obj.type === "done") {
    if (currentBubble && !currentBubble.textContent) currentBubble.remove();
    // Speak the finished reply, once — not per streamed chunk.
    if (spokenReply && voiceReplies) speak(spokenReply);
    spokenReply = "";
  }
}

sendBtn.addEventListener("click", () => send(input.value));
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send(input.value);
  }
});
input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 120) + "px";
});

resetBtn.addEventListener("click", async () => {
  await fetch("/api/reset", {
    method: "POST",
    headers: { "X-Jarvis-Token": token },
  });
  log.innerHTML = "";
});

// -- confirmations ----------------------------------------------------------

function showConfirm(req) {
  confirmEffect.textContent = req.effect;
  confirmDetail.textContent = req.detail;
  confirmSheet.hidden = false;
  confirmYes.dataset.id = req.id;
  confirmNo.dataset.id = req.id;
}

async function answerConfirm(id, approved) {
  confirmSheet.hidden = true;
  await fetch("/api/confirm", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Jarvis-Token": token },
    body: JSON.stringify({ id, approved }),
  });
}

confirmYes.addEventListener("click", () =>
  answerConfirm(confirmYes.dataset.id, true));
confirmNo.addEventListener("click", () =>
  answerConfirm(confirmNo.dataset.id, false));

async function pollState() {
  try {
    const res = await fetch("/api/state", {
      headers: { "X-Jarvis-Token": token },
    });
    if (!res.ok) return;
    const state = await res.json();
    if (state.pending && state.pending.length && confirmSheet.hidden) {
      showConfirm(state.pending[0]);
    }
  } catch {
    /* ignore */
  }
}

// -- voice: record -> server transcribes -> JARVIS answers -> speaks ---------
// MediaRecorder is used rather than the Web Speech API because:
//   * SpeechRecognition is Chrome-only and silently unsupported elsewhere;
//   * it sends audio to Google even when we are talking to our own server;
//   * it needs a secure origin on some builds, while MediaRecorder does not.
// Recording and sending the clip to JARVIS keeps one transcriber (the one in
// config.yaml) for terminal, desktop and phone alike.

let recorder = null;
let chunks = [];
let recording = false;
let voiceReplies = localStorage.getItem("jarvis-voice") !== "off";

const speakBtn = $("speak-btn"); // optional; the voice toggle covers the common case
const voiceBtn = $("voice-btn");

function updateVoiceBtn() {
  voiceBtn.textContent = voiceReplies ? "🔊" : "🔇";
  voiceBtn.setAttribute("aria-pressed", String(voiceReplies));
}

updateVoiceBtn();

voiceBtn.addEventListener("click", () => {
  voiceReplies = !voiceReplies;
  localStorage.setItem("jarvis-voice", voiceReplies ? "on" : "off");
  updateVoiceBtn();
  if (!voiceReplies) stopSpeaking();
});

async function startRecording() {
  if (recording) return;
  if (!navigator.mediaDevices || !window.MediaRecorder) {
    addError("This browser cannot record audio.");
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    chunks = [];
    recorder = new MediaRecorder(stream);

    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size) chunks.push(e.data);
    };

    recorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      if (blob.size < 1200) return; // a tap, not speech
      await sendVoice(blob);
    };

    recorder.start();
    recording = true;
    micBtn.classList.add("recording");
    statusDot.className = "bar__dot busy";
  } catch {
    addError("Microphone permission was refused.");
  }
}

function stopRecording() {
  if (!recording || !recorder) return;
  recording = false;
  micBtn.classList.remove("recording");
  try {
    recorder.stop();
  } catch {
    /* already stopped */
  }
}

async function sendVoice(blob) {
  const bubble = addMessage("you", "…");
  bubble.classList.add("cursor");
  try {
    const res = await fetch("/api/transcribe", {
      method: "POST",
      headers: {
        "Content-Type": blob.type || "audio/webm",
        "X-Jarvis-Token": token,
      },
      body: blob,
    });
    const data = await res.json();
    if (!res.ok) {
      bubble.remove();
      addError(data.error || "Could not transcribe that.");
      statusDot.className = "bar__dot live";
      return;
    }
    const text = (data.text || "").trim();
    if (!text) {
      bubble.remove();
      statusDot.className = "bar__dot live";
      return;
    }
    bubble.textContent = text;
    bubble.classList.remove("cursor");
    await send(text);
  } catch {
    bubble.remove();
    addError("Could not reach the transcriber.");
    statusDot.className = "bar__dot live";
  }
}

// Hold the mic to talk.
["touchstart", "mousedown"].forEach((evt) =>
  micBtn.addEventListener(evt, (e) => {
    e.preventDefault();
    startRecording();
  }));

["touchend", "mouseup", "mouseleave"].forEach((evt) =>
  micBtn.addEventListener(evt, (e) => {
    e.preventDefault();
    stopRecording();
  }));

// -- spoken replies ----------------------------------------------------------

let audioEl = null;

async function speak(text) {
  if (!voiceReplies || !text.trim()) return;
  try {
    const res = await fetch("/api/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Jarvis-Token": token },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) return;
    const blob = await res.blob();
    if (audioEl) audioEl.pause();
    audioEl = new Audio(URL.createObjectURL(blob));
    // iOS refuses playback that is not tied to a user gesture; the mic tap
    // counts, so this normally plays. If it does not, the text is still there.
    await audioEl.play().catch(() => {});
  } catch {
    /* speech is a bonus, never a blocker */
  }
}

function stopSpeaking() {
  if (audioEl) {
    audioEl.pause();
    audioEl = null;
  }
}

if (speakBtn) {
  speakBtn.addEventListener("click", () => {
    const last = log.querySelector(".msg--jarvis:last-of-type");
    if (last) speak(last.textContent);
  });
}

// -- boot -------------------------------------------------------------------

if (token) {
  connect(token).then((ok) => {
    if (!ok) {
      pairScreen.hidden = false;
      appScreen.hidden = true;
    }
  });
}

// Register the service worker so the app is installable.
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
