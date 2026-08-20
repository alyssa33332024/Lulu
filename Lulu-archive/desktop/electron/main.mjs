import { app, BrowserWindow, ipcMain, Menu, Tray, nativeImage, screen, Notification, session } from 'electron';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import WebSocket from 'ws';

app.commandLine.appendSwitch('enable-transparent-visuals');
app.commandLine.appendSwitch('use-fake-ui-for-media-stream');
app.commandLine.appendSwitch('disable-renderer-backgrounding');
app.commandLine.appendSwitch('disable-background-timer-throttling');
app.commandLine.appendSwitch('disable-backgrounding-occluded-windows');
app.commandLine.appendSwitch('disable-features', [
  'Windows11OverrideTitlebarCaption',
  'Windows11MicaTitlebar',
  'Windows11BorderColor',
].join(','));
Menu.setApplicationMenu(null);

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const VIEWER_URL = 'http://127.0.0.1:5173/?mode=overlay';
const VOICE_URL = 'http://127.0.0.1:5173/voice.html';
const BRAIN_URL = 'http://127.0.0.1:8000';
const ASR_WS_URL = 'ws://127.0.0.1:8000/api/asr/stream';
const TRAY_ICON = path.resolve(__dirname, '../assets/I_Zome.png');

let win = null;
let voiceWin = null;
let tray = null;
let dragOffset = null;
let sessionId = null;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForViewer() {
  for (let i = 0; i < 80; i++) {
    try {
      const res = await fetch('http://127.0.0.1:5173/?mode=overlay', { cache: 'no-store' });
      if (res.ok) return;
    } catch {
      /* vite 还没起来 */
    }
    await sleep(250);
  }
  throw new Error('Vite 未在 127.0.0.1:5173 启动');
}

function killGhostCaption(window) {
  if (!window || window.isDestroyed()) return;
  try {
    window.setMaximizable(false);
    window.setMinimizable(false);
    window.setResizable(false);
    const [w, h] = window.getSize();
    window.setSize(w, h + 1);
    window.setSize(w, h);
  } catch {
    /* ignore */
  }
}

function overlaySize() {
  const area = screen.getPrimaryDisplay().workArea;
  const size = Math.min(560, Math.max(360, Math.floor(Math.min(area.width, area.height) * 0.58)));
  return { width: size, height: size, area };
}

function placeBottomRight(window) {
  const { width, height, area } = overlaySize();
  const x = area.x + area.width - width - 8;
  const y = area.y + area.height - height;
  window.setBounds({ x, y, width, height });
}

function sendPet(event) {
  if (win && !win.isDestroyed()) win.webContents.send('agent-event', event);
}

function sendVoice(channel, payload) {
  if (voiceWin && !voiceWin.isDestroyed()) voiceWin.webContents.send(channel, payload);
}

/** 与 src/actions.js MENU_VRMA 保持一致（主进程不 import 渲染侧模块） */
const MENU_VRMA = [
  { label: '生气', vrma: 'Angry' },
  { label: '害羞', vrma: 'Blush' },
  { label: '鼓掌', vrma: 'Clapping' },
  { label: '挥手打招呼', vrma: 'Goodbye' },
  { label: '跳跃', vrma: 'Jump' },
  { label: '左顾右盼', vrma: 'LookAround' },
  { label: '放松', vrma: 'Relax' },
  { label: '难过', vrma: 'Sad' },
  { label: '犯困', vrma: 'Sleepy' },
  { label: '惊讶', vrma: 'Surprised' },
  { label: '思考', vrma: 'Thinking' },
];

function buildMenu() {
  const vrmaItems = MENU_VRMA.map(({ label, vrma }) => ({
    label,
    click: () => win?.webContents.send('menu-action', { cmd: 'play_vrma', name: vrma }),
  }));

  return Menu.buildFromTemplate([
    { label: '开始听（说完再停）', click: () => sendVoice('force-listen') },
    { type: 'separator' },
    ...vrmaItems,
    { type: 'separator' },
    { label: '放大', click: () => win?.webContents.send('menu-action', { cmd: 'scale_by', factor: 1.12 }) },
    { label: '缩小', click: () => win?.webContents.send('menu-action', { cmd: 'scale_by', factor: 1 / 1.12 }) },
    { label: '重置大小', click: () => win?.webContents.send('menu-action', { cmd: 'set_scale', value: 1 }) },
    { type: 'separator' },
    {
      label: '始终置顶',
      type: 'checkbox',
      checked: true,
      click: (item) => win?.setAlwaysOnTop(item.checked, 'screen-saver'),
    },
    { type: 'separator' },
    { label: '退出 LuLu', click: () => app.quit() },
  ]);
}

function createTray() {
  let image = nativeImage.createFromPath(TRAY_ICON);
  if (image.isEmpty()) image = nativeImage.createEmpty();
  else image = image.resize({ width: 16, height: 16 });
  tray = new Tray(image);
  tray.setToolTip('LuLu · 说「你好」或「LuLu」唤醒');
  tray.setContextMenu(buildMenu());
  tray.on('click', () => win?.show());
}

async function createWindow() {
  await waitForViewer();

  const { width, height } = overlaySize();
  win = new BrowserWindow({
    width,
    height,
    title: '',
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    maximizable: false,
    minimizable: false,
    fullscreenable: false,
    hasShadow: false,
    thickFrame: false,
    autoHideMenuBar: true,
    roundedCorners: false,
    backgroundColor: '#00000000',
    show: false,
    focusable: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      backgroundThrottling: false,
    },
  });

  win.setMenu(null);
  win.setTitle('');
  win.setAlwaysOnTop(true, 'screen-saver');
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  win.setIgnoreMouseEvents(true, { forward: true });
  win.on('page-title-updated', (event) => {
    event.preventDefault();
    win?.setTitle('');
  });
  win.on('blur', () => killGhostCaption(win));
  win.on('focus', () => killGhostCaption(win));
  placeBottomRight(win);

  win.webContents.on('console-message', (_e, _level, message) => {
    console.log('[renderer]', message);
  });
  win.webContents.on('did-fail-load', (_e, code, desc) => {
    console.error('[electron] load failed', code, desc);
  });

  await win.loadURL(VIEWER_URL);
  win.setTitle('');
  placeBottomRight(win);
  win.showInactive();
  killGhostCaption(win);
  setTimeout(() => killGhostCaption(win), 50);
  setTimeout(() => killGhostCaption(win), 300);
  placeBottomRight(win);
  console.log('[electron] overlay shown', win.getBounds());
}

async function createVoiceWindow() {
  voiceWin = new BrowserWindow({
    width: 80,
    height: 80,
    show: false,
    skipTaskbar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      backgroundThrottling: false,
      sandbox: false,
    },
  });
  voiceWin.setMenu(null);
  voiceWin.webContents.setBackgroundThrottling(false);
  voiceWin.setIgnoreMouseEvents(true);
  voiceWin.setOpacity(0);
  voiceWin.webContents.on('console-message', (_e, _level, message) => {
    console.log('[voice]', message);
  });
  await voiceWin.loadURL(VOICE_URL);
  voiceWin.showInactive();
}

function fileToBase64(filePath) {
  if (!filePath) return null;
  const cleaned = String(filePath).replace(/^file:\/+/, '');
  if (!fs.existsSync(cleaned)) return null;
  return fs.readFileSync(cleaned).toString('base64');
}

ipcMain.on('ignore-mouse', (_event, ignore) => {
  if (!win) return;
  if (dragOffset) return;
  win.setIgnoreMouseEvents(Boolean(ignore), { forward: true });
});

ipcMain.on('drag-start', (event, point) => {
  const target = BrowserWindow.fromWebContents(event.sender);
  if (!target || !point) return;
  const [wx, wy] = target.getPosition();
  dragOffset = { x: point.x - wx, y: point.y - wy };
  target.setIgnoreMouseEvents(false);
});

ipcMain.on('drag-move', (event, point) => {
  const target = BrowserWindow.fromWebContents(event.sender);
  if (!target || !dragOffset || !point) return;
  target.setPosition(Math.round(point.x - dragOffset.x), Math.round(point.y - dragOffset.y));
});

ipcMain.on('drag-end', () => {
  dragOffset = null;
});

ipcMain.on('show-menu', () => {
  if (!win) return;
  buildMenu().popup({ window: win });
});

ipcMain.on('start-listen', () => sendVoice('force-listen'));

ipcMain.on('speech-done', () => sendVoice('tts-state', false));

ipcMain.on('voice-state', (_event, state) => {
  if (state === 'listening') sendPet({ phase: 'listening' });
  if (state === 'idle') sendPet({ phase: 'idle' });
  if (state === 'mic-denied' || state === 'no-speech-api') {
    new Notification({
      title: 'LuLu',
      body: '麦克风或语音识别不可用。请在系统设置里允许桌面应用使用麦克风。',
    }).show();
  }
});

ipcMain.handle('get-cursor-info', () => {
  if (!win || win.isDestroyed()) return null;
  return {
    point: screen.getCursorScreenPoint(),
    bounds: win.getBounds(),
  };
});

let asrWs = null;
let asrQueue = [];
let asrOpen = false;
let asrWaiter = null;

function closeAsr(sendCancel = false) {
  if (asrWaiter) {
    const { resolve } = asrWaiter;
    asrWaiter = null;
    resolve('');
  }
  if (asrWs) {
    try {
      if (sendCancel && asrWs.readyState === WebSocket.OPEN) {
        asrWs.send(JSON.stringify({ event: 'cancel' }));
      }
      asrWs.close();
    } catch {
      // ignore
    }
    asrWs = null;
  }
  asrQueue = [];
  asrOpen = false;
}

ipcMain.on('asr-start', () => {
  console.log('[timing] asr_ws_start');
  closeAsr(true);
  asrQueue = [];
  asrOpen = false;
  const socket = new WebSocket(ASR_WS_URL);
  asrWs = socket;
  socket.on('open', () => {
    if (asrWs !== socket) return;
    asrOpen = true;
    console.log('[timing] asr_ws_open queued=', asrQueue.length);
    for (const buf of asrQueue) socket.send(buf);
    asrQueue = [];
  });
  socket.on('message', (data) => {
    let parsed;
    try {
      parsed = JSON.parse(String(data));
    } catch {
      return;
    }
    if (!asrWaiter) return;
    const { resolve, reject } = asrWaiter;
    asrWaiter = null;
    if (parsed.error) reject(new Error(String(parsed.error)));
    else resolve(String(parsed.text || '').trim());
  });
  socket.on('error', () => {
    if (!asrWaiter) return;
    const { reject } = asrWaiter;
    asrWaiter = null;
    reject(new Error('asr_stream_failed'));
  });
  socket.on('close', () => {
    if (asrWs === socket) {
      asrWs = null;
      asrOpen = false;
    }
  });
});

ipcMain.on('asr-push', (_event, b64) => {
  if (!b64) return;
  const buf = Buffer.from(String(b64), 'base64');
  if (asrOpen && asrWs?.readyState === WebSocket.OPEN) asrWs.send(buf);
  else asrQueue.push(buf);
});

ipcMain.on('asr-cancel', () => closeAsr(true));

ipcMain.handle('asr-end', async () => {
  const t0 = Date.now();
  if (!asrWs) throw new Error('asr_stream_closed');
  const socket = asrWs;
  try {
    const text = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('asr_stream_timeout')), 8000);
      asrWaiter = {
        resolve: (text) => {
          clearTimeout(timer);
          resolve(text);
        },
        reject: (err) => {
          clearTimeout(timer);
          reject(err);
        },
      };
      try {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ event: 'end' }));
        } else if (socket.readyState === WebSocket.CONNECTING) {
          socket.once('open', () => {
            if (asrWs !== socket) return;
            asrOpen = true;
            for (const buf of asrQueue) socket.send(buf);
            asrQueue = [];
            socket.send(JSON.stringify({ event: 'end' }));
          });
        } else {
          clearTimeout(timer);
          asrWaiter = null;
          reject(new Error('asr_stream_closed'));
        }
      } catch (err) {
        clearTimeout(timer);
        asrWaiter = null;
        reject(err);
      }
    });
    console.log('[timing] asr_ws_end', Date.now() - t0, 'ms text=', text);
    return text;
  } finally {
    closeAsr(false);
  }
});

ipcMain.handle('recognize-audio', async (_event, pcmB64, mode) => {
  const t0 = Date.now();
  const res = await fetch(`${BRAIN_URL}/api/asr`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pcm_b64: pcmB64, mode: mode || 'wake' }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `asr HTTP ${res.status}`);
  }
  const body = await res.json();
  const text = String(body.text || '').trim();
  console.log('[timing] asr_http', Date.now() - t0, 'ms text=', text);
  return text;
});

ipcMain.handle('ping-brain', async () => {
  try {
    const res = await fetch(`${BRAIN_URL}/health`, { cache: 'no-store' });
    if (!res.ok) return false;
    const body = await res.json();
    return body?.status === 'UP';
  } catch {
    return false;
  }
});

ipcMain.handle('ask-brain', async (_event, query) => {
  const text = String(query || '').trim();
  if (!text) return { error: 'empty' };
  sendVoice('tts-state', true);
  sendPet({ phase: 'thinking' });
  const t0 = Date.now();
  try {
    const res = await fetch(`${BRAIN_URL}/api/turn/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: text,
        session_id: sessionId,
        with_tts: false,
      }),
    });
    if (!res.ok) {
      sendPet({ phase: 'error' });
      sendVoice('tts-state', false);
      console.log('[timing] turn_stream', Date.now() - t0, 'ms error=', res.status);
      return { error: `大脑 HTTP ${res.status}`, reply: '我这边有点连不上大脑，稍后再试。' };
    }

    let data = {
      session_id: sessionId,
      route: 'chat',
      reply: '',
      play_song_path: null,
      tts_audio_base64: null,
    };
    let streamUiStarted = false;
    let firstSentenceAt = 0;
    let ttsChain = Promise.resolve();
    let song_audio_base64 = null;

    const playSentenceTts = (sentence) => {
      const piece = String(sentence || '').trim();
      if (!piece) return;
      ttsChain = ttsChain.then(async () => {
        if (!streamUiStarted) {
          streamUiStarted = true;
          sendPet({
            phase: 'reply-stream',
            route: data.route,
            play_song: Boolean(data.play_song_path),
          });
          console.log('[timing] tts_kickoff_after_sentence', Date.now() - t0, 'ms text=', piece.slice(0, 40));
        }
        const tTts = Date.now();
        let firstChunk = true;
        const ttsRes = await fetch(`${BRAIN_URL}/api/tts/stream`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: piece }),
        });
        if (ttsRes.ok && ttsRes.body) {
          const reader = ttsRes.body.getReader();
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            if (value && value.length) {
              if (firstChunk) {
                console.log('[timing] tts_first_chunk', Date.now() - tTts, 'ms since_ask=', Date.now() - t0, 'ms');
                firstChunk = false;
              }
              sendPet({ phase: 'tts-chunk', b64: Buffer.from(value).toString('base64') });
            }
          }
        }
        console.log('[timing] tts_sentence', Date.now() - tTts, 'ms chars=', piece.length);
      }).catch((err) => {
        console.log('[timing] tts_sentence_fail', String(err));
      });
    };

    const reader = res.body?.getReader();
    if (!reader) throw new Error('no_stream_body');
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line) continue;
        let event;
        try {
          event = JSON.parse(line);
        } catch {
          continue;
        }
        if (event.type === 'route') {
          data.route = event.route || data.route;
          if (event.session_id) {
            sessionId = event.session_id;
            data.session_id = event.session_id;
          }
          console.log('[timing] turn_route', Date.now() - t0, 'ms route=', data.route);
        } else if (event.type === 'sentence') {
          if (!firstSentenceAt) {
            firstSentenceAt = Date.now() - t0;
            console.log('[timing] first_sentence', firstSentenceAt, 'ms text=', String(event.text || '').slice(0, 40));
          }
          playSentenceTts(event.text);
        } else if (event.type === 'done') {
          data = { ...data, ...event };
          if (data.session_id) sessionId = data.session_id;
          song_audio_base64 = fileToBase64(data.play_song_path);
          console.log(
            '[timing] turn_done',
            Date.now() - t0,
            'ms route=',
            data.route,
            'reply=',
            String(data.reply || '').slice(0, 40),
          );
          if (data.tts_audio_base64 && data.route === 'greet') {
            // 问候走缓存整段音频，不再逐句 TTS
            await ttsChain;
            sendPet({
              phase: 'reply',
              route: data.route,
              play_song: Boolean(data.play_song_path),
              tts_audio_base64: data.tts_audio_base64,
              song_audio_base64,
            });
            console.log('[timing] voice_roundtrip', Date.now() - t0, 'ms query=', text);
            return data;
          }
        } else if (event.type === 'error') {
          throw new Error(event.error || 'turn_stream_error');
        }
      }
    }

    await ttsChain;
    if (!streamUiStarted && data.reply) {
      // 技能路径等：整段一句
      playSentenceTts(data.reply);
      await ttsChain;
    }
    sendPet({ phase: 'tts-end', song_audio_base64 });
    console.log('[timing] voice_roundtrip', Date.now() - t0, 'ms query=', text);
    return data;
  } catch {
    sendPet({ phase: 'error' });
    sendVoice('tts-state', false);
    console.log('[timing] turn_stream_fail', Date.now() - t0, 'ms');
    return { error: '大脑未启动', reply: '大脑还没连上。请先启动 lulu-agent（127.0.0.1:8000）。' };
  }
});

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => win?.show());
  app.whenReady().then(async () => {
    session.defaultSession.setPermissionRequestHandler((_wc, permission, callback) => {
      callback(permission === 'media' || permission === 'microphone' || permission === 'audioCapture');
    });
    session.defaultSession.setPermissionCheckHandler((_wc, permission) => (
      permission === 'media' || permission === 'microphone' || permission === 'audioCapture'
    ));
    createTray();
    await createWindow();
    await createVoiceWindow();
  });
  app.on('window-all-closed', () => app.quit());
}
