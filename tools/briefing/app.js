(() => {
'use strict';
const D = window.ASRP_DATA;
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private window: state stays in the page */ } },
};

/* ---------- decoding the embedded data ---------- */
const bytes = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
const f32 = (s) => new Float32Array(bytes(s).buffer);
const u16 = (s) => new Uint16Array(bytes(s).buffer);
const u32 = (s) => new Uint32Array(bytes(s).buffer);

function normals(pos, idx) {
  const n = new Float32Array(pos.length);
  for (let t = 0; t < idx.length; t += 3) {
    const a = idx[t] * 3, b = idx[t + 1] * 3, c = idx[t + 2] * 3;
    const ux = pos[b] - pos[a], uy = pos[b + 1] - pos[a + 1], uz = pos[b + 2] - pos[a + 2];
    const vx = pos[c] - pos[a], vy = pos[c + 1] - pos[a + 1], vz = pos[c + 2] - pos[a + 2];
    const x = uy * vz - uz * vy, y = uz * vx - ux * vz, z = ux * vy - uy * vx;
    for (const v of [a, b, c]) { n[v] += x; n[v + 1] += y; n[v + 2] += z; }
  }
  for (let i = 0; i < n.length; i += 3) {
    const l = Math.hypot(n[i], n[i + 1], n[i + 2]) || 1;
    n[i] /= l; n[i + 1] /= l; n[i + 2] /= l;
  }
  return n;
}

const cache = {};
function mesh(name) {
  if (!cache[name]) {
    const pos = f32(D.meshes[name].p), idx = u16(D.meshes[name].i);
    cache[name] = { pos, idx, nor: normals(pos, idx) };
  }
  return cache[name];
}

function edges(idx) {
  const seen = new Set(), out = [];
  for (let t = 0; t < idx.length; t += 3) {
    for (let e = 0; e < 3; e++) {
      const a = idx[t + e], b = idx[t + (e + 1) % 3];
      const key = a < b ? a * 65536 + b : b * 65536 + a;
      if (!seen.has(key)) { seen.add(key); out.push(a, b); }
    }
  }
  return new Uint16Array(out);
}

/* ---------- matrices, column-major ---------- */
const M = {
  id: () => [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
  mul(a, b) {
    const r = new Array(16);
    for (let c = 0; c < 4; c++) for (let w = 0; w < 4; w++) {
      r[c * 4 + w] = a[w] * b[c * 4] + a[w + 4] * b[c * 4 + 1] + a[w + 8] * b[c * 4 + 2] + a[w + 12] * b[c * 4 + 3];
    }
    return r;
  },
  persp(f, asp, n, far) {
    const t = 1 / Math.tan(f / 2);
    return [t / asp, 0, 0, 0, 0, t, 0, 0, 0, 0, (far + n) / (n - far), -1, 0, 0, 2 * far * n / (n - far), 0];
  },
  look(e, c, u) {
    let z = [e[0] - c[0], e[1] - c[1], e[2] - c[2]];
    const zl = Math.hypot(...z); z = z.map((v) => v / zl);
    let x = [u[1] * z[2] - u[2] * z[1], u[2] * z[0] - u[0] * z[2], u[0] * z[1] - u[1] * z[0]];
    const xl = Math.hypot(...x); x = x.map((v) => v / xl);
    const y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]];
    const dot = (a) => -(a[0] * e[0] + a[1] * e[1] + a[2] * e[2]);
    return [x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, dot(x), dot(y), dot(z), 1];
  },
  trans: (x, y, z) => [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1],
  scale: (s) => [s, 0, 0, 0, 0, s, 0, 0, 0, 0, s, 0, 0, 0, 0, 1],
  rotX(a) { const c = Math.cos(a), s = Math.sin(a); return [1, 0, 0, 0, 0, c, s, 0, 0, -s, c, 0, 0, 0, 0, 1]; },
  inv(m) {
    const [a, b, c, d, e, f, g, h, i, j, k, l, n, o, p, q] = m;
    const A = a * f - b * e, B = a * g - c * e, C = a * h - d * e, E = b * g - c * f, F = b * h - d * f, G = c * h - d * g;
    const H = i * o - j * n, I = i * p - k * n, J = i * q - l * n, K = j * p - k * o, L = j * q - l * o, N = k * q - l * p;
    const det = 1 / (A * N - B * L + C * K + E * J - F * I + G * H);
    return [f * N - g * L + h * K, c * L - b * N - d * K, o * G - p * F + q * E, k * F - j * G - l * E,
      g * J - e * N - h * I, a * N - c * J + d * I, p * C - n * G - q * B, i * G - k * C + l * B,
      e * L - f * J + h * H, b * J - a * L - d * H, n * F - o * C + q * A, j * C - i * F - l * A,
      f * I - e * K - g * H, a * K - b * I + c * H, o * B - n * E - p * A, i * E - j * B + k * A].map((v) => v * det);
  },
  apply(m, p) {
    return [m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12],
      m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13],
      m[2] * p[0] + m[6] * p[1] + m[10] * p[2] + m[14]];
  },
};

/* ---------- a small WebGL stage ---------- */
const VS = `#version 300 es
layout(location=0) in vec3 aP; layout(location=1) in vec3 aN; layout(location=2) in vec3 aC;
uniform mat4 uVP, uM; out vec3 vN, vW, vC;
void main(){ vec4 w=uM*vec4(aP,1.); vW=w.xyz; vN=mat3(uM)*aN; vC=aC; gl_Position=uVP*w; }`;
const FS = `#version 300 es
precision highp float; in vec3 vN,vW,vC; uniform vec3 uCol,uEye; uniform float uAlpha,uXray,uUseC; out vec4 o;
void main(){
  vec3 N=normalize(vN), V=normalize(uEye-vW); if(dot(N,V)<0.) N=-N;
  vec3 base=mix(uCol,vC,uUseC);
  vec3 L1=normalize(vec3(.45,.75,.65)), L2=normalize(vec3(-.8,.35,.15));
  float d=max(dot(N,L1),0.)*.72+max(dot(N,L2),0.)*.24, hemi=.5+.5*N.z;
  vec3 c=base*(.30+.18*hemi+.62*d);
  vec3 H=normalize(L1+V); c+=vec3(.10)*pow(max(dot(N,H),0.),28.);
  float a=uAlpha;
  if(uXray>0.){ float f=pow(1.-abs(dot(N,V)),2.2); a=mix(.015,.5,f)*uXray; c=base; }
  o=vec4(c*a,a);
}`;
const LVS = `#version 300 es
layout(location=0) in vec3 aP; uniform mat4 uVP, uM; uniform float uSize;
layout(location=2) in vec3 aC; out vec3 vC;
void main(){ gl_Position=uVP*uM*vec4(aP,1.); gl_PointSize=uSize; vC=aC; }`;
const LFS = `#version 300 es
precision highp float; uniform vec4 uRGBA; uniform float uRound,uUseC; in vec3 vC; out vec4 o;
void main(){ if(uRound>0.&&length(gl_PointCoord-.5)>.5) discard;
  vec3 c=mix(uRGBA.rgb,vC,uUseC); o=vec4(c*uRGBA.a,uRGBA.a); }`;

function program(gl, v, f) {
  const p = gl.createProgram();
  for (const [t, s] of [[gl.VERTEX_SHADER, v], [gl.FRAGMENT_SHADER, f]]) {
    const sh = gl.createShader(t);
    gl.shaderSource(sh, s); gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(sh));
    gl.attachShader(p, sh);
  }
  gl.linkProgram(p);
  const u = {};
  const n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS);
  for (let i = 0; i < n; i++) { const a = gl.getActiveUniform(p, i); u[a.name] = gl.getUniformLocation(p, a.name); }
  return { p, u };
}

const stages = [];
class Stage {
  constructor(host, o = {}) {
    Object.assign(this, { host, az: .5, el: .1, dist: 700, target: [0, 0, 0], fov: .46, spin: false, onpick: null }, o);
    this.objs = new Map(); this.lines = new Map(); this.points = null; this.labels = [];
    this.dirty = true; this.onscreen = true; this.az0 = this.az; this.t0 = performance.now();
    const c = this.canvas = document.createElement('canvas');
    c.setAttribute('aria-label', o.label || '可以拖动旋转的三维模型');
    host.appendChild(c);
    const gl = this.gl = c.getContext('webgl2', { antialias: true, premultipliedAlpha: true });
    if (!gl) {
      host.innerHTML = '<div class="nogl detail">这个浏览器没有开启 WebGL，看不到三维图。请换用新版 Chrome 或 Edge。</div>';
      this.dead = true;
      return;
    }
    this.mp = program(gl, VS, FS); this.lp = program(gl, LVS, LFS);
    gl.enable(gl.DEPTH_TEST); gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    gl.clearColor(0, 0, 0, 0); gl.polygonOffset(1, 1); gl.enable(gl.POLYGON_OFFSET_FILL);
    this.bind();
    new ResizeObserver(() => this.resize()).observe(host);
    new IntersectionObserver((e) => { this.onscreen = e[0].isIntersecting; if (this.onscreen) this.dirty = true; }).observe(host);
    this.resize();
    stages.push(this);
  }

  bind() {
    const c = this.canvas; let down = null, moved = 0;
    c.addEventListener('pointerdown', (e) => { down = [e.clientX, e.clientY]; moved = 0; c.setPointerCapture(e.pointerId); this.spin = false; });
    c.addEventListener('pointermove', (e) => {
      if (!down) return;
      const dx = e.clientX - down[0], dy = e.clientY - down[1];
      moved += Math.abs(dx) + Math.abs(dy); down = [e.clientX, e.clientY];
      this.az -= dx * .008; this.el = Math.max(-1.4, Math.min(1.4, this.el + dy * .006)); this.dirty = true;
    });
    const up = (e) => {
      if (down && moved < 6 && this.onpick) { const r = c.getBoundingClientRect(); this.onpick(e.clientX - r.left, e.clientY - r.top); }
      down = null;
    };
    c.addEventListener('pointerup', up); c.addEventListener('pointercancel', () => { down = null; });
    c.addEventListener('wheel', (e) => {
      if (!e.ctrlKey) return;
      e.preventDefault(); this.dist *= Math.exp(e.deltaY * .002); this.dirty = true; this.spin = false;
    }, { passive: false });
  }

  resize() {
    const r = this.host.getBoundingClientRect(), s = Math.min(devicePixelRatio || 1, 2);
    if (!r.width) return;
    this.canvas.width = Math.round(r.width * s); this.canvas.height = Math.round(r.height * s);
    this.w = r.width; this.h = r.height; this.dirty = true;
  }

  vbo(data, loc, size) {
    const gl = this.gl, b = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 0, 0);
    return b;
  }

  add(name, m, o = {}) {
    const gl = this.gl, vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    const pos = this.vbo(m.pos, 0, 3), nor = this.vbo(m.nor, 1, 3), col = this.vbo(new Float32Array(m.pos.length), 2, 3);
    const ibo = gl.createBuffer();
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ibo); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, m.idx, gl.STATIC_DRAW);
    gl.bindVertexArray(null);
    this.objs.set(name, { vao, pos, nor, col, ibo, m, n: m.idx.length, color: [.8, .8, .8], alpha: 1, xray: 0, useC: 0, model: M.id(), show: true, wire: false, ...o });
    this.dirty = true;
  }

  update(name, pos, nor) {
    const gl = this.gl, ob = this.objs.get(name);
    gl.bindBuffer(gl.ARRAY_BUFFER, ob.pos); gl.bufferSubData(gl.ARRAY_BUFFER, 0, pos);
    gl.bindBuffer(gl.ARRAY_BUFFER, ob.nor); gl.bufferSubData(gl.ARRAY_BUFFER, 0, nor);
    this.dirty = true;
  }

  colors(name, col) {
    const gl = this.gl, ob = this.objs.get(name);
    gl.bindBuffer(gl.ARRAY_BUFFER, ob.col); gl.bufferSubData(gl.ARRAY_BUFFER, 0, col);
    ob.useC = 1; this.dirty = true;
  }

  setPoints(pos, col, size) {
    const gl = this.gl, vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    this.vbo(pos, 0, 3);
    const c = this.vbo(col, 2, 3);
    gl.bindVertexArray(null);
    this.points = { vao, c, n: pos.length / 3, size, pos, onTop: true };
    this.dirty = true;
  }

  pointColors(col) {
    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.points.c); gl.bufferSubData(gl.ARRAY_BUFFER, 0, col);
    this.dirty = true;
  }

  addLines(name, pos, rgba) {
    const gl = this.gl, vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    this.vbo(pos, 0, 3);
    gl.bindVertexArray(null);
    this.lines.set(name, { vao, n: pos.length / 3, rgba });
  }

  eye() {
    const c = Math.cos(this.el), d = this.dist, t = this.target;
    return [t[0] + d * Math.sin(this.az) * c, t[1] + d * Math.cos(this.az) * c, t[2] + d * Math.sin(this.el)];
  }

  vp() {
    return M.mul(M.persp(this.fov, this.w / this.h, this.dist * .05, this.dist * 6), M.look(this.eye(), this.target, [0, 0, 1]));
  }

  project(p) {
    const v = this.vp();
    const w = v[3] * p[0] + v[7] * p[1] + v[11] * p[2] + v[15];
    const q = M.apply(v, p);
    return [(q[0] / w * .5 + .5) * this.w, (.5 - q[1] / w * .5) * this.h];
  }

  draw(now) {
    if (this.spin && !reduced) { this.az = this.az0 + .42 * Math.sin((now - this.t0) / 3600); }
    const gl = this.gl, vp = this.vp(), eye = this.eye();
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.useProgram(this.mp.p);
    gl.uniformMatrix4fv(this.mp.u.uVP, false, vp); gl.uniform3fv(this.mp.u.uEye, eye);
    const pass = (test) => {
      for (const ob of this.objs.values()) {
        if (!ob.show || !test(ob)) continue;
        gl.uniformMatrix4fv(this.mp.u.uM, false, ob.model);
        gl.uniform3fv(this.mp.u.uCol, ob.color);
        gl.uniform1f(this.mp.u.uAlpha, ob.alpha); gl.uniform1f(this.mp.u.uXray, ob.xray); gl.uniform1f(this.mp.u.uUseC, ob.useC);
        gl.bindVertexArray(ob.vao);
        gl.drawElements(gl.TRIANGLES, ob.n, gl.UNSIGNED_SHORT, 0);
      }
    };
    gl.depthMask(true); gl.disable(gl.CULL_FACE);
    pass((ob) => !ob.xray);
    gl.useProgram(this.lp.p);
    gl.uniformMatrix4fv(this.lp.u.uVP, false, vp); gl.uniform1f(this.lp.u.uRound, 0); gl.uniform1f(this.lp.u.uUseC, 0);
    for (const ob of this.objs.values()) {
      if (!ob.show || !ob.wire) continue;
      if (!ob.ebo) {
        const e = edges(ob.m.idx); ob.ebo = gl.createBuffer(); ob.en = e.length;
        gl.bindVertexArray(ob.vao); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ob.ebo); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, e, gl.STATIC_DRAW);
      }
      gl.bindVertexArray(ob.vao); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ob.ebo);
      gl.uniformMatrix4fv(this.lp.u.uM, false, ob.model); gl.uniform4f(this.lp.u.uRGBA, .08, .12, .15, .5);
      gl.drawElements(gl.LINES, ob.en, gl.UNSIGNED_SHORT, 0);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ob.ibo);
    }
    for (const l of this.lines.values()) {
      gl.bindVertexArray(l.vao);
      gl.uniformMatrix4fv(this.lp.u.uM, false, M.id()); gl.uniform4fv(this.lp.u.uRGBA, l.rgba);
      gl.drawArrays(gl.LINES, 0, l.n);
    }
    if (this.points) {
      gl.disable(gl.DEPTH_TEST);
      gl.uniform1f(this.lp.u.uRound, 1); gl.uniform1f(this.lp.u.uUseC, 1);
      gl.uniform1f(this.lp.u.uSize, this.points.size * Math.min(devicePixelRatio || 1, 2));
      gl.uniformMatrix4fv(this.lp.u.uM, false, M.id()); gl.uniform4f(this.lp.u.uRGBA, 1, 1, 1, 1);
      gl.bindVertexArray(this.points.vao);
      gl.drawArrays(gl.POINTS, 0, this.points.n);
      gl.enable(gl.DEPTH_TEST);
    }
    gl.useProgram(this.mp.p); gl.depthMask(false);
    pass((ob) => ob.xray);
    gl.depthMask(true); gl.bindVertexArray(null);
    this.updateLabels();
    this.dirty = false;
  }

  /* Atlas-style leader lines: a fixed label, a thin line to a point on the moving model. */
  setLabels(list) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'lead-lines');
    this.host.appendChild(svg);
    this.labels = list.map((l) => {
      const el = document.createElement('div');
      el.className = 'lbl';
      el.innerHTML = `${l.text}${l.sub ? `<small>${l.sub}</small>` : ''}`;
      el.style.top = `${l.y * 100}%`;
      el.style[l.side === 'left' ? 'left' : 'right'] = `${(l.side === 'left' ? l.x : 1 - l.x) * 100}%`;
      this.host.appendChild(el);
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.setAttribute('stroke', 'var(--dim)'); line.setAttribute('stroke-width', '1');
      const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      dot.setAttribute('r', '2.5'); dot.setAttribute('fill', 'var(--ink)');
      svg.append(line, dot);
      return { ...l, el, line, dot };
    });
  }

  updateLabels() {
    for (const l of this.labels) {
      const ob = l.obj && this.objs.get(l.obj);
      const show = !ob || ob.show;
      l.el.hidden = !show; l.line.style.display = l.dot.style.display = show ? '' : 'none';
      if (!show) continue;
      const q = ob ? M.apply(ob.model, l.at) : l.at;
      const [px, py] = this.project(q);
      const lw = l.el.offsetWidth, lh = l.el.offsetHeight;
      const lx = l.side === 'left' ? l.x * this.w + lw : l.x * this.w - lw;
      const ly = l.y * this.h + lh / 2;
      l.line.setAttribute('x1', lx); l.line.setAttribute('y1', ly); l.line.setAttribute('x2', px); l.line.setAttribute('y2', py);
      l.dot.setAttribute('cx', px); l.dot.setAttribute('cy', py);
    }
  }
}
function loop(t) {
  for (const s of stages) if (s.onscreen && (s.dirty || s.spin)) s.draw(t);
  requestAnimationFrame(loop);
}
requestAnimationFrame(loop);

/* Build a stage only when it is about to be seen: the page stays quick to open. */
function whenNear(el, fn) {
  new IntersectionObserver((e, io) => { if (e[0].isIntersecting) { io.disconnect(); fn(); } }, { rootMargin: '500px' }).observe(el);
}

const BONE = [.84, .80, .70], TOOTH = [.95, .94, .88], LIP = [.74, .15, .2], SKIN = [.55, .75, .85];
const PARTS = {
  skull: { color: BONE }, jaw: { color: BONE }, teethU: { color: TOOTH }, teethL: { color: TOOTH }, lips: { color: LIP },
};
const hingeMatrix = (deg) => {
  const h = D.hinge;
  return M.mul(M.mul(M.trans(...h), M.rotX(-deg * Math.PI / 180)), M.trans(-h[0], -h[1], -h[2]));
};
function addHead(stage, skin) {
  for (const [name, o] of Object.entries(PARTS)) stage.add(name, mesh(name), o);
  if (skin) stage.add('skin', mesh('skin'), { color: SKIN, xray: .9, show: skin === 'show' });
}

/* ---------- hero ---------- */
whenNear($('#heroStage'), () => {
  const s = new Stage($('#heroStage'), { az: .62, el: .06, dist: 1020, target: [0, -118, 2], spin: true, label: '实验室的头部模型，可以旋转' });
  if (s.dead) return;
  addHead(s, 'show');
  s.setLabels([
    { text: '颅骨', sub: '硬的，不动', at: [46, -12, 95], obj: 'skull', x: .99, y: .06 },
    { text: '皮肤', sub: '只显示位置，不计算', at: [0, 66, -25], obj: 'skin', x: .99, y: .30 },
    { text: '嘴唇肌肉', sub: '软组织，要算的就是它', at: [24, 18, -82], obj: 'lips', x: .99, y: .55 },
    { text: '下颌', sub: '硬的，绕铰链转', at: [60, -40, -128], obj: 'jaw', x: .99, y: .80 },
  ]);
  const jaw = $('#heroJaw'), note = $('#heroNote'), base = note.textContent;
  jaw.addEventListener('input', () => {
    const v = +jaw.value;
    $('#heroJawV').textContent = `${v}°`;
    for (const n of ['jaw', 'teethL']) s.objs.get(n).model = hingeMatrix(v);
    s.dirty = true;
    note.classList.toggle('alert', v > 2);
    note.textContent = v > 2 ? '注意嘴唇没有跟着动。让它跟着动，就是这个项目要算的东西。' : base;
  });
});

/* ---------- layer stack ---------- */
const LAYERS = [
  { id: 'ctrl', name: '控制器', now: '实验室的研究成果', after: '不动', keep: true, sub: '算出 300 个控制点每一帧该怎么动',
    more: '<h4>控制器</h4><p>给定一个目标表情，用优化算法算出控制点的运动。这是实验室论文的成果，第一阶段不移植，我们只接收它算好的结果。</p><p>第二阶段才考虑让它直接调用新的物理层。那时速度是最大的问题，所以现在就要问清楚它怎么用物理。</p>' },
  { id: 'lm', name: '控制点蒙皮', now: 'Maya skinCluster', after: '我们自己写', sub: '把控制点的移动叠到嘴唇上', change: true,
    more: '<h4>控制点蒙皮</h4><p>一个简单的公式，在物理算完以后叠加。在 Maya 里由 skinCluster7 完成，换到新系统要自己实现（任务 T-09）。</p><p>第 6 章可以直接试。</p>' },
  { id: 'phys', name: '物理引擎', now: 'Ziva', after: 'FEBio', sub: '算软组织在重力和骨头带动下怎么变形', change: true,
    more: '<h4>物理引擎</h4><p>这是项目的核心。FEBio 已经在一个小测试模型上确认能算重力加骨头带动软组织，结果能逐帧放回 Blender，回放误差小于 0.000001 mm。真实嘴唇还没有算过。</p><p>Ziva 在 Maya 里是一个插件；FEBio 是独立程序，输入输出都是文件，所以每一步都能检查。</p>' },
  { id: 'ui', name: '操作和显示', now: 'Maya', after: 'Blender', sub: '导入模型、发起计算、看结果', change: true,
    more: '<h4>操作和显示</h4><p>Blender 里做一个面板：导入、运行、回放、比较。计算不放在 Blender 里，它只负责界面（第 7 章）。</p><p>Maya 只在迁移时用一次，导出数据以后就不需要了。</p>' },
];
(function stackUI() {
  const host = $('#stack'), detail = $('#stackDetail');
  let after = false, open = 'phys';
  const render = () => {
    host.innerHTML = LAYERS.map((l) => `<button type="button" class="layer ${l.keep ? 'keep' : ''} ${after && l.change ? 'changes' : ''}" aria-expanded="${l.id === open}" data-id="${l.id}">
      <b>${l.name}</b><span class="who">${after ? l.after : l.now}</span><small>${l.sub}</small></button>`).join('');
    detail.innerHTML = LAYERS.find((l) => l.id === open).more;
  };
  host.addEventListener('click', (e) => { const b = e.target.closest('.layer'); if (b) { open = b.dataset.id; render(); } });
  $('#stackNow').onclick = () => { after = false; $('#stackNow').classList.add('on'); $('#stackAfter').classList.remove('on'); render(); };
  $('#stackAfter').onclick = () => { after = true; $('#stackAfter').classList.add('on'); $('#stackNow').classList.remove('on'); render(); };
  render();
})();

/* ---------- soft tissue toy ---------- */
(function toy() {
  const c = $('#toy'), g = c.getContext('2d'), W = 960, H = 600, CX = 480, CY = 235;
  const RINGS = 5, SECT = 44, P = [], S = [];
  const lerp = (a, b, t) => a + (b - a) * t;
  for (let r = 0; r < RINGS; r++) for (let s = 0; s < SECT; s++) {
    const t = r / (RINGS - 1), th = 2 * Math.PI * s / SECT;
    const x = CX + lerp(92, 225, t) * Math.cos(th), y = CY + lerp(6, 112, t) * Math.sin(th);
    P.push({ x, y, px: x, py: y, rx: x, ry: y, th, r, a: null });
  }
  const at = (r, s) => r * SECT + ((s + SECT) % SECT);
  const link = (a, b) => S.push([a, b, Math.hypot(P[a].x - P[b].x, P[a].y - P[b].y)]);
  for (let r = 0; r < RINGS; r++) for (let s = 0; s < SECT; s++) {
    link(at(r, s), at(r, s + 1));
    if (r < RINGS - 1) { link(at(r, s), at(r + 1, s)); link(at(r, s), at(r + 1, s + 1)); link(at(r, s + 1), at(r + 1, s)); }
  }
  let mode = 'A', jaw = 0, stiff = .45, damp = .55, grab = null, playing = false, frame = 0, clock = 0;
  const JAW = 95;

  function setMode(m) {
    mode = m;
    for (const p of P) {
      p.a = null;
      if (p.r !== RINGS - 1) continue;
      const s = Math.sin(p.th);
      if (m === 'A') p.a = s < -.2 ? 0 : s > .2 ? 1 : .35;
      if (m === 'C' && s > .985) p.a = 1;
    }
  }
  function reset() { for (const p of P) { p.x = p.px = p.rx; p.y = p.py = p.ry; } frame = 0; clock = 0; playing = false; }

  function step(dt) {
    const k = .015 + .55 * stiff * stiff, drag = 1 - .16 * Math.pow(damp, 1.6), G = 420;
    for (const p of P) {
      const vx = (p.x - p.px) * drag, vy = (p.y - p.py) * drag;
      p.px = p.x; p.py = p.y;
      p.x += vx; p.y += vy + G * dt * dt;
    }
    for (let it = 0; it < 8; it++) {
      for (const [a, b, l] of S) {
        const A = P[a], B = P[b], dx = B.x - A.x, dy = B.y - A.y, d = Math.hypot(dx, dy) || 1, e = (d - l) / d * .5 * k;
        A.x += dx * e; A.y += dy * e; B.x -= dx * e; B.y -= dy * e;
      }
      for (const p of P) {
        if (p.a !== null) { p.x = p.rx; p.y = p.ry + p.a * jaw * JAW; }
        if (p === grab) { p.x = grab.gx; p.y = grab.gy; }
        if (p.y > H - 8) p.y = H - 8;
      }
    }
  }

  function draw() {
    const muscle = css('--muscle'), bone = css('--bone'), ink = css('--ink'), dim = css('--dim'), film = css('--plate-2');
    g.clearRect(0, 0, W, H);
    g.fillStyle = bone; g.globalAlpha = .28;
    g.beginPath(); g.roundRect(150, 20, 660, 92, 40); g.fill();
    g.beginPath(); g.roundRect(170, 362 + jaw * JAW, 620, 150, 56); g.fill();
    g.globalAlpha = 1;
    g.fillStyle = dim; g.font = '500 20px ' + css('--sans');
    g.fillText('颅骨（固定）', 410, 74);
    g.fillText('下颌（跟着滑块动）', 390, 470 + jaw * JAW);
    g.fillStyle = muscle; g.globalAlpha = .52;
    for (let r = 0; r < RINGS - 1; r++) for (let s = 0; s < SECT; s++) {
      const a = P[at(r, s)], b = P[at(r, s + 1)], d = P[at(r + 1, s + 1)], e = P[at(r + 1, s)];
      g.beginPath(); g.moveTo(a.x, a.y); g.lineTo(b.x, b.y); g.lineTo(d.x, d.y); g.lineTo(e.x, e.y); g.closePath(); g.fill();
    }
    g.globalAlpha = 1; g.strokeStyle = muscle; g.lineWidth = 1;
    g.beginPath();
    for (const [a, b] of S) { g.moveTo(P[a].x, P[a].y); g.lineTo(P[b].x, P[b].y); }
    g.globalAlpha = .4; g.stroke(); g.globalAlpha = 1;
    for (const p of P) {
      if (p.a !== null) { g.fillStyle = ink; g.fillRect(p.x - 4, p.y - 4, 8, 8); }
      else { g.fillStyle = muscle; g.beginPath(); g.arc(p.x, p.y, 2.6, 0, 7); g.fill(); }
    }
    g.fillStyle = film;
  }

  function phase(f) { return f < 15 ? '重力沉降：下颌不动' : f < 33 ? '下颌张开' : '下颌合上'; }
  let last = 0, on = false;
  function run(t) {
    requestAnimationFrame(run);
    if (!on) return;
    const dt = Math.min(.04, (t - last) / 1000 || .016); last = t;
    if (playing) {
      clock += dt; frame = Math.min(49, Math.floor(clock * 7.5));
      const u = frame < 15 ? 0 : frame < 33 ? (frame - 15) / 18 : (49 - frame) / 16;
      jaw = u * u * (3 - 2 * u);
      $('#toyJaw').value = jaw * 100;
      $('#frameRead').textContent = `第 ${frame} 帧 · ${phase(frame)}（放慢 4 倍）`;
      $('#fbA').style.background = frame < 15 ? css('--muscle') : css('--signal');
      $('#fbB').style.background = frame >= 15 ? css('--muscle') : css('--rule');
      if (frame >= 49) { playing = false; $('#frameRead').textContent = '第 49 帧 · 播放结束'; }
    }
    for (let i = 0; i < 2; i++) step(1 / 120);
    draw();
  }
  new IntersectionObserver((e) => { on = e[0].isIntersecting; }).observe(c);
  requestAnimationFrame(run);

  $$('[data-anchor]').forEach((b) => b.addEventListener('click', () => {
    $$('[data-anchor]').forEach((x) => x.classList.toggle('on', x === b));
    setMode(b.dataset.anchor);
    $('#toyCap').textContent = {
      A: '方案 A：上半圈挂颅骨，下半圈挂下颌，嘴角居中。方块是被固定的点。',
      C: '方案 C：只剩下颌上几个点挂着，整圈组织靠这几个点吊住。这就是"什么都不补"的后果。',
      N: '什么都不挂：组织直接掉下去。真实计算里，这种情况 FEBio 会一直算到组织落到无穷远。',
    }[b.dataset.anchor];
  }));
  $('#toyJaw').addEventListener('input', (e) => { playing = false; jaw = e.target.value / 100; });
  $('#toyStiff').addEventListener('input', (e) => { stiff = e.target.value / 100; });
  $('#toyDamp').addEventListener('input', (e) => { damp = e.target.value / 100; });
  $('#toyPlay').addEventListener('click', () => { reset(); playing = true; jaw = 0; });
  $('#toyReset').addEventListener('click', () => { reset(); jaw = 0; $('#toyJaw').value = 0; $('#frameRead').textContent = '第 0 帧'; });
  const toXY = (e) => { const r = c.getBoundingClientRect(); return [(e.clientX - r.left) * W / r.width, (e.clientY - r.top) * H / r.height]; };
  c.addEventListener('pointerdown', (e) => {
    const [x, y] = toXY(e); let best = null, bd = 900;
    for (const p of P) { const d = (p.x - x) ** 2 + (p.y - y) ** 2; if (d < bd) { bd = d; best = p; } }
    if (best) { grab = best; grab.gx = x; grab.gy = y; c.setPointerCapture(e.pointerId); }
  });
  c.addEventListener('pointermove', (e) => { if (grab) { [grab.gx, grab.gy] = toXY(e); } });
  c.addEventListener('pointerup', () => { grab = null; });
  setMode('A');
  for (let i = 0; i < 400; i++) step(1 / 120);
  draw();
})();

/* ---------- parts explorer ---------- */
whenNear($('#partStage'), () => {
  const s = new Stage($('#partStage'), { az: .6, el: .1, dist: 900, target: [0, -118, 2], label: '原型用到的部件' });
  if (s.dead) return;
  addHead(s, 'hide');
  const rows = $$('#partTable tr[data-part]');
  const only = (name) => {
    for (const [k, ob] of s.objs) if (k !== 'skin') ob.show = !name || k === name;
    rows.forEach((r) => { r.style.fontWeight = r.dataset.part === name ? '700' : ''; });
    if (name) { const b = bounds(mesh(name).pos); s.target = b.c; s.dist = Math.max(160, b.r * 3.4); } else { s.target = [0, -118, 2]; s.dist = 900; }
    s.dirty = true;
  };
  rows.forEach((r) => r.addEventListener('click', () => only(r.dataset.part)));
  $('#partAll').onclick = () => only(null);
  const wire = $('#partWire');
  wire.onclick = () => {
    const on = wire.getAttribute('aria-pressed') !== 'true';
    wire.setAttribute('aria-pressed', on);
    for (const [k, ob] of s.objs) if (k !== 'skin') ob.wire = on;
    s.dirty = true;
  };
  const skin = $('#partSkin');
  skin.onclick = () => {
    const on = skin.getAttribute('aria-pressed') !== 'true';
    skin.setAttribute('aria-pressed', on);
    s.objs.get('skin').show = on; s.dirty = true;
  };
});
function bounds(p) {
  const lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9];
  for (let i = 0; i < p.length; i += 3) for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], p[i + k]); hi[k] = Math.max(hi[k], p[i + k]); }
  return { c: lo.map((v, i) => (v + hi[i]) / 2), r: Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) / 2, size: hi.map((v, i) => v - lo[i]) };
}

/* ---------- pipeline stepper (every output below is a real run) ---------- */
const code = (id) => $(`#code-${id}`).innerHTML;
const P = [
  { t: '盘点文件', why: '<p>Maya 文件虽然没有公开文档，但它的结构是一层套一层的数据块。我们写了一个<strong>不需要 Maya</strong> 的读取工具，把整个场景列成一份清单：有哪些节点、怎么连接、存了哪些数值。</p><p>这一步回答的问题是：文件里到底有什么。</p>',
    cmd: 'uv run python tools/mb_inventory.py "assets/v36 dev_proxy_jaw_oor V3 more aggressive delete done.mb" data/asset_inventory.json',
    code: 'walk', codeNote: '逐块遍历文件结构，这是读取工具的核心',
    out: '14368 nodes, 21716 connections, 41 unparsed chunks -> data/asset_inventory.json' },
  { t: '列出事实', why: '<p>从清单里整理出设计要用的事实：哪些是软组织、谁粘着谁、材料存了什么值、运动是怎么传递的。项目的资产说明（<code>docs/03</code>）里的每个数字都能用这条命令重新算出来。</p><p><strong>结论有好有坏：</strong>节点、连接、权重、顶点坐标都读得出。但网格的<strong>面</strong>（哪些点连成三角形）读不出来，编码没有公开。只有点没有面，进不了物理计算。</p>',
    cmd: 'uv run python tools/asset_report.py data/asset_inventory.json',
    out: '<span class="c">## ziva node counts</span>\nzTissue 41, zBone 10, zCloth 2, zAttachment 140, zMaterial 43, zTet 41, zFiber 18, zEmbedder 1, zGeo 54\n\n<span class="c">## bodies whose source mesh is still in the file</span>\ntissue zTissue1: middleres_OrbicularisOrisShapeOrig, tet size 26.37, collisions 0.0\n\n<span class="c">## materials: stored (non-default) values</span>\nzMaterial numeric values stored: 0 {}\n\n<span class="c">## attachments touching the lip tissue (zTissue1)</span>\ndistinct lip vertices with an attachment weight > 0 (lip as source): 733 of 10240' },
  { t: '用 Maya 导出', why: '<p>面读不出来，就请 Maya 自己把网格写出来。实验室给了非 Ziva 版场景，本机的普通 Maya 就能打开，用它自带的命令行 Python（<button class="t" data-g="mayapy">mayapy</button>）跑脚本，全程不用打开界面。</p><p><strong>有个陷阱：</strong>直接导出网格，拿到的是已经被控制点变形过的形状。我们要的是变形之前的<button class="t" data-g="ShapeOrig">静止形状</button>。所以脚本读的是 <code>ShapeOrig</code>，并且把坐标含义写死成场景坐标。</p>',
    cmd: '"C:\\Program Files\\Autodesk\\Maya2027\\bin\\mayapy.exe" tools/maya_export.py "assets/w64 from v36 proxy delete done non ziva.mb" data/lab_export',
    code: 'write_obj', codeNote: '自己写 OBJ 文件，保证顶点顺序和坐标含义都由我们决定',
    out: 'middleres_OrbicularisOris     10240 v  20480 f  size [92.31, 75.2, 45.82]\nmiddleres_Jaw                  7426 v  14848 f  size [196.79, 146.52, 155.92]\nmiddleres_skull               28414 v  28416 f  size [225.19, 252.72, 310.97]\nmiddleres_TeethUp             24608 v  24576 f  size [86.78, 30.47, 78.46]\nmiddleres_TeethDown           24608 v  24576 f  size [80.15, 23.35, 70.11]\nskinCluster7: 300 influences, 10240 vertices, weight sum 1.000000..1.000000, at most 20 per vertex, bind error 5.6e-15\n301 joints, jaw hinge at [0.0, -56.812, 126.52]\n36.7 s -> data/lab_export\n<span class="good">EXPORT CHECK PASSED</span>' },
  { t: '独立核对', why: '<p>Maya 导出的网格对不对？用第 1 步那条不经过 Maya 的路线，直接从 <code>.mb</code> 读顶点，套上变换，再和导出的文件<strong>逐点比较</strong>。两条独立的路线得到同样的数字，说明顶点、顶点顺序和我们的读取工具都是对的。变换矩阵两边共用，它的独立依据是从 OBJ 量出的下颌尺寸 155.92。</p><p>同时检查网格能不能围成实体：有没有开口的边、有没有一条边连着三个面。嘴唇封闭、只有一块，是个环。上下牙各 16 块，正好是 16 颗牙。</p><p>控制点权重和关节没有走这条路线，目前只有 Maya 自检。</p>',
    cmd: 'uv run python tools/check_lab_export.py data/lab_export "assets/w64 from v36 proxy delete done non ziva.mb"',
    code: 'mesh_health', codeNote: '检查网格是否封闭：每条边都应该正好被两个面共用',
    variants: {
      '正常': 'mesh                          verts  worst diff open edges bad edges pieces\nmiddleres_OrbicularisOris     10240   0.0000000          0         0      1\nmiddleres_Jaw                  7426   0.0000000          0         0      1\nmiddleres_skull               28414   0.0000000          0         0      1\nmiddleres_TeethUp             24608   0.0000000          0         0     16\nmiddleres_TeethDown           24608   0.0000000          0         0     16\n\njaw z size 155.92 measured from the OBJ (expected 155.92)\n<span class="good">LAB EXPORT CHECK PASSED</span>',
      '故意调换两个嘴唇顶点': 'mesh                          verts  worst diff open edges bad edges pieces\nmiddleres_OrbicularisOris     10240  <span class="fail">62.3499436</span>          0         0      1\nmiddleres_Jaw                  7426   0.0000000          0         0      1\nmiddleres_skull               28414   0.0000000          0         0      1\nmiddleres_TeethUp             24608   0.0000000          0         0     16\nmiddleres_TeethDown           24608   0.0000000          0         0     16\n\njaw z size 155.92 measured from the OBJ (expected 155.92)\n<span class="fail">LAB EXPORT CHECK FAILED</span>',
      '故意多套一次变换': 'mesh                          verts  worst diff open edges bad edges pieces\nmiddleres_OrbicularisOris     10240    0.0000000          0         0      1\nmiddleres_Jaw                  7426 <span class="fail">550.3287350</span>          0         0      1\nmiddleres_skull               28414   0.0000000          0         0      1\nmiddleres_TeethUp             24608   0.0000000          0         0     16\nmiddleres_TeethDown           24608   0.0000000          0         0     16\n\njaw z size <span class="fail">372.16</span> measured from the OBJ (expected 155.92)\n<span class="fail">LAB EXPORT CHECK FAILED</span>',
      '故意删掉一半嘴唇的面': 'mesh                          verts  worst diff open edges bad edges pieces\nmiddleres_OrbicularisOris     10240    0.0000000        <span class="fail">128</span>         0      1\nmiddleres_Jaw                  7426   0.0000000          0         0      1\nmiddleres_skull               28414   0.0000000          0         0      1\nmiddleres_TeethUp             24608   0.0000000          0         0     16\nmiddleres_TeethDown           24608   0.0000000          0         0     16\n\njaw z size 155.92 measured from the OBJ (expected 155.92)\n<span class="fail">LAB EXPORT CHECK FAILED</span>',
    } },
  { t: '导入 Blender', why: '<p>OBJ 已经是场景坐标，这里再做两件事：换算成毫米，再把 Y 朝上转成 Z 朝上。然后在 Blender 里把每个顶点读回来，和预期值比较。</p><p>脚本还做了几个防错检查：嘴唇要在颅骨前面、转轴要是左右方向、下颌张开时下巴必须往下走。写这个脚本时，最后这条检查真的抓到了一个 bug：下颌父子关系的偏移算错了，下巴反而抬高了 1.3 mm。</p>',
    cmd: 'blender --background --factory-startup --python-exit-code 1 --python tools/blender_import_preview.py -- data/lab_export data/preview',
    code: 'to_mm_zup', codeNote: '单位和坐标轴转换就这一行',
    out: 'object          verts  faces  size in mm (x y z)\nlips            10240  20480    88.8   44.1   72.3\njaw              7426  14848   189.3  150.0  141.0\nskull           28414  28416   216.6  299.1  243.1\nteeth_upper     24608  24576    83.5   75.5   29.3\nteeth_lower     24608  24576    77.1   67.4   22.5\nskin_context    15905  15636   264.4  264.1  375.6\nworst vertex difference after import: 0.000015 mm\nchin drops 32.1 mm at 15 degrees\n58 s -> data/preview\n<span class="good">BLENDER IMPORT PREVIEW PASSED</span>' },
  { t: '接到产品（待开发）', why: '<p>到这一步，真实资产已经能进 Blender，但这只是预览，还不是原型。接下来：</p><ul><li><strong>T-02</strong> 把同样的步骤做成正式命令 <code>asrp import-asset</code>，生成场景描述文件；</li><li><strong>T-04</strong> 把嘴唇的空壳填成四面体；</li><li><strong>T-06</strong> 第一次用真实资产完整跑一遍 FEBio。</li></ul><p><strong>"资产能在 Blender 里显示"不等于原型。</strong>它只是 M1 的一部分。原型要能算物理、叠控制点、和 Ziva 并排比较，并且研究员能自己走完全流程。</p>',
    todo: true, cmd: 'asrp import-asset data/lab_export   # T-02，待开发',
    out: '<span class="c">(not built yet: this is the next task)</span>' },
];
(function pipeline() {
  const steps = $('#pipeSteps'), body = $('#pipeBody');
  let cur = 0, variant = '正常';
  const render = () => {
    const s = P[cur];
    steps.innerHTML = P.map((p, i) => `<button type="button" role="tab" aria-selected="${i === cur}" class="${i === cur ? 'on' : i < cur ? 'done' : ''}" data-i="${i}"><i>第 ${i + 1} 步</i>${p.t}</button>`).join('');
    const out = s.variants ? s.variants[variant] : s.out;
    const vb = s.variants ? `<div class="seg" style="margin:8px 0 2px">${Object.keys(s.variants).map((k) => `<button type="button" class="btn ${k === variant ? 'on' : ''}" data-v="${k}">${k}</button>`).join('')}</div>` : '';
    body.innerHTML = `<div class="step-grid"><div class="detail">${s.why}</div><div>
      <div class="lab">命令</div><pre class="term cmd"><span class="p">$</span> ${s.cmd}</pre>
      <div class="lab">${s.todo ? '输出' : '真实输出'}</div>${vb}<pre class="term">${out}</pre></div></div>
      ${s.code ? `<div class="lab">代码节选 · ${s.codeNote}</div><pre class="term" style="max-height:300px">${code(s.code)}</pre>` : ''}`;
  };
  steps.addEventListener('click', (e) => { const b = e.target.closest('[data-i]'); if (b) { cur = +b.dataset.i; render(); } });
  body.addEventListener('click', (e) => { const b = e.target.closest('[data-v]'); if (b) { variant = b.dataset.v; render(); } });
  render();
})();

/* ---------- coordinate stepper ---------- */
whenNear($('#xfStage'), () => {
  const s = new Stage($('#xfStage'), { az: .75, el: .32, dist: 1700, target: [0, -40, 90], label: '下颌的坐标换算' });
  if (s.dead) return;
  const jaw = mesh('jaw'), k = D.mmPerUnit;
  s.add('jaw', jaw, { color: BONE });
  const grid = [], R = 150;
  for (const x of [-R, 0, R]) grid.push(x, -R, 0, x, R, 0, -R, x, 0, R, x, 0);
  s.addLines('grid', new Float32Array(grid), [.5, .6, .65, .7]);
  s.addLines('x', new Float32Array([0, 0, 0, 170, 0, 0]), [.8, .2, .2, 1]);
  s.addLines('y', new Float32Array([0, 0, 0, 0, 170, 0]), [.2, .7, .3, 1]);
  s.addLines('z', new Float32Array([0, 0, 0, 0, 0, 170]), [.2, .4, .9, 1]);

  /* The stored mesh is the final mm, Z-up shape; step back from it to each earlier stage. */
  const toScene = [1 / k, 0, 0, 0, 0, 0, -1 / k, 0, 0, 1 / k, 0, 0, 0, 0, 0, 1];
  const W = D.jawWorld, W1 = M.inv(W);
  const STEPS = [
    { n: '0 网格自己记录的坐标', m: M.mul(W1, toScene), u: '单位', t: '<p>这是 <code>ShapeOrig</code> 里存的原始数字，叫物体坐标。还没放进场景，尺寸是实际的 40% 左右。</p>' },
    { n: '1 套用网格的变换：场景坐标', m: toScene, u: '单位', t: '<p>放大 2.54 倍、旋转、平移。这时 z 方向是 <strong>155.92</strong>。实验室论文里写着"下颌宽 155.92 个单位"，数字完全一样，说明这一步对了。（这个数在模型里其实是前后方向，要向实验室确认。）<strong>这一步在导出时完成。</strong></p>' },
    { n: '2 换成毫米', m: M.mul(M.scale(k), toScene), u: 'mm', t: '<p>乘 0.962。这个系数来自论文：1 个场景单位约 0.962 mm。下颌的 155.92 单位由此变成 150.0 mm。但这样换算后模型大约是真人的 1.5 倍，还在等实验室确认，所以它是设置项，不写死。</p>' },
    { n: '3 Y 朝上转成 Z 朝上', m: M.id(), u: 'mm', t: '<p>Maya 的场景 Y 朝上，Blender 和我们的计算 Z 朝上。公式是 <code>(x, y, z) → (x, -z, y)</code>。这是旋转，不是镜像，左右不会对调。下颌现在是正的了。</p>' },
    { n: '错误示范：再套一次变换', m: M.mul(W, toScene), u: '单位', bad: true, t: '<p class="s-bad"><strong>这是错的。</strong>OBJ 已经是场景坐标，再套一次，整体大 2.54 倍，还多转了一次，所以各方向的数字互相换了位置，z 方向变成 372。程序不会报错，重力和质量的效果全错。所以我们用 155.92 这个数字守着它。</p>' },
  ];
  const btns = $('#xfBtns'), info = $('#xfInfo');
  let cur = 3, from = STEPS[3].m, to = from, t = 1;
  const apply = () => {
    const box = STEPS[cur];
    const pts = new Float32Array(jaw.pos.length);
    for (let i = 0; i < jaw.pos.length; i += 3) pts.set(M.apply(box.m, [jaw.pos[i], jaw.pos[i + 1], jaw.pos[i + 2]]), i);
    const size = bounds(pts).size.map((v) => v.toFixed(1));
    info.innerHTML = `${box.t}<p class="mono" style="margin-top:6px">尺寸 ${size.join(' / ')} ${box.u}</p>`;
    btns.innerHTML = STEPS.map((x, i) => `<button type="button" class="btn ${i === cur ? 'on' : ''}" data-i="${i}" style="text-align:left">${x.n}</button>`).join('');
  };
  const anim = () => {
    t = Math.min(1, t + (reduced ? 1 : .05));
    const e = t * t * (3 - 2 * t);
    s.objs.get('jaw').model = from.map((v, i) => v + (to[i] - v) * e);
    s.dirty = true;
    if (t < 1) requestAnimationFrame(anim);
  };
  btns.addEventListener('click', (e) => {
    const b = e.target.closest('[data-i]');
    if (!b) return;
    from = s.objs.get('jaw').model; cur = +b.dataset.i; to = STEPS[cur].m; t = 0;
    apply(); anim();
  });
  apply();
});

/* ---------- compare slider ---------- */
(function compare() {
  const c = $('#cmp');
  const set = (x) => { const r = c.getBoundingClientRect(); c.style.setProperty('--x', `${Math.max(0, Math.min(100, (x - r.left) / r.width * 100))}%`); };
  let on = false;
  c.addEventListener('pointerdown', (e) => { on = true; c.setPointerCapture(e.pointerId); set(e.clientX); });
  c.addEventListener('pointermove', (e) => { if (on) set(e.clientX); });
  c.addEventListener('pointerup', () => { on = false; });
  c.setAttribute('tabindex', '0'); c.setAttribute('role', 'slider'); c.setAttribute('aria-label', '比较闭合和张开');
  let v = 50;
  c.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft') v = Math.max(0, v - 5); else if (e.key === 'ArrowRight') v = Math.min(100, v + 5); else return;
    c.style.setProperty('--x', `${v}%`);
  });
})();

/* ---------- attachments ---------- */
whenNear($('#attStage'), () => {
  const lips = mesh('lips'), b = bounds(lips.pos);
  const s = new Stage($('#attStage'), { az: .35, el: .05, dist: 300, target: b.c, label: '嘴唇上带粘连的顶点' });
  if (s.dead) return;
  s.add('lips', lips, { color: [.46, .22, .25] });
  const pts = [], cols = [];
  const blue = [.2, .75, .9], bone = [.95, .8, .4];
  for (const [name, str] of Object.entries(D.attach)) {
    const col = /jaw/i.test(name) ? blue : bone;
    for (const v of u16(str)) { pts.push(lips.pos[v * 3], lips.pos[v * 3 + 1], lips.pos[v * 3 + 2]); cols.push(...col); }
  }
  s.setPoints(new Float32Array(pts), new Float32Array(cols), 4);
});

/* ---------- landmark layer: real skin weights, the T-09 formula for a translated joint ---------- */
whenNear($('#lmStage'), () => {
  const lips = mesh('lips'), b = bounds(lips.pos);
  const s = new Stage($('#lmStage'), { az: .0, el: .02, dist: 290, target: b.c, label: '嘴唇和 300 个控制点' });
  if (s.dead) return;
  const L = D.landmarks, lp = f32(L.pos), off = u32(L.off), vs = u16(L.v), ws = bytes(L.w);
  const N = lp.length / 3, base = lips.pos, pos = base.slice();
  s.add('lips', { ...lips, pos: pos, nor: lips.nor.slice() }, { color: LIP });
  const pc = new Float32Array(N * 3), heat = new Float32Array(base.length);
  const deltas = new Map();
  const landmarkAt = (i) => [lp[i * 3], lp[i * 3 + 1], lp[i * 3 + 2]];
  const moved = () => {
    const p = new Float32Array(N * 3);
    p.set(lp);
    for (const [i, d] of deltas) for (let k = 0; k < 3; k++) p[i * 3 + k] += d[k];
    return p;
  };
  s.setPoints(lp.slice(), pc, 7);
  let sel = 0;
  const recolor = () => {
    for (let i = 0; i < N; i++) pc.set(i === sel ? [1, .85, .2] : [.15, .65, .9], i * 3);
    s.pointColors(pc);
    for (let i = 0; i < heat.length; i += 3) heat.set(LIP, i);
    let most = 0;
    for (let e = off[sel]; e < off[sel + 1]; e++) {
      const w = ws[e] / 255, v = vs[e] * 3, h = Math.pow(w, .55);
      most = Math.max(most, w);
      heat[v] = LIP[0] + (1 - LIP[0]) * h; heat[v + 1] = LIP[1] + (.85 - LIP[1]) * h; heat[v + 2] = LIP[2] + (.2 - LIP[2]) * h;
    }
    s.colors('lips', heat);
    $('#lmInfo').textContent = `oor_${String(sel + 1).padStart(2, '0')} · 影响 ${off[sel + 1] - off[sel]} 个顶点 · 最大权重 ${most.toFixed(2)}`;
    const d = deltas.get(sel) || [0, 0, 0];
    ['X', 'Y', 'Z'].forEach((a, k) => { $(`#lm${a}`).value = d[k]; $(`#lm${a}V`).textContent = `${d[k]} mm`; });
  };
  const deform = () => {
    pos.set(base);
    for (const [i, d] of deltas) for (let e = off[i]; e < off[i + 1]; e++) {
      const w = ws[e] / 255, v = vs[e] * 3;
      pos[v] += w * d[0]; pos[v + 1] += w * d[1]; pos[v + 2] += w * d[2];
    }
    s.update('lips', pos, normals(pos, lips.idx));
    const gl = s.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, null);
    s.points.pos = moved();
    s.movePoints(s.points.pos);
  };
  s.movePoints = (p) => {
    const gl = s.gl;
    gl.bindVertexArray(s.points.vao);
    const buf = gl.getVertexAttrib(0, gl.VERTEX_ATTRIB_ARRAY_BUFFER_BINDING);
    gl.bindBuffer(gl.ARRAY_BUFFER, buf); gl.bufferSubData(gl.ARRAY_BUFFER, 0, p);
    gl.bindVertexArray(null); s.dirty = true;
  };
  s.onpick = (x, y) => {
    let best = -1, bd = 400;
    const p = s.points.pos;
    for (let i = 0; i < N; i++) {
      const [sx, sy] = s.project([p[i * 3], p[i * 3 + 1], p[i * 3 + 2]]);
      const d = (sx - x) ** 2 + (sy - y) ** 2;
      if (d < bd) { bd = d; best = i; }
    }
    if (best >= 0) { sel = best; recolor(); }
  };
  ['X', 'Y', 'Z'].forEach((a, k) => $(`#lm${a}`).addEventListener('input', (e) => {
    const d = deltas.get(sel) || [0, 0, 0];
    d[k] = +e.target.value; deltas.set(sel, d);
    $(`#lm${a}V`).textContent = `${d[k]} mm`;
    deform();
  }));
  $('#lmReset').onclick = () => { deltas.clear(); deform(); recolor(); };
  $('#lmSmile').onclick = () => {
    deltas.clear();
    const order = [...Array(N).keys()].sort((a, c) => Math.abs(lp[c * 3]) - Math.abs(lp[a * 3])).slice(0, 44);
    const w = Math.max(...order.map((i) => Math.abs(lp[i * 3])));
    for (const i of order) {
      const f = Math.pow(Math.abs(lp[i * 3]) / w, 3), x = Math.sign(lp[i * 3]);
      deltas.set(i, [x * 7 * f, 0, 9 * f]);
    }
    deform();
  };
  let bestI = 0, score = -1e9;
  for (let i = 0; i < N; i++) { const [x, y, z] = landmarkAt(i); const c = y + z * .4 - Math.abs(x) * 2; if (c > score) { score = c; bestI = i; } }
  sel = bestI;
  recolor();
});

/* ---------- architecture ---------- */
const ARCH = [
  { n: '实验室场景', f: '.mb', st: '已有', t: '<h4>实验室场景</h4><p>完整版和非 Ziva 版两个文件，放在 <code>assets/</code>，绝不提交。</p>' },
  { n: 'Maya 导出', f: 'tools/maya_export.py', st: '已完成', t: '<h4>Maya 导出</h4><p>一次性迁移工具，用 mayapy 运行。产品不依赖它，自动检查也不需要 Maya。</p>' },
  { n: '开放格式文件', f: 'data/lab_export/', st: '已完成', t: '<h4>开放格式文件</h4><p>OBJ 网格（场景坐标）、控制点权重、关节位置。网格已和 <code>.mb</code> 逐点核对。</p>' },
  { n: '导入', f: 'asrp import-asset · T-02', st: '待开发', t: '<h4>导入</h4><p>换算成毫米、转成 Z 朝上，生成场景描述。单位系数是设置项，每个参数都记录来源：实验室设置、Ziva 默认值，或者我们定的。</p>' },
  { n: '场景描述', f: 'scene.json · T-05', st: '待开发', t: '<h4>场景描述</h4><p>我们自己定义的文件，完整描述一个要计算的模型：软组织、骨头、粘连、控制点、求解设置。几乎所有任务都靠它交接，所以要最先定。</p><p>长期看它才是核心：Ziva 停售以后，新模型要直接在 Blender 里搭，从 Ziva 导入只是一次性的迁移。</p>' },
  { n: '四面体化', f: 'tetmesh.py · T-04', st: '待开发', t: '<h4>四面体化</h4><p>把嘴唇的空壳填成小四面体。Ziva 自动做这一步，我们要自己选工具。嘴唇网格已查过封闭、一块、是个环，但有没有自身穿插还没查。</p>' },
  { n: '生成 FEBio 输入', f: '.feb · T-06', st: '待开发', t: '<h4>生成 FEBio 输入</h4><p>把场景描述翻译成 FEBio 的 XML 输入文件。已知的坑都写在 <code>docs/05</code> 里，比如重力要反号、默认没有阻尼。</p>' },
  { n: 'FEBio 求解', f: 'febio4 -noconfig', st: '已验证', t: '<h4>FEBio 求解</h4><p>独立进程运行，崩溃不影响 Blender。小模型已经在本机跑通，每次自动检查都会重跑。</p>' },
  { n: '运行文件夹', f: 'runs/<时间>/ · T-08', st: '待开发', t: '<h4>运行文件夹</h4><p>每次计算一个文件夹，装着全部输入、输出、版本和参数。任何结果都能追溯到产生它的输入，论文和审稿需要这一点。验收要求同一份输入跑两次，坐标差别不超过 1×10⁻⁹ mm。</p>' },
  { n: '叠加控制点', f: 'skinning.py · T-09', st: '待开发', t: '<h4>叠加控制点</h4><p>物理结果上再叠一层蒙皮。权重已经有了，运动要从 Ziva 机器上拿。</p>' },
  { n: '回放包', f: 'playback.py', st: '已完成', t: '<h4>回放包</h4><p>表面网格加每帧的点位置文件，用 Blender 自带的回放功能（Mesh Cache 修改器）直接播放，不用每帧重建网格。已验证逐帧一致。</p>' },
  { n: 'Blender 面板', f: 'blender_addon/ · T-13', st: '部分完成', t: '<h4>Blender 面板</h4><p>导入、运行、回放、比较，研究员在这里操作。面板里没有任何计算代码，它只调用核心程序。</p>' },
];
(function arch() {
  const host = $('#arch'), info = $('#archInfo');
  let cur = 3;
  const render = () => {
    host.innerHTML = ARCH.map((a, i) => `<button type="button" class="node ${i === cur ? 'on' : ''}" data-i="${i}"><b>${i + 1}. ${a.n}</b><i>${a.f.replace('<', '&lt;').replace('>', '&gt;')}</i><i style="color:var(--${/待/.test(a.st) ? 'dim' : /部分/.test(a.st) ? 'warn' : 'ok'})">${a.st}</i></button>`).join('');
    info.innerHTML = ARCH[cur].t;
  };
  host.addEventListener('click', (e) => { const b = e.target.closest('[data-i]'); if (b) { cur = +b.dataset.i; render(); } });
  render();
})();

/* ---------- sag calculator ---------- */
(function sag() {
  const L = $('#sagL'), E = $('#sagE'), meter = $('#sagMeter'), err = $('#sagErr');
  let k = 1;
  const pct = (v) => (Math.log10(v) + 3) / 6 * 100;
  meter.innerHTML = `<div class="axis"></div><div class="band" style="left:${pct(.1)}%;width:${pct(10) - pct(.1)}%"></div>${[.001, .01, .1, 1, 10, 100, 1000].map((v) => `<span class="tk" style="left:${pct(v)}%">${v}</span>`).join('')}<div class="mark" id="sagMark"></div>`;
  const update = () => {
    const l = +L.value, e = +E.value;
    $('#sagLV').textContent = `${l} mm`; $('#sagEV').textContent = `${e} kPa`;
    const raw = 1e-9 * 9810 * l * l / (e / 1000), v = raw * k;
    $('#sagOut').textContent = `沉降 ≈ 1×10⁻⁹ × 9810 × ${l}² ÷ ${(e / 1000).toFixed(3)}${k !== 1 ? ` × ${k}` : ''} = ${v < .01 ? v.toExponential(1) : v.toFixed(2)} mm`;
    $('#sagMark').style.left = `${Math.max(0, Math.min(100, pct(v)))}%`;
    const inside = v >= .1 && v <= 10;
    const out = $('#sagVerdict');
    if (inside && k === 1) { out.className = 's-ok'; out.textContent = '在范围内，检查通过。'; }
    else if (inside) { out.className = 's-warn'; out.textContent = '检查通过了，但这个结果其实是错的。范围放得很宽，错得不够多就抓不到，所以 T-06 跑完以后要收紧范围。'; }
    else { out.className = 's-bad'; out.textContent = k === 1 ? '超出范围，检查失败。真实运行遇到这种情况，要先查参数是不是写错了。' : '超出范围，检查失败，运行报告标红。'; }
  };
  L.addEventListener('input', update); E.addEventListener('input', update);
  err.addEventListener('click', (e) => {
    const b = e.target.closest('[data-k]');
    if (!b) return;
    k = +b.dataset.k;
    $$('button', err).forEach((x) => x.classList.toggle('on', x === b));
    update();
  });
  update();
})();

/* ---------- roadmap and task graph ---------- */
const TASKS = {
  'T-00': { t: '基础设施', s: 'done', c: 0, r: 0, d: [], m: 'M0', w: '仓库、开发环境、FEBio 动力学试验、结果回放、资产盘点工具、自动检查。', size: '已完成' },
  'T-15': { t: '代码检查工具', s: 'ready', c: 0, r: 1, d: [], m: '', w: '配置 ruff（Python 代码检查器），加进自动检查。不属于任何里程碑。', size: '小', f: 'pyproject.toml、tools/verify.py' },
  'T-05': { t: '场景描述格式', s: 'ready', c: 0, r: 2, d: [], m: 'M1', w: '把场景描述写成正式格式，提供 asrp check 校验。几乎所有任务都靠它交接。', size: '小到中', f: 'src/asrp_core/scene.py、cli.py' },
  'T-04': { t: '嘴唇四面体化', s: 'ready', c: 0, r: 3, d: [], m: 'M2', w: '比较至少两种工具，确认真实嘴唇网格能生成没有压扁的四面体。四面体尺寸试标准、粗一倍、细一倍三档。', size: '中', f: 'tetmesh.py、spikes/、pyproject.toml' },
  'T-03': { t: '读粘连算区域', s: 'ready', c: 0, r: 4, d: [], m: 'M2', w: '从完整版 .mb 读粘连权重，算出方案 A 要把嘴唇的哪些区域挂到哪块骨头上。', size: '中', f: 'tools/、tests/' },
  'T-07': { t: '粘连做法试验', s: 'ready', c: 0, r: 5, d: [], m: 'M2', w: '用小方块比较两种粘连做法：硬绑定（顶点和骨头完全锁死）和弹簧（顶点被弹簧拉向骨头），定下用哪种。结论用在 T-12，T-06 第一版先用硬绑定。', size: '小到中', f: 'spikes/、docs/05、docs/10' },
  'T-01': { t: '约 Ziva 机器', s: 'part', c: 0, r: 6, d: [], m: 'M4', w: '项目负责人带研究员去，一次拿到 Ziva 设置（含权重表）、相邻组织的网格、参考结果和运动。随时可以约，不依赖别的任务；标成部分能开始，是因为清单里的网格和权重已经做完，只剩这些。第 10 章有步骤。', size: '一小时，要约时间', owner: true },
  'T-16': { t: '仓库协作设置', s: 'part', c: 0, r: 7, d: [], m: '', w: '仓库和合并请求模板已就绪，还差邀请成员。分支保护在免费版私有仓库上开不了，靠规矩和审查把关。', size: '小', owner: true },
  'T-02': { t: '资产导入', s: 'wait', c: 1, r: 2, d: ['T-05'], m: 'M1', w: 'asrp import-asset：把导出文件变成场景描述和检查报告。预览工具已经走通了同样的步骤，可以照着做。', size: '中', f: 'src/asrp_core/asset/、cli.py' },
  'T-08': { t: '运行命令', s: 'wait', c: 1, r: 1, d: ['T-05'], m: 'M2', w: 'asrp run：运行文件夹、记录每个结果来自哪些输入（溯源）、进度、取消、出错处理。可以先用现成的 .feb 文件当替身。', size: '中', f: 'run.py、provenance.py、cli.py' },
  'T-06': { t: 'FEBio 生成器', s: 'wait', c: 2, r: 3, d: ['T-02', 'T-03', 'T-04', 'T-05'], m: 'M2', w: '把场景描述翻译成 FEBio 输入，第一次用真实资产完整跑通物理，并加上合理性检查。第一版用标明来源的临时值。', size: '大', f: '生成器模块、plausibility.py、run.py' },
  'T-10': { t: '运动轨迹格式', s: 'wait', c: 2, r: 5, d: ['T-01'], m: 'M3', w: '定义 trajectory.json，把实验室的运动转换过来。', size: '小', f: 'trajectory.py' },
  'T-11': { t: '并排比较工具', s: 'wait', c: 2, r: 7, d: ['T-01'], m: 'M4', w: 'asrp compare：算差别、出热力图，把 Ziva 结果也做成回放包。不判断合格与否。', size: '中', f: 'compare.py、cli.py' },
  'T-12': { t: '换真实数据调参', s: 'wait', c: 3, r: 3, d: ['T-06', 'T-07', 'T-01'], m: 'M2', w: '把临时值换成真实数据，按检查和评审意见调整少数参数。建议上限两周，从真实数据到齐那天开始算。', size: '中到大' },
  'T-09': { t: '控制点变形层', s: 'part', c: 3, r: 5, d: ['T-10'], m: 'M3', w: '权重已有，可以先用人为移动控制点验证。完整验收要等运动和 Ziva 参考结果。', size: '小到中', f: 'skinning.py' },
  'T-13': { t: 'Blender 面板', s: 'part', c: 3, r: 7, d: ['T-02', 'T-08', 'T-11'], m: 'M5', w: '五个小节随对应命令一起做。回放部分已有基础。', size: '中', f: 'blender_addon/' },
  'T-14': { t: '演示和验收', s: 'wait', c: 4, r: 4, d: ['T-12', 'T-09', 'T-13'], m: 'M5', w: '完成验收步骤，写一页给研究员的操作说明。', size: '小到中' },
};
const MILES = [
  ['M0', '基础', 'done', '环境、FEBio、回放'],
  ['M1', '原料就绪', 'now', '网格已导出，差 T-02、T-05'],
  ['M2', '物理段', 'now', '第一版用已有数据和临时值'],
  ['M3', '控制点段', '', '要 Ziva 机器上的运动'],
  ['M4', '对比评审', '', '要参考结果和研究员'],
  ['M5', '界面验收', '', '研究员独立走完全流程'],
];
(function graph() {
  const svg = $('#graph'), W = 150, H = 44, GX = 208, GY = 56, X0 = 6, Y0 = 6;
  const pos = (id) => [X0 + TASKS[id].c * GX, Y0 + TASKS[id].r * GY];
  const rows = Math.max(...Object.values(TASKS).map((t) => t.r)) + 1;
  svg.setAttribute('viewBox', `0 0 ${X0 * 2 + 4 * GX + W} ${Y0 * 2 + rows * GY - (GY - H)}`);
  const ns = 'http://www.w3.org/2000/svg';
  const edges = [];
  for (const [id, t] of Object.entries(TASKS)) for (const d of t.d) {
    const [x1, y1] = pos(d), [x2, y2] = pos(id);
    const p = document.createElementNS(ns, 'path');
    const a = x1 + W, b = y1 + H / 2, c = x2, e = y2 + H / 2, m = (a + c) / 2;
    p.setAttribute('d', `M${a} ${b} C${m} ${b} ${m} ${e} ${c} ${e}`);
    p.setAttribute('class', 'edge'); svg.appendChild(p);
    edges.push({ p, from: d, to: id });
  }
  const nodes = {};
  for (const [id, t] of Object.entries(TASKS)) {
    const [x, y] = pos(id), g = document.createElementNS(ns, 'g');
    g.setAttribute('class', `tn st-${t.s}`); g.setAttribute('transform', `translate(${x} ${y})`);
    g.setAttribute('tabindex', '0'); g.setAttribute('role', 'button'); g.setAttribute('aria-label', `${id} ${t.t}`);
    g.innerHTML = `<rect width="${W}" height="${H}" rx="4"></rect><text class="id" x="9" y="17">${id}</text><text x="9" y="35">${t.t}</text>`;
    g.addEventListener('click', () => pick(id));
    g.addEventListener('keydown', (e) => { if (e.key === 'Enter') pick(id); });
    svg.appendChild(g); nodes[id] = g;
  }
  const info = $('#taskInfo');
  const STATE = { done: '已完成', ready: '现在能开始', part: '部分能开始', wait: '在等前面的任务' };
  const after = (id) => Object.entries(TASKS).filter(([, t]) => t.d.includes(id)).map(([k]) => k);
  function mark(keep, sel) {
    for (const [id, g] of Object.entries(nodes)) {
      g.classList.toggle('dim', !!keep && !keep.has(id));
      g.classList.toggle('sel', id === sel);
    }
    for (const e of edges) e.p.classList.toggle('hot', !!keep && keep.has(e.from) && keep.has(e.to) && (!sel || e.from === sel || e.to === sel));
  }
  function pick(id) {
    const t = TASKS[id], keep = new Set([id, ...t.d, ...after(id)]);
    mark(keep, id);
    info.innerHTML = `<h4>${id} ${t.t}</h4><p>${t.w}</p><p class="mono" style="font-size:12.5px;color:var(--dim)">${STATE[t.s]} · 规模 ${t.size}${t.d.length ? ` · 依赖 ${t.d.join('、')}` : ''}${after(id).length ? ` · 完成后解锁 ${after(id).join('、')}` : ''}${t.f ? ` · 改动 ${t.f}` : ''}${t.owner ? ' · 负责人：项目负责人' : ''}</p>`;
  }
  const track = $('#track');
  track.innerHTML = MILES.map(([id, n, st, sub]) => `<button type="button" class="ms ${st}" data-m="${id}"><b>${id} ${n}</b>${sub}</button>`).join('');
  track.addEventListener('click', (e) => {
    const b = e.target.closest('[data-m]');
    if (!b) return;
    $$('.ms', track).forEach((x) => x.classList.toggle('on', x === b));
    const keep = new Set(Object.entries(TASKS).filter(([, t]) => t.m === b.dataset.m).map(([k]) => k));
    mark(keep, null);
    const m = MILES.find(([id]) => id === b.dataset.m);
    info.innerHTML = `<h4>${m[0]} ${m[1]}</h4><p>${m[3]}。包含：${[...keep].join('、')}。</p>`;
  });
  $('#fReady').onclick = () => {
    mark(new Set(['T-01', ...Object.entries(TASKS).filter(([, t]) => t.s === 'ready').map(([k]) => k)]), null);
    info.innerHTML = '<h4>现在能开始的</h4><p>绿框的任务互不依赖，可以同时开工。T-01 由项目负责人做，只差约时间。</p>';
  };
  $('#fPath').onclick = () => {
    const path = new Set(['T-05', 'T-02', 'T-06', 'T-12', 'T-14']);
    mark(path, null);
    edges.forEach((e) => e.p.classList.toggle('hot', path.has(e.from) && path.has(e.to)));
    info.innerHTML = '<h4>主线</h4><p>T-05 定格式 → T-02 导入 → T-06 跑通物理 → T-12 换真实数据 → T-14 验收。主线上任何一环卡住，后面都走不了。T-03 和 T-04 是 T-06 的另外两个前提。</p>';
  };
  $('#fClear').onclick = () => { mark(null, null); $$('.ms', track).forEach((x) => x.classList.remove('on')); pick('T-05'); mark(null, 'T-05'); };
  pick('T-05'); mark(null, 'T-05');
})();

/* ---------- checklist ---------- */
const CHECK = [
  { id: 'c1', t: '五个网格的静止形状', why: '建计算模型用。已导出并和 .mb 逐点核对。', where: 'local', done: true },
  { id: 'c3', t: '控制点的蒙皮权重', why: '300 个控制点对 10,240 个顶点的权重，以及公式要用的矩阵。目前只有 Maya 自检，T-09 和 Ziva 的精确对比才是独立检查。', where: 'local', done: true },
  { id: 'c2', t: 'Ziva 的完整设置，包括默认值和逐顶点权重表', why: '.mb 只存改过的值。没有它，材料和粘连刚度只能用我们定的临时值。权重表决定嘴唇哪些区域被拉着，单独导出，不只靠 zBuilder。', where: 'ziva' },
  { id: 'c4a', t: 'Ziva 参考结果：最终形状', why: '研究员评审时并排看。许可过期就再也做不出来。', where: 'ziva' },
  { id: 'c4b', t: 'Ziva 参考结果：只有物理', why: '控制点叠加之前的形状，和上一项来自同一次解算。这样能把物理和蒙皮分开看，蒙皮层还能精确核对。', where: 'ziva' },
  { id: 'c5', t: '这条运动的原始文件和每帧关节数据', why: '要用同一条运动驱动 FEBio。文件里只有静止位置。', where: 'ziva' },
  { id: 'c7', t: 'Ziva 里每个物体的网格，包括已删掉的 6 块肌肉', why: '嘴唇主要被口角、肌肉和皮肤拉着。6 块肌肉的网格只剩 Ziva 存的副本，离开 Ziva 就读不出面。不需要解算。', where: 'ziva' },
  { id: 'c6', t: '当面问完实验室的问题', why: '见下面的表，其中许可到期日和控制器怎么用物理最要紧。', where: 'ask' },
];
(function checklist() {
  const host = $('#checklist');
  const WHERE = { local: ['本机 Maya', 'local'], ziva: ['Ziva 机器', 'ziva'], ask: ['当面问', ''] };
  host.innerHTML = CHECK.map((c) => `<label class="check" for="${c.id}">
    <input type="checkbox" id="${c.id}" ${c.done ? 'checked disabled' : store.get(`asrp-${c.id}`) === '1' ? 'checked' : ''}>
    <b>${c.t}</b><span class="where ${WHERE[c.where][1]}">${WHERE[c.where][0]}</span><small>${c.why}</small></label>`).join('');
  host.addEventListener('change', (e) => store.set(`asrp-${e.target.id}`, e.target.checked ? '1' : '0'));
})();

/* ---------- quiz ---------- */
const QUIZ = [
  { q: '为什么不能把 .mb 直接导入 Blender？', o: ['文件太大', 'Maya 的私有格式，Blender 打不开，网格的面我们也读不出来', 'Blender 版本太新'], a: 1, y: '所以先写工具摸清内容，再用 Maya 把网格导出成开放格式。' },
  { q: '这个项目换掉的是哪一部分？', o: ['实验室的控制器', '物理引擎、控制点蒙皮和操作界面，控制器不动', '全部重写'], a: 1, y: '控制器是实验室的成果。我们换的是它底下的 Ziva、Maya 里的蒙皮和操作界面。' },
  { q: '在 Blender 里转动下颌，嘴唇没跟着动。这说明什么？', o: ['导入出错了', '网格坏了', '正常。预览没有物理计算，让嘴唇跟着动正是 FEBio 要算的'], a: 2, y: '资产能在 Blender 里显示，只是 M1 的一部分。' },
  { q: '控制点（landmark）在计算里处于什么位置？', o: ['物理算完以后叠加的蒙皮层', '物理计算的输入', '只用于显示'], a: 0, y: '这是从 Maya 场景的连接关系推断的，还要实验室一句话确认。' },
  { q: 'FEBio 的结果和 Ziva 平均差 3 mm，算不算失败？', o: ['算，必须对上 Ziva', '不一定。看合理性检查和研究员评审，差别只作参考', '不算，差多少都行'], a: 1, y: 'Ziva 的参数很可能是默认值，它本身不是正确答案。但合理性检查必须通过。' },
  { q: '为什么要尽快约 Ziva 机器，哪怕方案 A 还没定？', o: ['因为网格还没导出', '因为参考结果过了许可期就再也做不出来了', '因为 FEBio 要用它'], a: 1, y: '网格和权重已经在本机导出了。Ziva 机器只用来拿离不开 Ziva 的东西。' },
];
(function quiz() {
  const host = $('#quiz');
  host.innerHTML = QUIZ.map((q, i) => `<div class="q" data-i="${i}"><p>${i + 1}. ${q.q}</p><div class="opts">${q.o.map((o, k) => `<button type="button" data-k="${k}">${o}</button>`).join('')}</div><p class="why" hidden></p></div>`).join('');
  host.addEventListener('click', (e) => {
    const b = e.target.closest('[data-k]');
    if (!b) return;
    const box = b.closest('.q'), q = QUIZ[+box.dataset.i], k = +b.dataset.k;
    $$('button', box).forEach((x) => x.classList.remove('right', 'wrong'));
    b.classList.add(k === q.a ? 'right' : 'wrong');
    const why = $('.why', box);
    why.hidden = false;
    why.textContent = `${k === q.a ? '对。' : '不对。'}${q.y}`;
  });
})();

/* ---------- glossary ---------- */
const GLOSS = {
  Ziva: '装在 Maya 里的肌肉和软组织仿真插件，2024 年停售。本项目要替换的就是它。',
  Maya: 'Autodesk 公司的商业 3D 软件，实验室现在在用。',
  Blender: '免费开源的 3D 软件，本项目用它代替 Maya 做操作和显示。',
  FEBio: '专门为生物力学开发的开源有限元软件，经过同行评审。它接替 Ziva 做物理计算。',
  '控制器': '实验室的研究成果：给定目标表情，算出控制点每一帧该怎么动。第一阶段不移植。',
  landmark: '即控制点。实验室控制器用来驱动表情的点，嘴唇上有 300 个，在 Maya 里是关节。',
  '网格': '由很多小三角形或四边形拼成的表面，3D 模型就是它。',
  '顶点': '网格上的点。嘴唇有 10,240 个。顶点的编号顺序很重要，权重都是按编号对应的。',
  '面': '由几个顶点连成的小三角形或四边形。.mb 里的面我们读不出来，所以要用 Maya 导出。',
  '四面体': '由四个三角形围成的最小立体。有限元把物体切成很多个四面体来算。',
  '粘连': 'Ziva 里两样东西之间的连接，比如把嘴唇的一些顶点固定到下颌上。',
  '重力沉降': '运动开始前，让软组织在重力下先自然下垂、停稳。实验室用第 0 到 14 帧做这件事。',
  '阻尼': '让晃动慢慢停下来的因素。FEBio 默认没有，组织会一直小幅晃动。',
  '有限元': '把物体切成很多小块，分别算每一块的受力和变形，再拼起来的计算方法。FEBio 和 Ziva 都属于这一类。',
  '动力学分析': '按时间一帧一帧往前算，考虑惯性。另一种叫准静态，只算每一刻的平衡状态，不管惯性。',
  '节点': 'Maya 场景里的一个对象，比如一个网格、一个关节、一个 Ziva 设置。',
  '杨氏模量': '材料有多硬的指标。软组织大约几到几十千帕。',
  '刚体': '不变形的物体，只会移动和转动。骨头在这里按刚体算。',
  '.mb': 'Maya 的二进制场景文件，格式没有公开文档，Blender 打不开。',
  mayapy: 'Maya 自带的命令行 Python，不打开界面就能运行 Maya 脚本。',
  ShapeOrig: 'Maya 里网格变形之前的原始形状，也叫静止形状。Ziva 和蒙皮都以它为输入。',
  'OBJ': '最通用的开放 3D 网格文本格式，几乎所有 3D 软件都能读。',
  'Alembic': '存放"每一帧的网格形状"的开放格式，文件后缀 .abc。Ziva 参考结果用它导出。',
  '场景坐标': '网格放进场景以后的坐标。网格自己记录的叫物体坐标，两者差一个变换。',
  '口角': '嘴角处几块肌肉汇合的地方，英文 modiolus。',
  '蒙皮': '让关节按权重带动网格顶点。Maya 里叫 skinCluster。实验室用它让控制点带动嘴唇。',
  '合理性检查': '不依赖 Ziva 的自动检查：算没算完、该跟骨头走的点跟没跟、重力沉降的方向和大小对不对。',
  'ADR': '决策记录。记一个关键决定：定了什么、为什么、放弃了什么。在 docs/10。',
  '任务卡': '交给开发者的完整说明，写清目标、输入、输出、验收和改动范围。在 docs/09。',
  'scene.json': '我们自己定义的场景描述文件，完整描述一个要计算的模型。',
  '运行文件夹': '每次计算一个文件夹，装着这次的全部输入、输出和记录。',
  'Ziva 机器': '实验室里装着 Ziva 许可的电脑，大约 4 个人轮流用。',
  '非 Ziva 版': '实验室删掉全部 Ziva 节点后的场景副本，普通 Maya 就能打开。',
};
(function glossary() {
  const pop = $('#pop');
  const show = (b) => {
    const key = b.dataset.g, r = b.getBoundingClientRect();
    pop.innerHTML = `<b>${b.textContent}</b>${GLOSS[key] || '这个词还没有解释。'}`;
    pop.hidden = false;
    const w = pop.offsetWidth, h = pop.offsetHeight;
    pop.style.left = `${Math.max(8, Math.min(innerWidth - w - 8, r.left))}px`;
    pop.style.top = `${r.bottom + h + 8 > innerHeight ? r.top - h - 6 : r.bottom + 6}px`;
  };
  const hide = () => { pop.hidden = true; };
  document.addEventListener('mouseover', (e) => { const b = e.target.closest('.t'); if (b) show(b); });
  document.addEventListener('mouseout', (e) => { if (e.target.closest('.t')) hide(); });
  document.addEventListener('focusin', (e) => { const b = e.target.closest('.t'); if (b) show(b); });
  document.addEventListener('focusout', (e) => { if (e.target.closest('.t')) hide(); });
  document.addEventListener('click', (e) => { const b = e.target.closest('.t'); if (b) show(b); else hide(); });
  addEventListener('scroll', hide, { passive: true });

  const host = $('#gl'), q = $('#gq');
  const render = () => {
    const f = q.value.trim().toLowerCase();
    host.innerHTML = Object.entries(GLOSS).filter(([k, v]) => !f || k.toLowerCase().includes(f) || v.toLowerCase().includes(f))
      .map(([k, v]) => `<div><b>${k}</b>${v}</div>`).join('') || '<div>没有找到这个词。</div>';
  };
  q.addEventListener('input', render);
  render();
})();

/* ---------- page chrome ---------- */
const links = $$('#toc a');
const secs = links.map((a) => $(a.getAttribute('href')));
const onScroll = () => {
  const y = scrollY + innerHeight * .3;
  let cur = -1;
  secs.forEach((s, i) => { if (s.offsetTop <= y) cur = i; });
  links.forEach((a, i) => a.classList.toggle('on', i === cur));
  const max = document.documentElement.scrollHeight - innerHeight;
  $('#prog').style.width = `${Math.min(100, scrollY / max * 100)}%`;
};
addEventListener('scroll', onScroll, { passive: true });
onScroll();

const saved = store.get('asrp-theme');
if (saved) document.documentElement.dataset.theme = saved;
$('#themeBtn').addEventListener('click', () => {
  const dark = (document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')) === 'dark';
  const next = dark ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  store.set('asrp-theme', next);
  stages.forEach((s) => { s.dirty = true; });
});
})();
