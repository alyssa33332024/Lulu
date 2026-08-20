import { WebSocketServer } from 'ws';

const PORT = 8787;
const wss = new WebSocketServer({ host: '127.0.0.1', port: PORT });

/** @type {Set<import('ws').WebSocket>} */
const viewers = new Set();
/** @type {Set<import('ws').WebSocket>} */
const agents = new Set();

function send(ws, obj) {
  if (ws.readyState === ws.OPEN) ws.send(JSON.stringify(obj));
}

function broadcastViewers(obj, except = null) {
  const raw = JSON.stringify(obj);
  for (const ws of viewers) {
    if (ws !== except && ws.readyState === ws.OPEN) ws.send(raw);
  }
}

wss.on('connection', (ws) => {
  let role = 'unknown';

  send(ws, {
    type: 'welcome',
    port: PORT,
    protocol: [
      '{ "cmd": "play_action", "action_name": "wave" }',
      '{ "cmd": "gaze", "event": "thinking_start" }',
      '{ "cmd": "viseme", "v": "aa" }',
      '{ "cmd": "set_expression", "name": "happy", "value": 0.6 }',
    ],
  });

  ws.on('message', (buf) => {
    let msg;
    try {
      msg = JSON.parse(String(buf));
    } catch {
      send(ws, { type: 'error', error: 'invalid_json' });
      return;
    }

    if (msg.type === 'hello') {
      role = msg.role === 'agent' ? 'agent' : 'viewer';
      if (role === 'viewer') viewers.add(ws);
      else agents.add(ws);
      send(ws, { type: 'hello_ack', role });
      return;
    }

    // viewer 回传执行结果给 agent
    if (msg.type === 'result') {
      for (const agent of agents) send(agent, msg);
      return;
    }

    // 带 cmd 的指令：广播给所有 viewer（Agent 或调试端发来）
    if (msg.cmd) {
      broadcastViewers(msg);
      // 若发送者不是 viewer，也回一个已接受
      if (!viewers.has(ws)) {
        send(ws, { type: 'accepted', request_id: msg.request_id, cmd: msg.cmd });
      }
      return;
    }

    send(ws, { type: 'error', error: 'unknown_message' });
  });

  ws.on('close', () => {
    viewers.delete(ws);
    agents.delete(ws);
  });
});

console.log(`[lulu-ws] listening on ws://127.0.0.1:${PORT}`);
console.log('[lulu-ws] example: {"cmd":"play_action","action_name":"wave"}');
