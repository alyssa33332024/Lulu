const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('luluDesktop', {
  isOverlay: true,
  setIgnoreMouseEvents(ignore) {
    ipcRenderer.send('ignore-mouse', ignore);
  },
  startDrag(point) {
    ipcRenderer.send('drag-start', point);
  },
  moveDrag(point) {
    ipcRenderer.send('drag-move', point);
  },
  endDrag() {
    ipcRenderer.send('drag-end');
  },
  showMenu() {
    ipcRenderer.send('show-menu');
  },
  startListen() {
    ipcRenderer.send('start-listen');
  },
  speechDone() {
    ipcRenderer.send('speech-done');
  },
  getCursorInfo() {
    return ipcRenderer.invoke('get-cursor-info');
  },
  pingBrain() {
    return ipcRenderer.invoke('ping-brain');
  },
  askBrain(query) {
    return ipcRenderer.invoke('ask-brain', query);
  },
  recognize(pcmB64, mode) {
    return ipcRenderer.invoke('recognize-audio', pcmB64, mode);
  },
  asrStart(mode) {
    ipcRenderer.send('asr-start', mode || 'wake');
  },
  asrPush(pcmB64) {
    ipcRenderer.send('asr-push', pcmB64);
  },
  asrCancel() {
    ipcRenderer.send('asr-cancel');
  },
  asrEnd() {
    return ipcRenderer.invoke('asr-end');
  },
  voiceState(state) {
    ipcRenderer.send('voice-state', state);
  },
  onMenuAction(callback) {
    ipcRenderer.on('menu-action', (_event, action) => callback(action));
  },
  onAgentEvent(callback) {
    ipcRenderer.on('agent-event', (_event, event) => callback(event));
  },
  onTtsState(callback) {
    ipcRenderer.on('tts-state', (_event, busy) => callback(busy));
  },
  onForceListen(callback) {
    ipcRenderer.on('force-listen', () => callback());
  },
});
