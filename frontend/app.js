"use strict";
/*
  Nexa - voice-first client.

  Nexa is drawn as a constellation of particles on a sphere. It is always
  listening; it "wakes" when it hears its name ("Nexa" / "Nex"). You talk, it
  thinks, it answers out loud, and its shape reacts the whole time:

    idle       slow drifting sphere, cool blue
    wake       snaps inward + shockwave, bright cyan
    listening  shells pulse with your voice level
    thinking   turbulent violet swarm
    speaking   magenta jitter + sparks on every spoken word

  No build step - Canvas 2D + Web Audio + Web Speech API.
*/

(() => {
  // surface any uncaught error on the gate instead of failing silently
  window.addEventListener("error", (e) => {
    const n = document.getElementById("gateNote");
    if (n) n.textContent = "Script error: " + (e.message || e.error);
    console.error("[nexa] uncaught:", e.error || e.message);
  });

  // ────────────────────────────────────────────────────────────────
  //  config
  // ────────────────────────────────────────────────────────────────
  const CFG = {
    wake: /\b(hey\s+|ok\s+|okay\s+)?(nexa|nexah|neksa|nex)\b/i,
    sleepPhrases: /\b(go to sleep|goodbye nexa|never mind|that'?s all|stand down)\b/i,
    stopPhrases: /^(stop|wait|hold on|hold up|quiet|shush|shut up|pause|enough|one sec|hang on|never mind)[\s.!?,]*$/i,
    utteranceGapMs: 1100,    // silence after speech before we send it
    maxListenMs: 18000,      // hard cap on one utterance
    sleepAfterMs: 40000,     // awake but idle -> back to sleep
  };

  // ────────────────────────────────────────────────────────────────
  //  glow sprite (pre-rendered so per-particle draw is one drawImage)
  // ────────────────────────────────────────────────────────────────
  function makeGlow(r, g, b) {
    const s = 32;
    const c = document.createElement("canvas");
    c.width = c.height = s;
    const x = c.getContext("2d");
    const grad = x.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
    grad.addColorStop(0.0, `rgba(${r},${g},${b},1)`);
    grad.addColorStop(0.25, `rgba(${r},${g},${b},0.55)`);
    grad.addColorStop(1.0, `rgba(${r},${g},${b},0)`);
    x.fillStyle = grad;
    x.fillRect(0, 0, s, s);
    return c;
  }

  const SPRITES = {
    idle: makeGlow(120, 180, 255),
    wake: makeGlow(180, 245, 255),
    listening: makeGlow(120, 225, 255),
    thinking: makeGlow(170, 130, 255),
    speaking: makeGlow(255, 120, 220),
  };

  const STATE_PARAMS = {
    idle:      { spread: 1.00, jitter: 0.004, swirl: 0.020, pull: 0.00, bright: 0.55 },
    wake:      { spread: 0.80, jitter: 0.020, swirl: 0.150, pull: 0.40, bright: 1.00 },
    listening: { spread: 1.07, jitter: 0.006, swirl: 0.045, pull: 0.00, bright: 0.75 },
    thinking:  { spread: 0.95, jitter: 0.030, swirl: 0.300, pull: 0.08, bright: 0.62 },
    speaking:  { spread: 1.03, jitter: 0.018, swirl: 0.085, pull: 0.00, bright: 0.90 },
  };

  // ────────────────────────────────────────────────────────────────
  //  ParticleField - the visible "Nexa"
  // ────────────────────────────────────────────────────────────────
  class ParticleField {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d", { alpha: false });
      this.count = 1800;
      this.dpr = Math.min(window.devicePixelRatio || 1, 1.6);
      this.energy = 0;         // mic level 0..1 (set from outside)
      this.ttsPulse = 0;       // spikes on each spoken word
      this.state = "idle";
      this.cur = { ...STATE_PARAMS.idle };
      this.spritePrev = SPRITES.idle;
      this.spriteCur = SPRITES.idle;
      this.blend = 1;
      this.rot = 0;
      this.tilt = 0;
      this.shock = [];         // wake shockwaves
      this.sparks = [];        // speaking sparks
      this._frames = [];
      this._buildParticles();
      this._resize();
      window.addEventListener("resize", () => this._resize());
      this._loop = this._loop.bind(this);
      requestAnimationFrame(this._loop);
    }

    _buildParticles() {
      // Fibonacci sphere -> even distribution
      this.p = [];
      const n = this.count;
      const golden = Math.PI * (3 - Math.sqrt(5));
      for (let i = 0; i < n; i++) {
        const y = 1 - (i / (n - 1)) * 2;
        const rad = Math.sqrt(1 - y * y);
        const th = golden * i;
        this.p.push({
          x: Math.cos(th) * rad, y, z: Math.sin(th) * rad,
          ph: Math.random() * Math.PI * 2,
          sp: 0.6 + Math.random() * 0.9,
          rj: Math.random(),
        });
      }
    }

    _resize() {
      const w = window.innerWidth, h = window.innerHeight;
      this.canvas.width = w * this.dpr;
      this.canvas.height = h * this.dpr;
      this.canvas.style.width = w + "px";
      this.canvas.style.height = h + "px";
      this.w = this.canvas.width;
      this.h = this.canvas.height;
      this.baseR = Math.min(this.w, this.h) * 0.30;
    }

    setState(name) {
      if (!STATE_PARAMS[name] || name === this.state) return;
      this.state = name;
      this.spritePrev = this.spriteCur;
      this.spriteCur = SPRITES[name];
      this.blend = 0;
      if (name === "wake") this.shock.push({ r: this.baseR * 0.5, life: 1 });
    }

    pulse() {           // called per spoken word
      this.ttsPulse = Math.min(1.4, this.ttsPulse + 0.9);
      const cx = this.w / 2, cy = this.h / 2;
      for (let i = 0; i < 3; i++) {
        const a = Math.random() * Math.PI * 2;
        const v = (2 + Math.random() * 3) * this.dpr;
        this.sparks.push({
          x: cx + (Math.random() - 0.5) * this.baseR,
          y: cy + (Math.random() - 0.5) * this.baseR,
          vx: Math.cos(a) * v, vy: Math.sin(a) * v, life: 1,
        });
      }
    }

    _loop(now) {
      const dt = this._last ? Math.min(48, now - this._last) : 16;
      this._last = now;
      this._autoThrottle(dt);

      const ctx = this.ctx;
      // motion-trail clear
      ctx.globalCompositeOperation = "source-over";
      ctx.fillStyle = "rgba(5,6,10,0.30)";
      ctx.fillRect(0, 0, this.w, this.h);

      // ease current params toward the target state
      const tgt = STATE_PARAMS[this.state];
      const k = 1 - Math.pow(0.001, dt / 1000);
      for (const key in tgt) this.cur[key] += (tgt[key] - this.cur[key]) * k;
      if (this.blend < 1) this.blend = Math.min(1, this.blend + dt / 480);
      this.ttsPulse *= Math.pow(0.9, dt / 16);

      // rotation
      const swirl = this.cur.swirl + (this.state === "thinking" ? Math.sin(now / 700) * 0.15 : 0);
      this.rot += swirl * dt / 60;
      this.tilt = Math.sin(now / 4000) * 0.35;

      const cx = this.w / 2, cy = this.h / 2;
      const cosR = Math.cos(this.rot), sinR = Math.sin(this.rot);
      const cosT = Math.cos(this.tilt), sinT = Math.sin(this.tilt);
      const t = now / 1000;

      const listenPush = this.state === "listening" ? this.energy * 0.55 : 0;
      const speakJit = this.state === "speaking" ? this.ttsPulse * 0.10 : 0;
      const jitter = this.cur.jitter + speakJit + (this.state === "listening" ? this.energy * 0.05 : 0);
      const bright = this.cur.bright + (this.state === "listening" ? this.energy * 0.3 : 0);
      const FOV = 2.2;

      ctx.globalCompositeOperation = "lighter";

      for (let i = 0; i < this.count; i++) {
        const pt = this.p[i];
        // breathing + ripple + jitter, in sphere space
        const breathe = 1 + Math.sin(t * pt.sp + pt.ph) * 0.05;
        const ripple = 1 + Math.sin(t * 6 - pt.rj * 8) * listenPush;
        let rr = this.cur.spread * breathe * ripple * (1 - this.cur.pull * pt.rj);
        let px = pt.x * rr, py = pt.y * rr, pz = pt.z * rr;
        px += (Math.random() - 0.5) * jitter;
        py += (Math.random() - 0.5) * jitter;
        pz += (Math.random() - 0.5) * jitter;

        // rotate Y then tilt X
        let x1 = px * cosR - pz * sinR;
        let z1 = px * sinR + pz * cosR;
        let y1 = py * cosT - z1 * sinT;
        let z2 = py * sinT + z1 * cosT;

        const persp = FOV / (FOV + z2);
        const sx = cx + x1 * this.baseR * persp;
        const sy = cy + y1 * this.baseR * persp;

        const depth = (persp - 0.55) / 0.9;          // ~0..1 front-ness
        if (depth <= 0.02) continue;
        const size = (1.6 + depth * 4.2) * this.dpr;
        const alpha = Math.max(0, Math.min(1, depth * bright));

        if (this.blend < 1) {
          ctx.globalAlpha = alpha * (1 - this.blend);
          ctx.drawImage(this.spritePrev, sx - size, sy - size, size * 2, size * 2);
          ctx.globalAlpha = alpha * this.blend;
        } else {
          ctx.globalAlpha = alpha;
        }
        ctx.drawImage(this.spriteCur, sx - size, sy - size, size * 2, size * 2);
      }

      // shockwaves
      for (let i = this.shock.length - 1; i >= 0; i--) {
        const s = this.shock[i];
        s.r += (12 + s.r * 0.06) * dt / 16;
        s.life -= dt / 620;
        if (s.life <= 0) { this.shock.splice(i, 1); continue; }
        ctx.globalAlpha = s.life * 0.5;
        ctx.strokeStyle = "rgba(170,240,255,1)";
        ctx.lineWidth = 2 * this.dpr;
        ctx.beginPath();
        ctx.arc(cx, cy, s.r, 0, Math.PI * 2);
        ctx.stroke();
      }

      // sparks
      for (let i = this.sparks.length - 1; i >= 0; i--) {
        const s = this.sparks[i];
        s.x += s.vx; s.y += s.vy; s.vx *= 0.94; s.vy *= 0.94;
        s.life -= dt / 500;
        if (s.life <= 0) { this.sparks.splice(i, 1); continue; }
        const sz = 3 * this.dpr * s.life;
        ctx.globalAlpha = s.life;
        ctx.drawImage(SPRITES.speaking, s.x - sz, s.y - sz, sz * 2, sz * 2);
      }

      ctx.globalAlpha = 1;
      requestAnimationFrame(this._loop);
    }

    _autoThrottle(dt) {
      this._frames.push(dt);
      if (this._frames.length < 90) return;
      const avg = this._frames.reduce((a, b) => a + b, 0) / this._frames.length;
      this._frames.length = 0;
      if (avg > 24 && this.count > 900) { this.count -= 250; this.p.length = this.count; }
      else if (avg < 13 && this.count < 2200) { this.count += 200; this._buildParticles(); }
    }
  }

  // ────────────────────────────────────────────────────────────────
  //  Mic - Web Audio amplitude (drives the visual, instantly)
  // ────────────────────────────────────────────────────────────────
  class Mic {
    async start() {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      const AC = window.AudioContext || window.webkitAudioContext;
      this.ctx = new AC();
      const src = this.ctx.createMediaStreamSource(this.stream);
      this.analyser = this.ctx.createAnalyser();
      this.analyser.fftSize = 1024;
      src.connect(this.analyser);
      this.buf = new Uint8Array(this.analyser.fftSize);
      this.level = 0;   // smoothed, for visuals
      this.raw = 0;     // near-instant, for barge-in detection
      this._tick();
    }
    _tick() {
      this.analyser.getByteTimeDomainData(this.buf);
      let sum = 0;
      for (let i = 0; i < this.buf.length; i++) {
        const v = (this.buf[i] - 128) / 128;
        sum += v * v;
      }
      const rms = Math.sqrt(sum / this.buf.length);
      this.raw = Math.min(1, rms * 3.2);
      this.level += (this.raw - this.level) * 0.25;
      requestAnimationFrame(() => this._tick());
    }
  }

  // ────────────────────────────────────────────────────────────────
  //  Ears - continuous SpeechRecognition + wake word + utterance gate
  // ────────────────────────────────────────────────────────────────
  class Ears {
    constructor(handlers) {
      this.h = handlers;   // {onWake, onBargeIn, onInterim, onUtterance, onSleepPhrase, onReack, onError}
      // mode:
      //   "idle"      asleep - only the wake word does anything
      //   "listening" capturing your question
      //   "busy"      Nexa is thinking/speaking - ignore everything except a
      //               clean standalone wake word (barge-in). Prevents her own
      //               voice, picked up by the mic, being treated as input.
      this.mode = "idle";
      this.buffer = "";
      this.running = false;
      this._want = false;
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!SR) { this.unsupported = true; return; }
      const rec = new SR();
      rec.lang = "en-US";
      rec.continuous = true;
      rec.interimResults = true;
      rec.maxAlternatives = 1;
      rec.onstart = () => { this.running = true; console.log("[nexa] recognition on"); };
      rec.onresult = (e) => this._onResult(e);
      rec.onnomatch = () => {};
      rec.onerror = (e) => {
        console.warn("[nexa] recognition error:", e.error);
        this.running = false;
        if (e.error === "not-allowed" || e.error === "service-not-allowed")
          this.h.onError?.("Microphone permission blocked. Allow it via the address-bar lock icon, then reload.");
        else if (e.error === "audio-capture")
          this.h.onError?.("No microphone found.");
        else if (e.error === "network")
          this.h.onError?.("Speech recognition needs an internet connection.");
        // "no-speech" / "aborted" are normal - just let onend restart us
      };
      rec.onend = () => {
        this.running = false;
        if (this._want) this._scheduleRestart();
      };
      this.rec = rec;
    }

    start() { this._want = true; this._kick(); }
    stop() { this._want = false; try { this.rec.stop(); } catch {} }

    // ensure recognition is running RIGHT NOW (call after an interrupt so the
    // user's follow-up isn't lost in a restart gap)
    kick() {
      clearTimeout(this._restart);
      this._kick();
    }

    _kick() {
      if (this.running || !this._want) return;
      try {
        this.rec.start();
      } catch (err) {
        // "already started" or a transient state - retry shortly
        this._scheduleRestart();
      }
    }

    _scheduleRestart() {
      clearTimeout(this._restart);
      this._restart = setTimeout(() => this._kick(), 120);
    }

    setMode(mode) {
      this.mode = mode;
      this.buffer = "";
      clearTimeout(this._gap);
      clearTimeout(this._hard);
      if (mode === "listening") {
        this._hard = setTimeout(() => this._flush(true), CFG.maxListenMs);
      }
    }

    // "nexa", "hey nexa", "nexa?" ... but not a whole sentence containing it
    _isBareWake(text) {
      if (!CFG.wake.test(text)) return false;
      const rest = text.replace(CFG.wake, "").replace(/[^a-z ]/gi, "").trim();
      return rest.split(/\s+/).filter(Boolean).length <= 1;
    }

    _onResult(e) {
      let interim = "", finalChunk = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) finalChunk += r[0].transcript;
        else interim += r[0].transcript;
      }
      const heard = (finalChunk + " " + interim).trim();
      if (!heard) return;
      console.log(`[nexa] heard (${this.mode}):`, JSON.stringify(heard));

      // ---- asleep: only the wake word matters ----
      if (this.mode === "idle") {
        if (CFG.wake.test(heard)) this.h.onWake?.(heard.replace(CFG.wake, "").trim());
        return;
      }

      // ---- Nexa busy: ignore her echo, but if you address her by name,
      //      interrupt - and if you tacked a question on, pass it straight through
      if (this.mode === "busy") {
        if (finalChunk && CFG.wake.test(finalChunk)) {
          this.h.onBargeIn?.(finalChunk.replace(CFG.wake, "").trim());
        }
        return;
      }

      // ---- listening for your question ----
      if (CFG.sleepPhrases.test(heard)) { this.h.onSleepPhrase?.(); return; }

      // strip a leading "nexa," the recogniser may have caught
      const cleanInterim = interim.replace(CFG.wake, "").trim();
      const cleanFinal = finalChunk.replace(CFG.wake, "").trim();

      // just "nexa" again while already listening -> re-acknowledge, don't send
      if (!this.buffer && !cleanFinal && this._isBareWake(heard)) {
        this.h.onReack?.();
        return;
      }

      if (cleanInterim) this.h.onInterim?.(cleanInterim);
      if (cleanFinal) this.buffer = (this.buffer + " " + cleanFinal).trim();

      clearTimeout(this._gap);
      this._gap = setTimeout(() => this._flush(false), CFG.utteranceGapMs);
    }

    _flush(forced) {
      clearTimeout(this._gap);
      clearTimeout(this._hard);
      const text = this.buffer.trim();
      this.buffer = "";
      if (text.replace(/[^a-z0-9]/gi, "").length >= 2 && !this._isBareWake(text)) {
        this.h.onUtterance?.(text);
      } else if (forced) {
        this.h.onSilence?.();
      }
    }
  }

  // ────────────────────────────────────────────────────────────────
  //  Voice - speechSynthesis, sentence-queued so she starts fast
  // ────────────────────────────────────────────────────────────────
  // ranked best -> worst; all female, most natural first. "Natural"/"Online"
  // Microsoft voices (best) are exposed by Edge and Windows 11.
  const VOICE_RANK = [
    "Microsoft Aria Online (Natural) - English (United States)",
    "Microsoft Jenny Online (Natural) - English (United States)",
    "Microsoft Ava Online (Natural) - English (United States)",
    "Microsoft Emma Online (Natural) - English (United States)",
    "Microsoft Michelle Online (Natural) - English (United States)",
    "Microsoft Sonia Online (Natural) - English (United Kingdom)",
    "Google UK English Female",
    "Google US English",
    "Samantha", "Karen", "Tessa", "Moira", "Fiona", "Serena",
    "Microsoft Zira - English (United States)",
    "Microsoft Hazel - English (Great Britain)",
  ];
  const FEMALE_HINT = /aria|jenny|ava|emma|michelle|sonia|zira|hazel|susan|linda|catherine|samantha|karen|tessa|moira|fiona|serena|female|woman|girl/i;

  class Voice {
    constructor() {
      this.muted = false;
      this.voice = null;
      this.saved = null;
      try { this.saved = localStorage.getItem("nexa.voice"); } catch {}
      this._pick();
      speechSynthesis.addEventListener?.("voiceschanged", () => this._pick());
      if (speechSynthesis.onvoiceschanged !== undefined) {
        speechSynthesis.onvoiceschanged = () => this._pick();
      }
    }
    voices() {
      return speechSynthesis.getVoices().filter((v) => /^en(-|_|$)/i.test(v.lang));
    }
    _pick() {
      const vs = speechSynthesis.getVoices();
      if (!vs.length) return;
      const byName = (n) => vs.find((v) => v.name === n);
      this.voice =
        (this.saved && byName(this.saved)) ||
        VOICE_RANK.map(byName).find(Boolean) ||
        vs.find((v) => FEMALE_HINT.test(v.name) && /^en/i.test(v.lang)) ||
        vs.find((v) => /^en(-|_|$)/i.test(v.lang)) ||
        vs[0];
      window.dispatchEvent(new Event("nexa-voices"));
    }
    setVoice(name) {
      const v = speechSynthesis.getVoices().find((x) => x.name === name);
      if (!v) return;
      this.voice = v;
      this.saved = name;
      try { localStorage.setItem("nexa.voice", name); } catch {}
    }
    cancel() { try { speechSynthesis.cancel(); } catch {} }

    // strip stuff that voices read out literally: *, _, `, #, quotes, brackets
    static clean(text) {
      return text
        .replace(/```[\s\S]*?```/g, " ")
        .replace(/`([^`]+)`/g, "$1")
        .replace(/\*\*([^*]+)\*\*/g, "$1")
        .replace(/\*([^*]+)\*/g, "$1")
        .replace(/_([^_]+)_/g, "$1")
        .replace(/^#{1,6}\s+/gm, "")
        .replace(/[*_#`]+/g, "")
        .replace(/["“”„‟«»]/g, "")
        .replace(/[()[\]]/g, "")
        .replace(/\s{2,}/g, " ")
        .trim();
    }

    speak(text, { onWord } = {}) {
      text = Voice.clean(text || "");
      if (this.muted || !text) return;
      // one utterance per sentence keeps latency low and lets her start talking
      // before the model has finished generating
      for (const part of text.split(/(?<=[.!?…])\s+/)) {
        if (!part.trim()) continue;
        const u = new SpeechSynthesisUtterance(part.trim());
        if (this.voice) u.voice = this.voice;
        u.rate = 0.98;      // a touch slower reads more naturally
        u.pitch = 1.0;
        u.onboundary = () => onWord && onWord();
        speechSynthesis.speak(u);
      }
    }
  }

  // ────────────────────────────────────────────────────────────────
  //  Brain - stream from the API, hand back complete sentences
  // ────────────────────────────────────────────────────────────────
  const Brain = {
    conversationId: null,
    async ask(text, { onSentence, onMeta, onDone, onMemory, signal }) {
      const res = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, conversation_id: this.conversationId }),
        signal,
      });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "", pending = "", finished = false;
      const emitSentences = (flush) => {
        const re = /[^.!?…]+[.!?…]+[\s"')\]]*/g;
        let m, last = 0;
        while ((m = re.exec(pending))) { onSentence(m[0].trim()); last = re.lastIndex; }
        pending = pending.slice(last);
        if (flush && pending.trim()) { onSentence(pending.trim()); pending = ""; }
      };
      const finish = () => { if (!finished) { finished = true; emitSentences(true); onDone?.(); } };
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const blocks = buf.split("\n\n"); buf = blocks.pop();
        for (const b of blocks) {
          if (!b.trim()) continue;
          let ev = "message", data = "";
          for (const line of b.split("\n")) {
            if (line.startsWith("event:")) ev = line.slice(6).trim();
            else if (line.startsWith("data:")) data += line.slice(5).trim();
          }
          const payload = data ? JSON.parse(data) : {};
          if (ev === "token") { pending += payload.text || ""; emitSentences(false); }
          else if (ev === "meta") {
            this.conversationId = payload.conversation_id || this.conversationId;
            onMeta?.(payload);
          } else if (ev === "done") {
            finish();             // spoken reply complete - UI can move on
          } else if (ev === "memory") {
            onMemory?.(payload);  // arrives a bit later, after bookkeeping
          }
        }
      }
      finish();                  // safety, in case 'done' never arrived
    },
  };

  // ────────────────────────────────────────────────────────────────
  //  App - the state machine
  // ────────────────────────────────────────────────────────────────
  const el = (id) => document.getElementById(id);
  const captionEl = el("caption");

  const App = {
    state: "idle",
    async boot() {
      console.log("[nexa] boot");
      this.field = new ParticleField(el("field"));
      this.voice = new Voice();
      this.mic = new Mic();

      // wire controls FIRST, so the button always responds even if checks fail
      el("gateBtn").addEventListener("click", () => {
        this._enter().catch((e) => {
          console.error("[nexa] _enter failed:", e);
          el("gateNote").textContent = "Couldn't start: " + (e && e.message ? e.message : e);
        });
      });
      el("muteBtn").addEventListener("click", () => this._toggleMute());
      el("detailBtn").addEventListener("click", () => this._toggleDetails());
      el("sleepBtn").addEventListener("click", () => this._sleep(true));
      this._initVoicePicker();

      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!SR) {
        el("gateNote").textContent =
          "This browser has no Speech Recognition API. Use desktop Chrome or Edge (not Firefox, not Brave with Shields up).";
      }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        el("gateNote").textContent =
          "No microphone API. Open the app via http://127.0.0.1:8000 (a 'secure context'), not a file:// path.";
      }

      // is the backend up yet? (bootstrap can take a while on first run)
      fetch("/api/health")
        .then((r) => r.json())
        .then((h) => {
          el("gateMsg").innerHTML =
            `Model <b>${h.model}</b> · ${h.chunks_indexed} chunks ready. Tap to wake her, then say <b>&ldquo;Nexa&rdquo;</b>.`;
        })
        .catch(() => {
          el("gateNote").textContent =
            "Server still starting — wait for '[nexa] ready' in the terminal, then reload.";
        });

      // feed mic level into the visual every frame
      const pump = () => {
        this.field.energy = this.mic.level || 0;
        requestAnimationFrame(pump);
      };
      pump();

      // ── mic status light (so you can SEE if it's listening) ──
      setInterval(() => this._updateStatus(), 400);
    },

    _updateStatus() {
      const box = el("status");
      let cls = "status--idle", txt = 'asleep — say "Nexa"';
      if (!this.ears || this.ears.unsupported) { cls = "status--error"; txt = "no speech recognition"; }
      else if (!this.ears.running) { cls = "status--error"; txt = "mic reconnecting…"; }
      else if (this.ears.mode === "busy") { cls = "status--busy"; txt = "…"; }
      else if (this.ears.mode === "listening") { cls = "status--listening"; txt = "listening"; }
      box.className = "status " + cls;
      el("statusText").textContent = txt;
    },

    async _enter() {
      console.log("[nexa] wake clicked");
      el("gateNote").textContent = "";
      el("gateBtn").textContent = "Starting…";
      el("gateBtn").disabled = true;

      // 1. mic amplitude analyser - OPTIONAL, only drives the visual
      try {
        await this.mic.start();
        console.log("[nexa] mic analyser ok");
      } catch (e) {
        console.warn("[nexa] mic analyser unavailable (continuing):", e);
      }

      // 2. unlock TTS (some browsers need a gesture-triggered speak first)
      try {
        speechSynthesis.resume();
        speechSynthesis.speak(new SpeechSynthesisUtterance(" "));
      } catch {}

      // 3. speech recognition - REQUIRED
      this.ears = new Ears({
        onError: (msg) => {
          el("gate").classList.remove("gone");
          el("gateBtn").textContent = "Retry";
          el("gateBtn").disabled = false;
          el("gateNote").textContent = msg;
        },
        onWake: (rest) => this._wake(rest),
        onBargeIn: (rest) => this._wake(rest || ""),
        onReack: () => {
          clearTimeout(this._sleepTimer);
          this._setState("listening");
          this._say("mm-hmm?", false, true);
          this._armSleep();
        },
        onInterim: (t) => { if (this.state === "listening") this._say(t, true); },
        onUtterance: (t) => this._heard(t),
        onSilence: () => { if (this.state === "listening") this._armSleep(); },
        onSleepPhrase: () => this._sleep(true),
      });
      if (this.ears.unsupported) {
        el("gateBtn").textContent = "Wake Nexa";
        el("gateBtn").disabled = false;
        el("gateNote").textContent = "Speech Recognition isn't available in this browser. Use desktop Chrome or Edge.";
        return;
      }
      this.ears.start();
      this.ears.setMode("idle");
      console.log("[nexa] ears started");

      el("gate").classList.add("gone");
      this._setState("idle");
      this._say('Say "Nexa" to wake me.', false, true);
      // brief proof that audio output works, then she's silent until spoken to
      this.voice.speak("Ready.");
    },

    _setState(s) {
      this.state = s;
      this.field.setState(s);
    },

    _wake(rest) {
      clearTimeout(this._sleepTimer);
      clearInterval(this._tick);
      // saying "Nexa" while she's thinking/talking interrupts the current reply
      if (this.state === "speaking" || this.state === "thinking") {
        this._stopReply();
        this._interruptedAt = Date.now();
      }

      const followUp =
        rest && rest.replace(/[^a-z0-9 ]/gi, "").split(/\s+/).filter(Boolean).length >= 2
          ? rest
          : "";

      this.ears.setMode("listening");
      this.ears.kick();                 // make sure the mic is live NOW, no restart gap
      this.field.setState("wake");      // visual flash / shockwave
      this.state = "listening";         // ...but logically we're already listening
      setTimeout(() => { if (this.state === "listening") this.field.setState("listening"); }, 400);
      this._say(followUp ? "…" : "mm-hmm?", false, true);
      this._armSleep();

      if (followUp) {
        // "Nexa, <question>" said in one breath
        this._heard(followUp);
      }
    },

    _heard(text) {
      el("dHeard").textContent = text || "—";
      if (!text || !text.trim()) {
        if (this.state === "listening") this._armSleep();
        return;
      }
      // "stop" / "wait" right after interrupting her isn't a new question
      if (CFG.stopPhrases.test(text.trim()) && Date.now() - (this._interruptedAt || 0) < 3500) {
        this._say("…", false, true);
        this._armSleep();
        return;
      }
      clearTimeout(this._sleepTimer);
      this._stopReply();                   // cancel anything still in flight
      this.ears.setMode("busy");           // ignore the mic while she works
      this._setState("thinking");
      this._abort = new AbortController();

      // silent "thinking" caption - the violet swarm animation is the cue,
      // no spoken filler. Only show a seconds counter if it drags on.
      const t0 = Date.now();
      this._say("…", false, true);
      clearInterval(this._tick);
      this._tick = setInterval(() => {
        if (this.state !== "thinking") return;
        const s = Math.round((Date.now() - t0) / 1000);
        if (s >= 4) this._say(`thinking… ${s}s`, false, true);
      }, 1000);
      const stopTick = () => clearInterval(this._tick);

      let spokeAny = false;
      const queue = [];

      // each turn gets its own token; a new turn or an interrupt invalidates it
      const turn = (this._turn = (this._turn || 0) + 1);
      const alive = () => turn === this._turn;

      // watchdog: if the backend hangs, don't stay stuck in "busy" forever
      clearTimeout(this._busyGuard);
      this._busyGuard = setTimeout(() => {
        if (alive() && this.state !== "listening" && this.state !== "idle") {
          console.warn("[nexa] turn watchdog fired");
          this._doneSpeaking();
        }
      }, 35000);

      Brain.ask(text, {
        signal: this._abort.signal,
        onSentence: (s) => {
          if (!s || !alive()) return;
          stopTick();
          queue.push(s);
          if (!spokeAny) {
            spokeAny = true;
            this._setState(this.voice.muted ? "listening" : "speaking");
          }
          this._say(s);
          if (!this.voice.muted) {
            this.voice.speak(s, { onWord: () => this.field.pulse() });
          }
        },
        onMeta: (p) => this._fillDetails(p),
        onMemory: (p) => this._fillDetails(p),
        onDone: () => {
          stopTick();
          if (!alive()) return;
          const full = queue.join(" ").trim();
          if (!full) { this._say("I don't have anything for that."); this._doneSpeaking(); return; }
          if (this.voice.muted) {
            this._say(full);
            setTimeout(() => { if (alive()) this._doneSpeaking(); }, Math.min(9000, 1500 + full.length * 45));
          } else {
            this._waitForSynth(() => { if (alive()) this._doneSpeaking(); });
          }
        },
      }).catch((err) => {
        stopTick();
        if (!alive() || (err && err.name === "AbortError")) return;
        console.error(err);
        this._say("Something went wrong reaching my brain.", false, true);
        if (!this.voice.muted) this.voice.speak("Something went wrong reaching my brain.");
        this._doneSpeaking();
      });
    },

    // interrupt the current reply (only ever triggered by the wake word now)
    _stopReply() {
      this._turn = (this._turn || 0) + 1;      // invalidates callbacks in flight
      clearTimeout(this._busyGuard);
      clearInterval(this._tick);
      this.voice.cancel();
      if (this._abort) this._abort.abort();
    },

    _waitForSynth(cb) {
      const check = () => {
        if (speechSynthesis.speaking || speechSynthesis.pending) {
          setTimeout(check, 250);
        } else cb();
      };
      setTimeout(check, 300);
    },

    _doneSpeaking() {
      clearTimeout(this._busyGuard);
      if (this.state === "idle") return;
      // small gap so the tail of Nexa's audio isn't recognised as input
      setTimeout(() => {
        if (this.state === "idle") return;
        this.ears.setMode("listening");
        this._setState("listening");
        this._say("…", false, true);
        this._armSleep();
      }, 350);
    },

    _armSleep() {
      clearTimeout(this._sleepTimer);
      this._sleepTimer = setTimeout(() => this._sleep(true), CFG.sleepAfterMs);
    },

    _sleep() {
      clearTimeout(this._sleepTimer);
      clearTimeout(this._busyGuard);
      this._stopReply();
      if (this.ears) this.ears.setMode("idle");
      this._setState("idle");
      this._say('Say "Nexa" to wake me.', false, true);
    },

    // caption helper
    _say(text, interim = false, dim = false) {
      captionEl.classList.toggle("dim", dim);
      captionEl.classList.add("show");
      captionEl.innerHTML = interim
        ? `<span class="interim">${escapeHtml(text)}</span>`
        : escapeHtml(text);
    },

    _toggleMute() {
      this.voice.muted = !this.voice.muted;
      el("muteBtn").textContent = this.voice.muted ? "🔇" : "🔊";
      el("muteBtn").classList.toggle("on", this.voice.muted);
      if (this.voice.muted) this.voice.cancel();
    },

    _toggleDetails() {
      const d = el("details");
      d.hidden = !d.hidden;
      el("detailBtn").classList.toggle("on", !d.hidden);
    },

    _initVoicePicker() {
      const sel = el("voiceSelect");
      const fill = () => {
        const list = this.voice.voices();
        sel.innerHTML = "";
        for (const v of list) {
          const o = document.createElement("option");
          o.value = v.name;
          o.textContent = v.name.replace(/ - English.*$/, "").replace(/Microsoft |Online |\(Natural\)/g, "").trim() + (/gb|uk|united kingdom/i.test(v.lang + v.name) ? " (UK)" : "");
          if (this.voice.voice && v.name === this.voice.voice.name) o.selected = true;
          sel.appendChild(o);
        }
        if (!list.length) sel.innerHTML = '<option>no voices installed</option>';
      };
      fill();
      window.addEventListener("nexa-voices", fill);
      sel.addEventListener("change", () => this.voice.setVoice(sel.value));
      el("voiceTest").addEventListener("click", () => {
        this.voice.cancel();
        const wasMuted = this.voice.muted;
        this.voice.muted = false;
        this.voice.speak("Hi, I'm Nexa. This is how I sound.");
        this.voice.muted = wasMuted;
      });
    },

    _fillDetails(p) {
      // 'meta' carries sources + recalled; the later 'memory' event carries
      // stored + forgotten. Only update the sections present in this payload.
      if ("sources" in p) {
        const s = p.sources || [];
        el("dSources").innerHTML = s.length
          ? s.map((x) => `<div class="item"><b>${escapeHtml(x.title)}</b> · ${x.score.toFixed(2)}<br>${escapeHtml(x.text.slice(0, 180))}…</div>`).join("")
          : '<p class="muted">none</p>';
      }
      if ("memories_recalled" in p) {
        const m = p.memories_recalled || [];
        el("dMemory").innerHTML = m.length
          ? m.map((x) => `<div class="item"><b>${escapeHtml(x.type)}</b> · ${escapeHtml(x.text)}</div>`).join("")
          : '<p class="muted">none</p>';
      }
      if ("memories_stored" in p || "memories_forgotten" in p) {
        const changes = [
          ...(p.memories_forgotten || []).map((x) => `<div class="item">🗑 forgot · ${escapeHtml(x.text)}</div>`),
          ...(p.memories_stored || []).map((x) => `<div class="item">＋ learned · ${escapeHtml(x.text)}</div>`),
        ];
        el("dMemChange").innerHTML = changes.length ? changes.join("") : '<p class="muted">none</p>';
      }
    },
  };

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  App.boot();
})();
