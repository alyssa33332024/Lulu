/**
 * 右键菜单展示的全部开源 VRMA（tk256ailab/vrm-viewer，MIT）。
 * label 给人看，vrma 对应 public/vrma/{vrma}.vrma。
 */
export const MENU_VRMA = [
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

/**
 * 精简动作表。
 * 有 openVrma 的动作优先播 public/vrma/*.vrma；
 * 失败或无文件时回退程序动作。
 *
 * 映射：wave→Goodbye | thinking→Thinking | excited→Surprised
 * idle/talking 故意不用 VRMA，方便鼠标跟随。
 * talking / shrug / groove：产品链路必需，暂用轻量程序动作。
 */
export const ACTION_TABLE = {
  idle: {
    label: '待机',
    track: 'action',
    durationMs: 0,
    loop: true,
    kind: 'idle',
    openVrma: null,
  },
  wave: {
    label: '挥手打招呼',
    track: 'action',
    durationMs: 2400,
    loop: false,
    kind: 'procedural',
    motion: 'wave',
    openVrma: 'Goodbye',
  },
  blush: {
    label: '害羞',
    track: 'ux',
    durationMs: 2200,
    loop: false,
    kind: 'procedural',
    motion: 'peek',
    openVrma: 'Blush',
  },
  talking: {
    label: '说话',
    track: 'ux',
    durationMs: 0,
    loop: true,
    kind: 'talk',
    openVrma: null,
  },
  thinking: {
    label: '思考',
    track: 'ux',
    durationMs: 2800,
    loop: false,
    kind: 'procedural',
    motion: 'peek',
    openVrma: 'Thinking',
  },
  excited: {
    label: '小兴奋',
    track: 'ux',
    durationMs: 1800,
    loop: false,
    kind: 'procedural',
    motion: 'excited',
    openVrma: 'Surprised',
  },
  shrug: {
    label: '不知道呀',
    track: 'ux',
    durationMs: 1600,
    loop: false,
    kind: 'procedural',
    motion: 'shrug',
    openVrma: null,
  },
  groove: {
    label: '听歌微晃',
    track: 'ux',
    durationMs: 0,
    loop: true,
    kind: 'procedural',
    motion: 'groove',
    openVrma: null,
  },
};

/** 技能场景 → 上面保留的动作 */
export const SKILL_UX_HOOKS = {
  chat: {
    idle: 'idle',
    speaking: 'talking',
    happy: 'excited',
    unknown: 'shrug',
    agree: 'wave',
    react: 'excited',
  },
  weather: {
    thinking: 'thinking',
    sunny: 'excited',
    speaking: 'talking',
  },
  reminder: {
    thinking: 'thinking',
    success: 'excited',
    need_slot: 'shrug',
    speaking: 'talking',
  },
  sing: {
    searching: 'thinking',
    playing: 'groove',
    encore: 'wave',
    speaking: 'talking',
  },
  device_action: {},
};

export const GAZE_EVENTS = [
  'idle',
  'listening_start',
  'thinking_start',
  'tool_pending',
  'speaking_start',
  'speaking_end',
];

export const VISEMES = ['aa', 'ih', 'ou', 'ee', 'oh', 'neutral'];

export function listActionNames() {
  return Object.entries(ACTION_TABLE)
    .filter(([, def]) => def.track === 'action')
    .map(([name]) => name);
}

export function listUxClipNames() {
  return Object.entries(ACTION_TABLE)
    .filter(([, def]) => def.track === 'ux')
    .map(([name]) => name);
}
