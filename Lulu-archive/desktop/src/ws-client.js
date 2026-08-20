const WS_URL = 'ws://127.0.0.1:8787';

/**
 * 浏览器连本地控制通道。
 * Agent / 调试脚本也可以直接连同一个 ws-server，向所有 viewer 广播指令。
 */
export function connectControlSocket({ onStatus, onMessage }) {
  let socket = null;
  let retryMs = 800;

  function connect() {
    onStatus('连接中…');
    socket = new WebSocket(WS_URL);

    socket.addEventListener('open', () => {
      retryMs = 800;
      onStatus('已连接 :8787');
      socket.send(JSON.stringify({ type: 'hello', role: 'viewer' }));
    });

    socket.addEventListener('close', () => {
      onStatus('已断开，重连中…');
      setTimeout(connect, retryMs);
      retryMs = Math.min(retryMs * 1.5, 5000);
    });

    socket.addEventListener('error', () => {
      // close 会触发重连
    });

    socket.addEventListener('message', (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === 'welcome' || msg.type === 'result') return;
        onMessage(msg);
      } catch (err) {
        console.warn('bad ws message', err);
      }
    });
  }

  connect();

  return {
    send(obj) {
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify(obj));
      }
    },
  };
}
