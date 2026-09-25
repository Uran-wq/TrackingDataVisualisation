/* Interactive 3D playback of VR tracking data (three.js, no build step).
 *
 * Verified assumptions (see README):
 *  - Head pose = position + quaternion (x,y,z,w), head->world; face = local -Z.
 *  - 26 hand joints in OpenXR-style order; bone edges validated by a
 *    rigid-bone test against the source data.
 *  - Inactive hands arrive as NaN rows and are hidden, never interpolated.
 */
(function () {
  'use strict';

  function fail(msg) {
    var el = document.getElementById('error');
    el.textContent = msg;
    el.style.display = 'block';
  }
  if (typeof THREE === 'undefined') { fail('three.js failed to load (lib/three.min.js).'); return; }
  if (!window.VIEWER_DATA) { fail('data.js not found — generate it first: python -m src.main'); return; }

  var D = window.VIEWER_DATA;

  function decodeF32(b64) {
    var bin = atob(b64);
    var u8 = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) { u8[i] = bin.charCodeAt(i); }
    return new Float32Array(u8.buffer);
  }

  var COUNT = D.count;
  var DURATION = D.duration;
  var times = decodeF32(D.times);
  var headData = decodeF32(D.head);   // COUNT * 7: x y z qx qy qz qw
  var leftData = decodeF32(D.left);   // COUNT * 78: 26 * (x y z)
  var rightData = decodeF32(D.right); // COUNT * 78
  var JS = D.jointCount;              // 26
  var STRIDE = JS * 3;

  // OpenXR-style bone edges (verified rigid against the source file).
  var EDGES = [
    [1, 0], [1, 2],
    [2, 3], [3, 4], [4, 5],
    [6, 7], [7, 8], [8, 9], [9, 10],
    [11, 12], [12, 13], [13, 14], [14, 15],
    [16, 17], [17, 18], [18, 19], [19, 20],
    [21, 22], [22, 23], [23, 24], [24, 25],
    [0, 6], [0, 11], [0, 16], [0, 21]
  ];
  var TIPS = [5, 10, 15, 20, 25];

  var COLORS = { head: 0x1f77b4, left: 0xd62728, right: 0x2ca02c };

  // --- scene -----------------------------------------------------------------
  var canvas = document.getElementById('scene');
  var renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  var scene = new THREE.Scene();
  scene.background = new THREE.Color(0xfafafa);
  var camera = new THREE.PerspectiveCamera(50, 1, 0.01, 100);
  var controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;

  scene.add(new THREE.HemisphereLight(0xffffff, 0x909090, 0.95));
  var sun = new THREE.DirectionalLight(0xffffff, 0.45);
  sun.position.set(1, 2, 1.2);
  scene.add(sun);

  // Bounding box over everything that has valid samples.
  function accumulate(arr, stride, box) {
    for (var i = 0; i < arr.length; i += stride) {
      if (isFinite(arr[i]) && isFinite(arr[i + 1]) && isFinite(arr[i + 2])) {
        for (var a = 0; a < 3; a++) {
          if (arr[i + a] < box.min[a]) { box.min[a] = arr[i + a]; }
          if (arr[i + a] > box.max[a]) { box.max[a] = arr[i + a]; }
        }
      }
    }
  }
  var box = { min: [Infinity, Infinity, Infinity], max: [-Infinity, -Infinity, -Infinity] };
  accumulate(headData, 7, box);
  accumulate(leftData, 3, box);
  accumulate(rightData, 3, box);
  var spanX = box.max[0] - box.min[0], spanY = box.max[1] - box.min[1],
      spanZ = box.max[2] - box.min[2];
  var maxSpan = Math.max(spanX, spanY, spanZ, 0.5);
  var center = new THREE.Vector3(
    (box.min[0] + box.max[0]) / 2, (box.min[1] + box.max[1]) / 2,
    (box.min[2] + box.max[2]) / 2);

  // Reference plane + world axes (X red, Y green, Z blue).
  var gridSize = Math.max(Math.max(spanX, spanZ) * 1.5, 0.8);
  var grid = new THREE.GridHelper(gridSize, 16, 0xc8c8c8, 0xe4e4e4);
  grid.position.y = box.min[1] - 0.02;
  scene.add(grid);
  var axes = new THREE.AxesHelper(gridSize * 0.25);
  axes.position.set(0, box.min[1] - 0.019, 0);
  scene.add(axes);

  // --- head model (stylized VR headset + orientation triad) ------------------
  function makeHead() {
    var g = new THREE.Group();
    var mat = new THREE.MeshStandardMaterial({
      color: COLORS.head, roughness: 0.55, metalness: 0.05
    });
    var skull = new THREE.Mesh(new THREE.SphereGeometry(1, 24, 18), mat);
    skull.scale.set(0.085, 0.105, 0.095); // source units; head-sized if meters
    g.add(skull);
    var visor = new THREE.Mesh(
      new THREE.BoxGeometry(0.13, 0.055, 0.03),
      new THREE.MeshStandardMaterial({ color: 0x123a5e, roughness: 0.25 })
    );
    visor.position.z = -0.085; // face direction = local -Z
    g.add(visor);
    var triad = new THREE.AxesHelper(0.17);
    g.add(triad);
    return g;
  }
  var head = makeHead();
  scene.add(head);

  // --- hand models (joint spheres + bone cylinders) --------------------------
  var jointGeo = new THREE.SphereGeometry(1, 10, 8);
  var tipGeo = new THREE.SphereGeometry(1, 12, 10);
  var boneGeo = new THREE.CylinderGeometry(1, 1, 1, 8, 1, true);
  var upAxis = new THREE.Vector3(0, 1, 0);
  var tmpDir = new THREE.Vector3();
  var tmpMid = new THREE.Vector3();

  function makeHand(colorHex) {
    var g = new THREE.Group();
    var mat = new THREE.MeshStandardMaterial({
      color: colorHex, roughness: 0.45, metalness: 0.05
    });
    var joints = [], bones = [], jv = [];
    for (var i = 0; i < JS; i++) {
      var isTip = TIPS.indexOf(i) !== -1;
      var m = new THREE.Mesh(isTip ? tipGeo : jointGeo, mat);
      m.scale.setScalar(isTip ? 0.0065 : 0.0048);
      g.add(m); joints.push(m);
      jv.push(new THREE.Vector3());
    }
    for (var e = 0; e < EDGES.length; e++) {
      var b = new THREE.Mesh(boneGeo, mat);
      b.scale.set(0.0026, 1, 0.0026);
      g.add(b); bones.push(b);
    }
    scene.add(g);
    return { group: g, joints: joints, bones: bones, jv: jv };
  }
  var leftHand = makeHand(COLORS.left);
  var rightHand = makeHand(COLORS.right);

  function setBone(bone, a, b) {
    tmpDir.subVectors(b, a);
    var len = tmpDir.length();
    if (len < 1e-9) { bone.visible = false; return; }
    bone.visible = true;
    tmpMid.addVectors(a, b).multiplyScalar(0.5);
    bone.position.copy(tmpMid);
    bone.quaternion.setFromUnitVectors(upAxis, tmpDir.multiplyScalar(1 / len));
    bone.scale.set(0.0026, len, 0.0026);
  }

  function updateHand(model, arr, offset) {
    if (!isFinite(arr[offset])) { model.group.visible = false; return; }
    model.group.visible = true;
    var i;
    for (i = 0; i < JS; i++) {
      model.jv[i].set(arr[offset + i * 3], arr[offset + i * 3 + 1], arr[offset + i * 3 + 2]);
      model.joints[i].position.copy(model.jv[i]);
    }
    for (i = 0; i < EDGES.length; i++) {
      setBone(model.bones[i], model.jv[EDGES[i][0]], model.jv[EDGES[i][1]]);
    }
  }

  var lastFrame = -1;
  // Read-only state snapshot for debugging / automated checks.
  window.VIEWER_STATE = { frame: -1, leftVisible: false, rightVisible: false, t: 0, playing: true };
  function applyFrame(idx) {
    if (idx === lastFrame) { return; }
    lastFrame = idx;
    var h = idx * 7;
    head.position.set(headData[h], headData[h + 1], headData[h + 2]);
    head.quaternion.set(headData[h + 3], headData[h + 4], headData[h + 5], headData[h + 6]);
    updateHand(leftHand, leftData, idx * STRIDE);
    updateHand(rightHand, rightData, idx * STRIDE);
    var st = window.VIEWER_STATE;
    st.frame = idx;
    st.leftVisible = leftHand.group.visible;
    st.rightVisible = rightHand.group.visible;
  }

  // --- playback --------------------------------------------------------------
  var tData = 0, playing = true, speed = 1, scrubbing = false;
  var playBtn = document.getElementById('play');
  var scrub = document.getElementById('scrub');
  var timeEl = document.getElementById('time');
  var speedEl = document.getElementById('speed');

  function findIndex(t) {
    if (t <= times[0]) { return 0; }
    if (t >= times[COUNT - 1]) { return COUNT - 1; }
    var lo = 0, hi = COUNT - 1;
    while (lo < hi) {
      var mid = (lo + hi + 1) >> 1;
      if (times[mid] <= t) { lo = mid; } else { hi = mid - 1; }
    }
    return lo;
  }

  function syncPlayBtn() { playBtn.innerHTML = playing ? '&#10074;&#10074;' : '&#9654;'; }
  playBtn.addEventListener('click', function () {
    if (!playing && tData >= DURATION) { tData = 0; }
    playing = !playing;
    syncPlayBtn();
  });
  speedEl.addEventListener('change', function () { speed = parseFloat(speedEl.value); });
  scrub.addEventListener('pointerdown', function () { scrubbing = true; });
  window.addEventListener('pointerup', function () { scrubbing = false; });
  scrub.addEventListener('input', function () {
    tData = (parseFloat(scrub.value) / 1000) * DURATION;
    applyFrame(findIndex(tData));
  });

  // --- camera framing + reset ------------------------------------------------
  var camStart = new THREE.Vector3(
    center.x + maxSpan * 0.85, center.y + maxSpan * 0.55, center.z + maxSpan * 1.05);
  var targetStart = center.clone();
  camera.position.copy(camStart);
  controls.target.copy(targetStart);
  controls.update();
  document.getElementById('reset').addEventListener('click', function () {
    camera.position.copy(camStart);
    controls.target.copy(targetStart);
    controls.update();
  });

  document.getElementById('units-note').textContent = D.unitsNote;

  // Automation API: deterministic seek + camera orbit (used for demo captures).
  window.VIEWER_API = {
    seek: function (sec) {
      tData = Math.max(0, Math.min(DURATION, sec));
      playing = false;
      syncPlayBtn();
      applyFrame(findIndex(tData));
      scrub.value = String(Math.round((tData / DURATION) * 1000));
      window.VIEWER_STATE.t = tData;
      window.VIEWER_STATE.playing = false;
    },
    orbit: function (yaw, pitch) {
      var r = camStart.distanceTo(targetStart);
      camera.position.set(
        targetStart.x + r * Math.cos(pitch) * Math.sin(yaw),
        targetStart.y + r * Math.sin(pitch),
        targetStart.z + r * Math.cos(pitch) * Math.cos(yaw)
      );
      controls.update();
    },
    rest: function () {  // initial framing constants for scripted captures
      var off = camStart.clone().sub(targetStart);
      var r = off.length();
      return {
        radius: r,
        yaw0: Math.atan2(off.x, off.z),
        pitch0: Math.asin(off.y / r),
        target: targetStart.toArray()
      };
    }
  };

  // --- render loop -----------------------------------------------------------
  function resize() {
    var w = window.innerWidth, h = window.innerHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  window.addEventListener('resize', resize);
  resize();

  var lastNow = performance.now();
  function tick(now) {
    var dt = Math.min((now - lastNow) / 1000, 0.1);
    lastNow = now;
    if (playing) {
      tData += dt * speed;
      if (tData >= DURATION) { tData = DURATION; playing = false; syncPlayBtn(); }
    }
    applyFrame(findIndex(tData));
    if (!scrubbing) { scrub.value = String(Math.round((tData / DURATION) * 1000)); }
    window.VIEWER_STATE.t = tData;
    window.VIEWER_STATE.playing = playing;
    timeEl.textContent = tData.toFixed(1) + ' / ' + DURATION.toFixed(1) + ' s';
    controls.update();
    renderer.render(scene, camera);
    requestAnimationFrame(tick);
  }
  applyFrame(0);
  requestAnimationFrame(tick);
})();
