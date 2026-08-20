const api = window.luluDesktop;

const WAKE_RE = /(你好啊?|嗨|hello|hi|lulu|噜噜|露露|璐璐)/i;
const STRIP_WAKE_RE = /^\s*(你好啊?|嗨|hello|hi|lulu|lu\s*lu|噜噜|露露|璐璐)[，,。.!！？?\s]*/i;
const SAMPLE_RATE = 16000;
const SILENCE_MS = 450;
const MIN_MS = 400;
const START_RMS = 0.008;
const PRE_MS = 350;

let mode = 'wake'; // wake | listen | busy
let listenTimer = 0;
let ttsBusy = false;
let recognizing = false;

function stripWake(text) {
  return (text || '').trim().replace(STRIP_WAKE_RE, '').trim();
}

function hasWake(text) {
  return WAKE_RE.test((text || '').replace(/\s+/g, ''));
}

function armListenTimeout() {
  if (listenTimer) window.clearTimeout(listenTimer);
  listenTimer = window.setTimeout(() => {
    if (mode === 'listen') {
      mode = 'wake';
      api?.voiceState?.('idle');
    }
  }, 12000);
}

function setBusy(on) {
  ttsBusy = on;
  if (on) mode = 'busy';
}

async function handleFinal(raw, asrMs) {
  const text = (raw || '').trim();
  console.log('[timing] asr_done', Math.round(asrMs || 0), 'ms text=', text, 'mode=', mode);
  console.log('[voice] asr:', text, 'mode=', mode);
  if (!text || ttsBusy) return;

  if (mode === 'wake') {
    if (!hasWake(text)) return;
    const rest = stripWake(text);
    api?.voiceState?.('listening');
    mode = 'busy';
    await ask(rest.length >= 2 ? rest : '你好');
    return;
  }

  if (mode === 'listen') {
    if (listenTimer) window.clearTimeout(listenTimer);
    mode = 'busy';
    await ask(text);
  }
}

async function ask(query) {
  const t0 = performance.now();
  try {
    const data = await api.askBrain(query);
    console.log(
      '[timing] ask_brain',
      Math.round(performance.now() - t0),
      'ms query=',
      query,
      'route=',
      data?.route || '',
      'reply=',
      (data?.reply || '').slice(0, 40),
    );
    if (data?.error) {
      mode = 'wake';
      api?.voiceState?.('idle');
    }
  } catch {
    console.log('[timing] ask_brain_fail', Math.round(performance.now() - t0), 'ms query=', query);
    mode = 'wake';
    api?.voiceState?.('idle');
  }
}

function floatTo16kPcm(input, inRate) {
  const ratio = inRate / SAMPLE_RATE;
  const outLen = Math.max(1, Math.floor(input.length / ratio));
  const pcm = new Int16Array(outLen);
  for (let i = 0; i < outLen; i += 1) {
    const src = i * ratio;
    const i0 = Math.floor(src);
    const frac = src - i0;
    const a = input[i0] || 0;
    const b = input[i0 + 1] || a;
    const s = Math.max(-1, Math.min(1, a + (b - a) * frac));
    pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return pcm;
}

function rms(buf) {
  let sum = 0;
  for (let i = 0; i < buf.length; i += 1) sum += buf[i] * buf[i];
  return Math.sqrt(sum / Math.max(buf.length, 1));
}

function pcmToB64(chunks) {
  let total = 0;
  for (const c of chunks) total += c.length;
  const merged = new Int16Array(total);
  let o = 0;
  for (const c of chunks) {
    merged.set(c, o);
    o += c.length;
  }
  return int16ToB64(merged);
}

function int16ToB64(pcm) {
  const bytes = new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength);
  let bin = '';
  const step = 0x8000;
  for (let i = 0; i < bytes.length; i += step) {
    bin += String.fromCharCode(...bytes.subarray(i, i + step));
  }
  return btoa(bin);
}

function finishUtterance(saved, currentMode) {
  if (api.asrEnd) {
    return api.asrEnd().catch((err) => {
      console.warn('[voice] stream asr failed, fallback', err);
      return api.recognize(pcmToB64(saved), currentMode);
    });
  }
  return api.recognize(pcmToB64(saved), currentMode);
}

async function startCapture() {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  });
  const ctx = new AudioContext();
  if (ctx.state === 'suspended') await ctx.resume();
  const src = ctx.createMediaStreamSource(stream);
  const proc = ctx.createScriptProcessor(4096, 1, 1);
  const mute = ctx.createGain();
  mute.gain.value = 0;
  src.connect(proc);
  proc.connect(mute);
  mute.connect(ctx.destination);

  let speaking = false;
  let silenceMs = 0;
  let chunks = [];
  let voicedMs = 0;
  let pre = [];
  let preMs = 0;
  const frameMs = (4096 / ctx.sampleRate) * 1000;
  console.log('[voice] capture rate', ctx.sampleRate, 'frame', frameMs.toFixed(1), 'ms');

  proc.onaudioprocess = (ev) => {
    if (ttsBusy || recognizing || mode === 'busy') {
      if (speaking) api?.asrCancel?.();
      speaking = false;
      chunks = [];
      voicedMs = 0;
      silenceMs = 0;
      pre = [];
      preMs = 0;
      return;
    }
    const input = ev.inputBuffer.getChannelData(0);
    const level = rms(input);
    const pcm = floatTo16kPcm(input, ctx.sampleRate);
    pre.push(pcm);
    preMs += frameMs;
    while (preMs > PRE_MS && pre.length > 1) {
      pre.shift();
      preMs -= frameMs;
    }
    if (level >= START_RMS) {
      if (!speaking) {
        chunks = pre.slice();
        voicedMs = preMs;
        speaking = true;
        silenceMs = 0;
        console.log('[timing] vad_start mode=', mode);
        api?.asrStart?.(mode);
        for (const c of chunks) api?.asrPush?.(int16ToB64(c));
        return;
      }
      silenceMs = 0;
      voicedMs += frameMs;
      chunks.push(pcm);
      api?.asrPush?.(int16ToB64(pcm));
      return;
    }
    if (!speaking) return;
    silenceMs += frameMs;
    chunks.push(pcm);
    api?.asrPush?.(int16ToB64(pcm));
    if (silenceMs < SILENCE_MS) return;
    const ready = voicedMs >= MIN_MS && chunks.length;
    const voicedMsReady = voicedMs;
    speaking = false;
    silenceMs = 0;
    voicedMs = 0;
    const saved = chunks;
    const currentMode = mode;
    chunks = [];
    pre = [];
    preMs = 0;
    if (!ready) {
      api?.asrCancel?.();
      return;
    }
    recognizing = true;
    const tAsr = performance.now();
    console.log('[timing] vad_end voiced=', Math.round(voicedMsReady), 'ms silence=', SILENCE_MS);
    console.log('[voice] send', Math.round(voicedMsReady), 'ms');
    finishUtterance(saved, currentMode)
      .then((text) => handleFinal(text, performance.now() - tAsr))
      .catch((err) => console.warn('[voice] asr failed', err))
      .finally(() => { recognizing = false; });
  };
  console.log('[voice] volc asr capture started');
}

api?.onTtsState?.((busy) => {
  setBusy(Boolean(busy));
  if (!busy) {
    mode = 'listen';
    armListenTimeout();
  }
});

api?.onForceListen?.(() => {
  if (ttsBusy) return;
  mode = 'listen';
  api?.voiceState?.('listening');
  armListenTimeout();
});

startCapture().catch((err) => {
  console.error('[voice] mic denied', err);
  api?.voiceState?.('mic-denied');
});
