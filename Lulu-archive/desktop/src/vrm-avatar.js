import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';
import {
  VRMAnimationLoaderPlugin,
  createVRMAnimationClip,
} from '@pixiv/three-vrm-animation';
import { ACTION_TABLE, MENU_VRMA } from './actions.js';

const VRMA_BASE = '/vrma';
const CROSSFADE_SEC = 0.35;

/**
 * VRM 形象运行时：加载模型、待机呼吸、眨眼、眼神、VRMA / 程序化动作。
 * Agent 侧只关心 play_action / gaze / viseme，不关心 Three 细节。
 */
export class VrmAvatar {
  constructor(scene) {
    this.scene = scene;
    this.vrm = null;
    this.mixer = null;
    this.clock = new THREE.Clock();
    this.lookAtTarget = new THREE.Object3D();
    this.scene.add(this.lookAtTarget);

    this.currentAction = 'idle';
    this.actionBusyUntil = 0;
    this.blinkTimer = 0;
    this.nextBlinkIn = 2 + Math.random() * 3;
    this.gazeEvent = 'idle';
    this.baseYaw = 0;
    this.motion = null;
    /** @type {THREE.AnimationAction | null} */
    this.vrmaAction = null;
    /** @type {Map<string, THREE.AnimationClip>} name → clip */
    this.vrmaClips = new Map();
    this.visemeWeights = { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 };
    /** 屏幕归一化鼠标：-1..1，用于明显的 LookAt 跟随 */
    this.mouseNdc = { x: 0, y: 0 };
    this.mouseSmooth = { x: 0, y: 0 };
    this.mouseFollowEnabled = true;
  }

  async load(url) {
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    loader.register((parser) => new VRMAnimationLoaderPlugin(parser));
    this._gltfLoader = loader;

    const gltf = await loader.loadAsync(url);
    console.log('[vrm] 模型文件已加载');
    const vrm = gltf.userData.vrm;
    if (!vrm) throw new Error('未解析到 VRM 数据，请确认模型文件有效');
    console.log('[vrm] VRM 对象就绪', vrm.meta?.title || vrm.meta?.name || '');

    try {
      VRMUtils.removeUnnecessaryVertices(gltf.scene);
      VRMUtils.combineSkeletons(gltf.scene);
    } catch (err) {
      console.warn('[vrm] 网格优化跳过', err);
    }
    console.log('[vrm] 加入场景');

    vrm.scene.rotation.y = Math.PI;
    this.baseYaw = Math.PI;
    this.scene.add(vrm.scene);
    this.vrm = vrm;
    this.mixer = new THREE.AnimationMixer(vrm.scene);

    if (vrm.lookAt) {
      vrm.lookAt.target = this.lookAtTarget;
    }

    // 站立髋高：VRMA 位移轨道要以它为基准，否则播动画时人会整体抬起
    const restHips = vrm.humanoid?.getNormalizedBoneNode('hips');
    this.restHipsPos = restHips ? restHips.position.clone() : null;

    this.lookAtTarget.position.set(0, 1.4, 1.2);
    this.applyRestPose();
    vrm.scene.updateMatrixWorld(true);

    // 预加载菜单全部 VRMA + 动作表引用（来自 tk256ailab/vrm-viewer）
    const names = [
      ...new Set([
        ...MENU_VRMA.map((x) => x.vrma),
        ...Object.values(ACTION_TABLE)
          .map((d) => d.openVrma)
          .filter(Boolean),
      ]),
    ];
    await Promise.all(names.map((n) => this.ensureVrmaClip(n).catch((e) => {
      console.warn(`[vrm] VRMA 预载失败 ${n}`, e);
    })));
    console.log('[vrm] VRMA 已就绪', [...this.vrmaClips.keys()]);
    return vrm;
  }

  /**
   * 按 VRMA 文件名直接播放（右键菜单用）。可打断当前动作。
   * @param {string} vrmaName 如 Goodbye
   * @returns {'ok'|'unknown_action'}
   */
  playVrmaByName(vrmaName, { interrupt = true } = {}) {
    if (!vrmaName || !this.vrmaClips.has(vrmaName)) return 'unknown_action';
    if (interrupt) {
      this.motion = null;
      this.actionBusyUntil = 0;
    } else if (this.busy) {
      return 'renderer_busy';
    }
    this.currentAction = `vrma:${vrmaName}`;
    const ok = this.playVrmaClip(vrmaName, { loop: false, durationMs: 0 });
    return ok ? 'ok' : 'unknown_action';
  }

  /**
   * @param {string} name 不含扩展名，如 Goodbye
   * @returns {Promise<THREE.AnimationClip | null>}
   */
  async ensureVrmaClip(name) {
    if (!name || !this.vrm || !this._gltfLoader) return null;
    if (this.vrmaClips.has(name)) return this.vrmaClips.get(name);

    const gltf = await this._gltfLoader.loadAsync(`${VRMA_BASE}/${name}.vrma`);
    const data = gltf.userData.vrmAnimations?.[0];
    if (!data) throw new Error(`无 VRMA 数据: ${name}`);
    const clip = createVRMAnimationClip(data, this.vrm);
    if (!clip) throw new Error(`无法生成 clip: ${name}`);
    this.rebaseRootMotion(clip);
    this.vrmaClips.set(name, clip);
    return clip;
  }

  /**
   * 把髋/根位移平移到「首帧 = 站立时的髋高」，并压扁水平漂移。
   * 直接删位移会让人被抬起（腿按下沉髋高摆姿势），原样保留则会漂出小窗口。
   */
  rebaseRootMotion(clip) {
    const HORIZONTAL_SCALE = 0.35;
    const rest = this.restHipsPos;
    for (const track of clip.tracks) {
      const n = track.name.toLowerCase();
      if (!n.includes('.position')) continue;
      const isHips = n.includes('hips');
      if (!isHips && !n.includes('root')) continue;

      const v = track.values;
      if (v.length < 3) continue;
      const [x0, y0, z0] = [v[0], v[1], v[2]];
      const base = isHips && rest ? rest : { x: 0, y: 0, z: 0 };
      for (let i = 0; i < v.length; i += 3) {
        v[i] = (v[i] - x0) * HORIZONTAL_SCALE + base.x;
        v[i + 1] = v[i + 1] - y0 + base.y;
        v[i + 2] = (v[i + 2] - z0) * HORIZONTAL_SCALE + base.z;
      }
    }
  }

  stopVrma({ hard = false } = {}) {
    if (!this.vrmaAction && !hard) return;
    if (this.vrmaAction) {
      if (hard) this.vrmaAction.stop();
      else this.vrmaAction.fadeOut(CROSSFADE_SEC);
      this.vrmaAction = null;
    }
    if (hard && this.mixer) this.mixer.stopAllAction();
  }

  /** 骨骼彻底回中立，再套待机（VRMA 结束后必做，否则人会停在窗外） */
  resetAfterVrma() {
    this.stopVrma({ hard: true });
    if (this.vrm?.humanoid) {
      this.vrm.humanoid.resetNormalizedPose();
      this.vrm.humanoid.resetRawPose();
    }
    try {
      this.vrm?.lookAt?.reset?.();
    } catch {
      /* ignore */
    }
    if (this.vrm?.scene) {
      this.vrm.scene.position.set(0, 0, 0);
      this.vrm.scene.rotation.y = this.baseYaw;
    }
    this.applyRestPose();
  }

  /**
   * 播放已缓存的 VRMA；失败返回 false（调用方回退程序动作）。
   * @param {string} vrmaName
   * @param {{ loop?: boolean, durationMs?: number }} def
   */
  playVrmaClip(vrmaName, def) {
    const clip = this.vrmaClips.get(vrmaName);
    if (!clip || !this.mixer) return false;

    this.motion = null;
    // VRMA 不含手指/手腕轨道，若不先清掉待机的捏手姿态，手会一直塞在袖子里
    if (this.vrm?.humanoid) {
      this.vrm.humanoid.resetNormalizedPose();
      this.vrm.humanoid.resetRawPose();
    }
    const next = this.mixer.clipAction(clip);
    next.reset();
    next.setLoop(def.loop ? THREE.LoopRepeat : THREE.LoopOnce, Infinity);
    next.clampWhenFinished = !def.loop;
    next.enabled = true;

    if (this.vrmaAction && this.vrmaAction !== next) {
      next.crossFadeFrom(this.vrmaAction, CROSSFADE_SEC, false);
    }
    next.play();
    this.vrmaAction = next;

    if (def.loop && (!def.durationMs || def.durationMs <= 0)) {
      this.actionBusyUntil = Number.POSITIVE_INFINITY;
    } else {
      // 以 VRMA 实际时长为准，避免动画还没播完就切回待机
      const ms = Math.max(400, clip.duration * 1000, def.durationMs || 0);
      this.actionBusyUntil = performance.now() + ms;
    }
    return true;
  }

  get busy() {
    return performance.now() < this.actionBusyUntil;
  }

  /**
   * @returns {'ok'|'unknown_action'|'renderer_busy'}
   */
  playAction(actionName) {
    const def = ACTION_TABLE[actionName];
    if (!def) return 'unknown_action';
    // 对话链路动作可打断思考/害羞 VRMA，避免「你好」挥手或听歌接不上
    const canInterrupt = ['idle', 'talking', 'groove', 'wave', 'blush'].includes(actionName);
    if (this.busy && !canInterrupt) {
      return 'renderer_busy';
    }

    this.currentAction = actionName;
    this.motion = null;
    // 听歌只晃身体，不要沿用说话口型，否则嘴会一直张着
    if (actionName !== 'talking') this.setViseme('neutral', 0);

    // 待机 / 说话：停 VRMA，用程序待机（方便鼠标跟随）
    if (def.kind === 'idle' || def.kind === 'talk') {
      this.resetAfterVrma();
      this.actionBusyUntil = 0;
      return 'ok';
    }

  // 有对应开源 VRMA 则优先播真实动画
    if (def.openVrma && this.playVrmaClip(def.openVrma, def)) {
      return 'ok';
    }
    this.resetAfterVrma();

    if (def.loop && (!def.durationMs || def.durationMs <= 0)) {
      // 循环 UX（听歌微晃等）：一直播到被下一个动作打断
      this.actionBusyUntil = Number.POSITIVE_INFINITY;
      this.motion = {
        name: def.motion,
        t0: performance.now(),
        duration: 100000,
      };
      return 'ok';
    }

    this.actionBusyUntil = performance.now() + def.durationMs;
    this.motion = {
      name: def.motion,
      t0: performance.now(),
      duration: def.durationMs,
    };
    return 'ok';
  }

  setGaze(event) {
    this.gazeEvent = event;
    if (!this.vrm) return;
    if (this.mouseFollowEnabled) {
      this.applyMouseLook();
      return;
    }

    const y = 1.35;
    switch (event) {
      case 'listening_start':
        this.lookAtTarget.position.set(0, y, 1.0);
        break;
      case 'thinking_start':
        this.lookAtTarget.position.set(0.35, y + 0.1, 1.1);
        break;
      case 'tool_pending':
        this.lookAtTarget.position.set(-0.25, y, 1.0);
        break;
      case 'speaking_start':
        this.lookAtTarget.position.set(0, y, 0.9);
        break;
      case 'speaking_end':
      case 'idle':
      default:
        this.lookAtTarget.position.set(0.05, y, 1.2);
        break;
    }
  }

  /** @param {number} ndcX 相对桌宠窗口 -1..1（可略超出） @param {number} ndcY -1..1 */
  setMouseLook(ndcX, ndcY) {
    this.mouseNdc.x = ndcX;
    this.mouseNdc.y = ndcY;
  }

  /** 平滑鼠标，避免抖 */
  smoothMouse() {
    this.mouseSmooth.x += (this.mouseNdc.x - this.mouseSmooth.x) * 0.14;
    this.mouseSmooth.y += (this.mouseNdc.y - this.mouseSmooth.y) * 0.14;
    return {
      x: THREE.MathUtils.clamp(this.mouseSmooth.x, -1.6, 1.6),
      y: THREE.MathUtils.clamp(this.mouseSmooth.y, -1.6, 1.6),
    };
  }

  applyMouseLook() {
    if (!this.lookAtTarget || !this.vrm?.humanoid) return;
    const mx = THREE.MathUtils.clamp(this.mouseSmooth.x, -1.6, 1.6);
    const my = THREE.MathUtils.clamp(this.mouseSmooth.y, -1.6, 1.6);
    const bone = (name) => this.vrm.humanoid.getNormalizedBoneNode(name);
    const head = bone('head');
    const spine = bone('spine');
    const chest = bone('chest');
    const hips = bone('hips');

    const headPos = new THREE.Vector3(0, 1.4, 0);
    if (head) head.getWorldPosition(headPos);

    // 鼠标右 → 目标点右；转头同号（修过反向）
    this.lookAtTarget.position.set(
      mx * 0.95,
      headPos.y + my * 0.55,
      headPos.z + 1.35,
    );

    if (head) {
      head.rotation.y = THREE.MathUtils.clamp(mx * 0.58, -0.85, 0.85);
      // 鼠标上 → 抬头（此前 -my 会上下反）
      head.rotation.x = THREE.MathUtils.clamp(my * 0.38, -0.5, 0.5);
    }
    // 在待机姿态上叠加身体跟随
    if (spine) {
      spine.rotation.y += mx * 0.14;
      spine.rotation.x += my * 0.03;
    }
    if (chest) {
      chest.rotation.y += mx * 0.18;
      chest.rotation.x += my * 0.04;
    }
    if (hips) {
      hips.rotation.y += mx * 0.06;
    }
  }

  setViseme(v, weight = 0.85) {
    for (const k of Object.keys(this.visemeWeights)) {
      this.visemeWeights[k] = 0;
    }
    if (v && v !== 'neutral' && this.visemeWeights[v] !== undefined) {
      this.visemeWeights[v] = weight;
    }
    this.applyVisemes();
  }

  setExpression(name, value = 1) {
    const expr = this.vrm?.expressionManager;
    if (!expr) return;
    try {
      expr.setValue(name, value);
    } catch {
      // 模型未包含该表情时忽略
    }
  }

  resetPoseSoft() {
    this.applyRestPose();
  }

  /** 待机：对位站姿 + 放松手臂，不再用僵硬 A-pose。 */
  applyRestPose() {
    if (!this.vrm?.humanoid) return;
    this.applyIdlePose(performance.now());
    this.vrm.scene.rotation.y = this.baseYaw;
  }

  /**
   * 更自然的站立：微对位（胯略偏、肩一高一低）、手臂自然下垂微屈、
   * 手指略收；并随鼠标轻微侧倾。（恢复到「头/手脚跟鼠标」那一版）
   */
  applyIdlePose(t = performance.now()) {
    if (!this.vrm?.humanoid) return;
    const bone = (name) => this.vrm.humanoid.getNormalizedBoneNode(name);
    const mx = this.mouseFollowEnabled ? this.mouseSmooth.x : 0;
    const my = this.mouseFollowEnabled ? this.mouseSmooth.y : 0;

    const breath = Math.sin(t * 0.0024) * 0.028;
    const sway = Math.sin(t * 0.0015) * 0.035;
    const float = Math.sin(t * 0.0019) * 0.03;

    const hips = bone('hips');
    const spine = bone('spine');
    const chest = bone('chest');
    const head = bone('head');

    // 对位站：重心略偏右腿感
    if (hips) {
      hips.rotation.set(0.02, 0.06 + mx * 0.05, -0.04);
      const rest = this.restHipsPos;
      hips.position.set(
        rest?.x ?? 0,
        (rest?.y ?? 0) + Math.abs(Math.sin(t * 0.0024)) * 0.008,
        rest?.z ?? 0,
      );
    }
    if (spine) spine.rotation.set(0.04 + breath * 0.5, -0.04 + sway * 0.4, 0.03);
    if (chest) chest.rotation.set(0.03 + breath, 0.05 + sway, -0.05);
    if (head) head.rotation.set(0, 0, 0);

    const leftUpper = bone('leftUpperArm');
    const rightUpper = bone('rightUpperArm');
    const leftLower = bone('leftLowerArm');
    const rightLower = bone('rightLowerArm');
    const leftHand = bone('leftHand');
    const rightHand = bone('rightHand');
    const leftShoulder = bone('leftShoulder');
    const rightShoulder = bone('rightShoulder');

    // 肩线：右肩略低；鼠标左右时肩膀轻轻跟着
    if (leftShoulder) leftShoulder.rotation.set(0.02, 0.04, 0.08 + mx * 0.04);
    if (rightShoulder) rightShoulder.rotation.set(0.02, -0.04, -0.12 - mx * 0.04);

    // 手臂自然下垂 + 肘微屈；鼠标偏向哪侧，同侧手臂略抬、略前伸
    const leanL = Math.max(0, -mx);
    const leanR = Math.max(0, mx);
    // 手臂略离身、肘只微屈：Zome 袖子很宽，肘弯大了手会被吞进袖口
    if (leftUpper) {
      leftUpper.rotation.set(
        0.06 + breath * 0.3 + leanL * 0.2 + my * 0.04,
        0.06 + leanL * 0.1,
        0.98 + float * 0.4 - leanL * 0.15,
      );
    }
    if (rightUpper) {
      rightUpper.rotation.set(
        0.07 + breath * 0.3 + leanR * 0.2 + my * 0.04,
        -0.07 - leanR * 0.1,
        -1.0 - float * 0.4 + leanR * 0.15,
      );
    }
    if (leftLower) {
      leftLower.rotation.set(-0.16 + sway * 0.3 + leanL * 0.08, 0.05, 0.04);
    }
    if (rightLower) {
      rightLower.rotation.set(-0.18 + sway * 0.3 + leanR * 0.08, -0.04, -0.03);
    }

    // 手：腕放松，别内翻太多
    if (leftHand) leftHand.rotation.set(0.04, 0.06, 0.1 + float * 0.2);
    if (rightHand) rightHand.rotation.set(0.05, -0.05, -0.12 - float * 0.2);

    this.curlFingersSoft(bone, 'left', 0.16 + float * 0.4);
    this.curlFingersSoft(bone, 'right', 0.18 + float * 0.4);
  }

  curlFingersSoft(bone, side, amount) {
    const prefix = side === 'left' ? 'left' : 'right';
    const names = [
      `${prefix}ThumbProximal`,
      `${prefix}IndexProximal`,
      `${prefix}MiddleProximal`,
      `${prefix}RingProximal`,
      `${prefix}LittleProximal`,
    ];
    const sign = side === 'left' ? 1 : -1;
    for (const n of names) {
      const node = bone(n);
      if (!node) continue;
      // 拇指略不同轴
      if (n.includes('Thumb')) node.rotation.set(amount * 0.25, sign * amount * 0.4, 0);
      else node.rotation.set(0, 0, sign * amount * 0.55);
    }
  }

  /** @deprecated 兼容旧调用名 */
  applyArmRest(t = performance.now()) {
    this.applyIdlePose(t);
  }

  update() {
    if (!this.vrm) return;
    const dt = this.clock.getDelta();
    const t = performance.now();
    const playingVrma = Boolean(this.vrmaAction);

    this.updateBlink(dt);
    this.applyVisemes();
    if (this.mouseFollowEnabled) this.smoothMouse();

    if (this.mixer) this.mixer.update(dt);

    if (!playingVrma) {
      if (!this.motion) this.applyIdlePose(t);
      else this.updateProceduralMotion(t);
    }

    if (t >= this.actionBusyUntil && this.currentAction !== 'idle' && this.currentAction !== 'talking') {
      this.currentAction = 'idle';
      this.motion = null;
      this.resetAfterVrma();
    }

    // VRMA 播放时不硬拧骨骼，只更新视线目标，避免和动画抢控制权
    if (this.mouseFollowEnabled) {
      if (playingVrma) this.applyMouseLookTargetOnly();
      else this.applyMouseLook();
    }

    this.vrm.update(dt);
  }

  /** 仅移动 lookAt 目标点，不改头/身骨骼（给 VRMA 用） */
  applyMouseLookTargetOnly() {
    if (!this.lookAtTarget || !this.vrm?.humanoid) return;
    const mx = THREE.MathUtils.clamp(this.mouseSmooth.x, -1.6, 1.6);
    const my = THREE.MathUtils.clamp(this.mouseSmooth.y, -1.6, 1.6);
    const head = this.vrm.humanoid.getNormalizedBoneNode('head');
    const headPos = new THREE.Vector3(0, 1.4, 0);
    if (head) head.getWorldPosition(headPos);
    this.lookAtTarget.position.set(
      mx * 0.95,
      headPos.y + my * 0.55,
      headPos.z + 1.35,
    );
  }

  updateBlink(dt) {
    this.blinkTimer += dt;
    const expr = this.vrm.expressionManager;
    if (!expr) return;

    if (this.blinkTimer >= this.nextBlinkIn) {
      this.blinkTimer = 0;
      this.nextBlinkIn = 2 + Math.random() * 4;
      this._blinkPhase = 0.12;
    }

    if (this._blinkPhase > 0) {
      this._blinkPhase -= dt;
      const w = Math.max(0, Math.min(1, this._blinkPhase / 0.06));
      const close = this._blinkPhase > 0.06 ? 1 - w : w;
      try {
        expr.setValue('blink', close);
      } catch {
        try {
          expr.setValue('blinkLeft', close);
          expr.setValue('blinkRight', close);
        } catch {
          /* ignore */
        }
      }
    }
  }

  applyVisemes() {
    const expr = this.vrm?.expressionManager;
    if (!expr) return;
    for (const [k, v] of Object.entries(this.visemeWeights)) {
      try {
        expr.setValue(k, v);
      } catch {
        /* model may not have this blendshape */
      }
    }
  }

  updateIdleBreath(_t) {
    // 呼吸已并入 applyIdlePose
  }

  updateProceduralMotion(t) {
    if (!this.motion || !this.vrm?.humanoid) return;
    // 先回到站立姿态再叠动作，避免髋高被写成 0、人掉出小窗口
    this.applyIdlePose(t);
    const humanoid = this.vrm.humanoid;
    const p = Math.min(1, (t - this.motion.t0) / this.motion.duration);
    const e = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
    const s = Math.sin(e * Math.PI);
    const restY = this.restHipsPos?.y ?? 0;

    const leftArm = humanoid.getNormalizedBoneNode('leftUpperArm');
    const rightArm = humanoid.getNormalizedBoneNode('rightUpperArm');
    const leftLower = humanoid.getNormalizedBoneNode('leftLowerArm');
    const rightLower = humanoid.getNormalizedBoneNode('rightLowerArm');
    const spine = humanoid.getNormalizedBoneNode('spine');
    const hips = humanoid.getNormalizedBoneNode('hips');
    const head = humanoid.getNormalizedBoneNode('head');

    switch (this.motion.name) {
      case 'wave': {
        // 站姿右臂 z≈-1；往 0 抬起再左右摆，才是挥手（不要整臂拧到 T-pose）
        if (rightArm) {
          rightArm.rotation.z += 1.05 * s;
          rightArm.rotation.x += -0.45 * s;
          rightArm.rotation.y += Math.sin(p * Math.PI * 8) * 0.35 * s;
        }
        if (rightLower) {
          rightLower.rotation.x += -0.55 * s;
          rightLower.rotation.z += Math.sin(p * Math.PI * 10) * 0.55 * s;
        }
        if (spine) spine.rotation.y += 0.2 * s;
        if (hips) hips.position.y = restY + Math.abs(Math.sin(p * Math.PI * 4)) * 0.02 * s;
        break;
      }
      case 'peek': {
        if (head) {
          head.rotation.y = Math.sin(p * Math.PI * 2) * 0.55;
          head.rotation.x = -0.1 * s;
        }
        if (spine) spine.rotation.y += head ? head.rotation.y * 0.35 : 0;
        if (rightArm) rightArm.rotation.z += -0.4 * s;
        break;
      }
      case 'excited': {
        if (leftArm) leftArm.rotation.z += 1.1 * s + Math.sin(p * 20) * 0.15;
        if (rightArm) rightArm.rotation.z += -1.1 * s + Math.cos(p * 20) * 0.15;
        if (hips) hips.position.y = restY + Math.abs(Math.sin(p * Math.PI * 5)) * 0.05;
        if (head) head.rotation.x += -0.12 * s;
        break;
      }
      case 'shrug': {
        if (leftArm) leftArm.rotation.z += 0.75 * s;
        if (rightArm) rightArm.rotation.z += -0.75 * s;
        if (leftLower) leftLower.rotation.x += -0.3 * s;
        if (rightLower) rightLower.rotation.x += -0.3 * s;
        if (head) head.rotation.x += 0.12 * s;
        if (spine) spine.rotation.x += -0.1 * s;
        break;
      }
      case 'groove': {
        if (head) head.rotation.y += Math.sin(t * 0.008) * 0.25;
        if (spine) {
          spine.rotation.y += Math.sin(t * 0.006) * 0.18;
          spine.rotation.z += Math.sin(t * 0.005) * 0.08;
        }
        if (hips) hips.position.y = restY + Math.sin(t * 0.008) * 0.015;
        if (leftArm) leftArm.rotation.z += Math.sin(t * 0.005) * 0.15;
        if (rightArm) rightArm.rotation.z += Math.cos(t * 0.005) * 0.15;
        break;
      }
      default:
        break;
    }
  }
}
