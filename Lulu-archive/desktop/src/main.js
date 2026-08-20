import * as THREE from 'three';
import { VrmAvatar } from './vrm-avatar.js';
import { connectControlSocket } from './ws-client.js';

const SCALE_MIN = 0.4;
const SCALE_MAX = 2.4;
const SCALE_KEY = 'lulu.avatar.scale';
const VISEMES = ['aa', 'ih', 'ou', 'ee', 'oh'];

let userScale = 1;
try {
  const saved = Number(localStorage.getItem(SCALE_KEY));
  if (Number.isFinite(saved) && saved > 0) userScale = Math.min(SCALE_MAX, Math.max(SCALE_MIN, saved));
} catch {
  /* ignore */
}

function setUserScale(next) {
  userScale = Math.min(SCALE_MAX, Math.max(SCALE_MIN, next));
  try {
    localStorage.setItem(SCALE_KEY, String(userScale));
  } catch {
    /* ignore */
  }
  if (avatar.vrm) frameFullBody(avatar.vrm);
  return userScale;
}

const desktop = window.luluDesktop || null;
document.documentElement.classList.add('overlay');
document.body.classList.add('overlay');

const canvas = document.getElementById('stage');
const renderer = new THREE.WebGLRenderer({
  canvas,
  antialias: true,
  alpha: true,
  premultipliedAlpha: false,
  preserveDrawingBuffer: true,
});
renderer.setClearColor(0x000000, 0);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
renderer.setSize(Math.max(window.innerWidth, 1), Math.max(window.innerHeight, 1), true);
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 80);
camera.position.set(0, 0.8, 10);
camera.lookAt(0, 0.8, 0);

function frameFullBody(vrm) {
  if (!vrm) return;
  vrm.scene.updateMatrixWorld(true);

  const world = new THREE.Vector3();
  let minY = Infinity;
  let maxY = -Infinity;

  vrm.scene.traverse((obj) => {
    if (obj.isBone) {
      obj.getWorldPosition(world);
      minY = Math.min(minY, world.y);
      maxY = Math.max(maxY, world.y);
    }
  });

  const humanoid = vrm.humanoid;
  if (humanoid) {
    for (const name of ['head', 'hips', 'leftFoot', 'rightFoot', 'leftToes', 'rightToes', 'leftLowerLeg', 'rightLowerLeg', 'leftUpperLeg', 'rightUpperLeg']) {
      const bone = humanoid.getNormalizedBoneNode(name) || humanoid.getRawBoneNode?.(name);
      if (!bone) continue;
      bone.getWorldPosition(world);
      minY = Math.min(minY, world.y);
      maxY = Math.max(maxY, world.y);
    }
  }

  if (!Number.isFinite(minY) || !Number.isFinite(maxY) || maxY <= minY) {
    const box = new THREE.Box3().setFromObject(vrm.scene);
    if (box.isEmpty()) return;
    minY = box.min.y;
    maxY = box.max.y;
  }

  const footY = minY - 0.22;
  const headY = maxY + 0.14;
  const charH = Math.max(headY - footY, 1.2);
  const topMargin = 0.06;
  const bottomMargin = 0.2;
  const used = 1 - topMargin - bottomMargin;
  const frustumH = charH / used / userScale;
  const frustumTop = headY + frustumH * topMargin;
  const frustumBottom = frustumTop - frustumH;
  const centerY = (frustumTop + frustumBottom) / 2;
  const aspect = Math.max(window.innerWidth / Math.max(window.innerHeight, 1), 0.2);
  const halfH = frustumH / 2;
  const halfW = halfH * aspect;
  camera.left = -halfW;
  camera.right = halfW;
  camera.top = halfH;
  camera.bottom = -halfH;
  camera.near = 0.1;
  camera.far = 80;
  camera.position.set(0, centerY, 12);
  camera.lookAt(0, centerY, 0);
  camera.updateProjectionMatrix();
}

scene.add(new THREE.AmbientLight(0xffffff, 0.95));
const key = new THREE.DirectionalLight(0xfff2e0, 1.45);
key.position.set(1.5, 2.5, 2);
scene.add(key);
const fill = new THREE.DirectionalLight(0xc8ddff, 0.7);
fill.position.set(-2, 1.5, -1);
scene.add(fill);

const avatar = new VrmAvatar(scene);

function resize() {
  const w = Math.max(window.innerWidth, 1);
  const h = Math.max(window.innerHeight, 1);
  renderer.setSize(w, h, true);
  camera.aspect = w / h;
  if (avatar.vrm) frameFullBody(avatar.vrm);
  else camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);
resize();

function handleCommand(msg) {
  if (!msg || typeof msg !== 'object') return { ok: false, error: 'invalid_json' };

  switch (msg.cmd) {
    case 'play_action': {
      const result = avatar.playAction(msg.action_name);
      return { ok: result === 'ok', result, action_name: msg.action_name };
    }
    case 'play_vrma': {
      const result = avatar.playVrmaByName(msg.name, { interrupt: true });
      return { ok: result === 'ok', result, name: msg.name };
    }
    case 'ux_clip': {
      const clip = msg.clip || msg.action_name;
      const result = avatar.playAction(clip);
      return { ok: result === 'ok', result, clip };
    }
    case 'gaze': {
      avatar.setGaze(msg.event || 'idle');
      return { ok: true };
    }
    case 'viseme': {
      avatar.setViseme(msg.v || 'neutral', msg.weight ?? 0.85);
      return { ok: true };
    }
    case 'set_expression': {
      avatar.setExpression(msg.name, msg.value ?? 1);
      return { ok: true };
    }
    case 'set_scale': {
      const value = setUserScale(Number(msg.value) || 1);
      return { ok: true, scale: value };
    }
    case 'scale_by': {
      const value = setUserScale(userScale * (Number(msg.factor) || 1.12));
      return { ok: true, scale: value };
    }
    case 'ping':
      return { ok: true, pong: true };
    default:
      return { ok: false, error: 'unknown_cmd' };
  }
}

const ws = connectControlSocket({
  onStatus() {},
  onMessage(msg) {
    const result = handleCommand(msg);
    ws.send({ type: 'result', request_id: msg.request_id, ...result });
  },
});

console.log('[lulu] overlay model=/Zome.vrm');
avatar
  .load('/Zome.vrm')
  .then(() => {
    console.log('[lulu] Zome 已就绪');
    avatar.setGaze('idle');
    avatar.playAction('idle');
    avatar.vrm.scene.scale.setScalar(0.92);
    frameFullBody(avatar.vrm);
    requestAnimationFrame(() => frameFullBody(avatar.vrm));
    setTimeout(() => frameFullBody(avatar.vrm), 250);
    setTimeout(() => handleCommand({ cmd: 'play_action', action_name: 'wave' }), 500);
  })
  .catch((err) => {
    console.error(err);
  });

const hitPixel = new Uint8Array(4);
let dragging = false;
let lastIgnore = null;

function sampleHit(clientX, clientY) {
  const rect = canvas.getBoundingClientRect();
  const localX = clientX - rect.left;
  const localY = clientY - rect.top;
  const radius = Math.min(rect.width, rect.height) / 2 - 2;
  const dx = localX - rect.width / 2;
  const dy = localY - rect.height / 2;
  if (dx * dx + dy * dy > radius * radius) return false;
  const x = Math.round(localX * (canvas.width / rect.width));
  const y = Math.round(localY * (canvas.height / rect.height));
  if (x < 0 || y < 0 || x >= canvas.width || y >= canvas.height) return false;
  const gl = renderer.getContext();
  gl.readPixels(x, canvas.height - y - 1, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, hitPixel);
  return hitPixel[3] > 18;
}

function setIgnore(ignore) {
  if (!desktop || lastIgnore === ignore) return;
  lastIgnore = ignore;
  desktop.setIgnoreMouseEvents(ignore);
}

if (desktop) {
  window.addEventListener('mousemove', (e) => {
    if (dragging) {
      desktop.moveDrag({ x: e.screenX, y: e.screenY });
      return;
    }
    setIgnore(!sampleHit(e.clientX, e.clientY));
  });

  window.addEventListener('mousedown', (e) => {
    if (e.button === 2) {
      e.preventDefault();
      desktop.showMenu();
      return;
    }
    if (e.button !== 0 || !sampleHit(e.clientX, e.clientY)) return;
    dragging = true;
    setIgnore(false);
    desktop.startDrag({ x: e.screenX, y: e.screenY });
  });

  window.addEventListener('mouseup', (e) => {
    if (!dragging) return;
    dragging = false;
    desktop.endDrag();
    desktop.moveDrag({ x: e.screenX, y: e.screenY });
    setIgnore(!sampleHit(e.clientX, e.clientY));
  });

  window.addEventListener('dblclick', (e) => {
    if (!sampleHit(e.clientX, e.clientY)) return;
    desktop.startListen?.();
  });

  window.addEventListener('wheel', (e) => {
    if (!sampleHit(e.clientX, e.clientY)) return;
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.08 : 1 / 1.08;
    setUserScale(userScale * factor);
  }, { passive: false });

  window.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    desktop.showMenu();
  });

  desktop.onMenuAction((action) => handleCommand(action));
  desktop.onAgentEvent?.((event) => handleAgentEvent(event));
}

function isInsideCharacterFrame(point, bounds) {
  const w = Math.max(1, bounds.width);
  const h = Math.max(1, bounds.height);
  const dx = point.x - (bounds.x + w / 2);
  const dy = point.y - (bounds.y + h / 2);
  const radius = Math.min(w, h) / 2 - 2;
  return dx * dx + dy * dy <= radius * radius;
}

let cursorSyncInFlight = false;
async function syncGlobalCursorLook() {
  if (!desktop?.getCursorInfo || cursorSyncInFlight) return;
  cursorSyncInFlight = true;
  try {
    const info = await desktop.getCursorInfo();
    if (!info?.point || !info?.bounds) return;
    const { point, bounds } = info;
    if (!isInsideCharacterFrame(point, bounds)) {
      avatar.setMouseLook(0, 0);
      return;
    }
    const w = Math.max(1, bounds.width);
    const h = Math.max(1, bounds.height);
    const ndcX = ((point.x - bounds.x) / w) * 2 - 1;
    const ndcY = -(((point.y - bounds.y) / h) * 2 - 1);
    avatar.setMouseLook(ndcX, ndcY);
  } catch {
    /* ignore */
  } finally {
    cursorSyncInFlight = false;
  }
}

let visemeTimer = 0;
let ttsAudio = null;

function stopSpeechMotion() {
  if (visemeTimer) {
    window.clearInterval(visemeTimer);
    visemeTimer = 0;
  }
  if (ttsAudio) {
    ttsAudio.pause();
    ttsAudio = null;
  }
  avatar.setViseme('neutral', 0);
  avatar.setGaze('speaking_end');
  avatar.playAction('idle');
}

function playBase64Audio(b64, mime, { motion = 'talking', viseme = null } = {}) {
  return new Promise((resolve) => {
    const t0 = performance.now();
    if (ttsAudio) {
      ttsAudio.pause();
      ttsAudio = null;
    }
    stopViseme();
    const audio = new Audio(`data:${mime || 'audio/mpeg'};base64,${b64}`);
    ttsAudio = audio;
    const useViseme = viseme ?? motion === 'talking';
    const done = () => {
      stopViseme();
      console.log('[timing] tts_play_done', Math.round(performance.now() - t0), 'ms');
      resolve();
    };
    audio.addEventListener('playing', () => {
      avatar.setGaze('speaking_start');
      if (motion) avatar.playAction(motion);
      if (useViseme) startViseme();
      console.log('[timing] tts_audio_playing', Math.round(performance.now() - t0), 'ms');
    }, { once: true });
    audio.addEventListener('ended', done);
    audio.addEventListener('error', done);
    audio.play().catch(done);
  });
}

function startViseme() {
  if (visemeTimer) window.clearInterval(visemeTimer);
  let i = 0;
  visemeTimer = window.setInterval(() => {
    avatar.setViseme(VISEMES[i % VISEMES.length], 0.85);
    i += 1;
  }, 140);
}

function stopViseme() {
  if (visemeTimer) {
    window.clearInterval(visemeTimer);
    visemeTimer = 0;
  }
  avatar.setViseme('neutral', 0);
}

const mpegStream = {
  ms: null,
  sb: null,
  queue: [],
  ended: false,
  fallback: [],
  waiting: null,
  useFallback: false,
};

function concatBytes(parts) {
  let total = 0;
  for (const p of parts) total += p.length;
  const out = new Uint8Array(total);
  let o = 0;
  for (const p of parts) {
    out.set(p, o);
    o += p.length;
  }
  return out;
}

function bytesToB64(u8) {
  let bin = '';
  const step = 0x8000;
  for (let i = 0; i < u8.length; i += step) {
    bin += String.fromCharCode(...u8.subarray(i, i + step));
  }
  return btoa(bin);
}

function flushMpeg() {
  if (!mpegStream.sb || mpegStream.sb.updating) return;
  if (mpegStream.queue.length) {
    mpegStream.sb.appendBuffer(mpegStream.queue.shift());
    return;
  }
  if (mpegStream.ended && mpegStream.ms && mpegStream.ms.readyState === 'open') {
    try { mpegStream.ms.endOfStream(); } catch { /* already ended */ }
  }
}

function beginMpegStream() {
  console.log('[timing] tts_stream_begin');
  if (ttsAudio) {
    ttsAudio.pause();
    ttsAudio = null;
  }
  stopViseme();
  mpegStream.queue = [];
  mpegStream.ended = false;
  mpegStream.fallback = [];
  mpegStream.sb = null;
  mpegStream.ms = null;
  mpegStream.useFallback = !(window.MediaSource && MediaSource.isTypeSupported('audio/mpeg'));
  if (mpegStream.useFallback) {
    mpegStream.waiting = null;
    return;
  }
  const ms = new MediaSource();
  const audio = new Audio();
  mpegStream.ms = ms;
  ttsAudio = audio;
  audio.src = URL.createObjectURL(ms);
  audio.addEventListener('playing', () => {
    avatar.setGaze('speaking_start');
    avatar.playAction('talking');
    startViseme();
    console.log('[timing] tts_stream_playing');
  }, { once: true });
  mpegStream.waiting = new Promise((resolve) => {
    const done = () => resolve();
    audio.addEventListener('ended', done, { once: true });
    audio.addEventListener('error', done, { once: true });
  });
  ms.addEventListener('sourceopen', () => {
    try {
      mpegStream.sb = ms.addSourceBuffer('audio/mpeg');
      mpegStream.sb.mode = 'sequence';
      mpegStream.sb.addEventListener('updateend', flushMpeg);
      flushMpeg();
    } catch {
      mpegStream.useFallback = true;
    }
  }, { once: true });
}

function appendMpeg(b64) {
  const binary = atob(b64);
  const u8 = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) u8[i] = binary.charCodeAt(i);
  if (mpegStream.useFallback) {
    mpegStream.fallback.push(u8);
    return;
  }
  mpegStream.queue.push(u8);
  flushMpeg();
  if (ttsAudio && ttsAudio.paused) ttsAudio.play().catch(() => {});
}

async function endMpegStream() {
  mpegStream.ended = true;
  if (mpegStream.useFallback) {
    const all = [...mpegStream.fallback, ...mpegStream.queue];
    if (all.length) await playBase64Audio(bytesToB64(concatBytes(all)), 'audio/mpeg');
    return;
  }
  flushMpeg();
  if (mpegStream.waiting) {
    await Promise.race([
      mpegStream.waiting,
      new Promise((r) => window.setTimeout(r, 12000)),
    ]);
  }
}

function handleAgentEvent(event) {
  if (!event || typeof event !== 'object') return;
  if (event.phase === 'listening') {
    avatar.setGaze('listening_start');
    avatar.playAction('blush');
    return;
  }
  if (event.phase === 'idle') {
    stopSpeechMotion();
    return;
  }
  if (event.phase === 'thinking') {
    // 害羞进行中不要被思考动画打断，否则「你好」的动作会中途错乱
    if (avatar.currentAction === 'blush') return;
    stopSpeechMotion();
    avatar.setGaze('thinking_start');
    avatar.playAction('thinking');
    return;
  }
  if (event.phase === 'error') {
    stopSpeechMotion();
    avatar.setGaze('idle');
    avatar.playAction('shrug');
    desktop.speechDone?.();
    return;
  }
  if (event.phase === 'reply') {
    // 口型/说话动作等真正出声再开，避免「嘴先动、声后到」
    (async () => {
      if (event.tts_audio_base64) {
        // 问候：让害羞播完，只动嘴，不要切成 talking 把它掐掉
        if (event.route === 'greet') {
          await playBase64Audio(event.tts_audio_base64, 'audio/mpeg', {
            motion: null,
            viseme: true,
          });
        } else {
          await playBase64Audio(event.tts_audio_base64, 'audio/mpeg');
        }
      }
      if (event.song_audio_base64) {
        await playBase64Audio(event.song_audio_base64, 'audio/mpeg', { motion: 'groove' });
      }
      if (!event.tts_audio_base64 && !event.song_audio_base64) {
        await new Promise((r) => window.setTimeout(r, 1600));
      }
      stopSpeechMotion();
      desktop.speechDone?.();
    })();
    return;
  }
  if (event.phase === 'reply-stream') {
    beginMpegStream();
    return;
  }
  if (event.phase === 'tts-chunk' && event.b64) {
    appendMpeg(event.b64);
    return;
  }
  if (event.phase === 'tts-end') {
    (async () => {
      await endMpegStream();
      if (event.song_audio_base64) {
        await playBase64Audio(event.song_audio_base64, 'audio/mpeg', { motion: 'groove' });
      }
      stopSpeechMotion();
      desktop.speechDone?.();
    })();
  }
}

function frame() {
  requestAnimationFrame(frame);
  syncGlobalCursorLook();
  avatar.update();
  renderer.render(scene, camera);
}
frame();

window.lulu = {
  play: (action_name) => handleCommand({ cmd: 'play_action', action_name }),
  ux: (clip) => handleCommand({ cmd: 'ux_clip', clip }),
  gaze: (event) => handleCommand({ cmd: 'gaze', event }),
  viseme: (v) => handleCommand({ cmd: 'viseme', v }),
  scale: (value) => handleCommand({ cmd: 'set_scale', value }),
};
