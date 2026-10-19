/**
 * JARVIS — Living Mind
 *
 * A 3D navigable map of the agent's mind.
 * Complete rewrite: individual meshes, cylinder edges, proper layout.
 *
 * Architecture:
 * - Individual Mesh objects for nodes (not InstancedMesh)
 * - Cylinder Mesh objects for edges (not Line)
 * - Force-directed layout with centering force
 * - Auto-rotating camera
 */

import * as THREE from '../lib/three.module.js';

const CONFIG = {
  background: 0x0a0a12,
  camera: {
    fov: 60,
    near: 0.1,
    far: 200,
  },
  fog: {
    color: 0x0a0a12,
    density: 0.008,
  },
  layout: {
    repulsion: 120,
    springStrength: 0.03,
    springLength: 5,
    gravity: 0.08,
    centering: 0.15,
    damping: 0.85,
    maxVelocity: 0.5,
    settleThreshold: 0.01,
    maxIterations: 500,
  },
  regionAnchors: {
    core: { x: 0, y: 0, z: 0 },
    memory: { x: -6, y: 3, z: 0 },
    knowledge: { x: 6, y: 3, z: 0 },
    rim: { x: 0, y: -10, z: 0 },
  },
};

// ── Starfield ──────────────────────────────────────────────────────────────

class Starfield {
  constructor(count = 1500) {
    this.count = count;
    this.geometry = new THREE.BufferGeometry();

    const positions = new Float32Array(count * 3);
    this.baseSizes = new Float32Array(count);
    this.phases = new Float32Array(count);

    for (let i = 0; i < count; i++) {
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      const r = 60 + Math.random() * 30;

      positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      positions[i * 3 + 2] = r * Math.cos(phi);

      this.baseSizes[i] = 0.3 + Math.random() * 1.0;
      this.phases[i] = Math.random() * Math.PI * 2;
    }

    this.geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    this.geometry.setAttribute('size', new THREE.BufferAttribute(this.baseSizes.slice(), 1));

    this.material = new THREE.PointsMaterial({
      color: 0xffffff,
      size: 0.8,
      sizeAttenuation: true,
      transparent: true,
      opacity: 0.6,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });

    this.points = new THREE.Points(this.geometry, this.material);
  }

  update(time) {
    const sizes = this.geometry.attributes.size;
    const array = sizes.array;
    for (let i = 0; i < this.count; i++) {
      array[i] = this.baseSizes[i] * (0.7 + 0.3 * Math.sin(time * 0.3 + this.phases[i]));
    }
    sizes.needsUpdate = true;
  }
}

// ── Membrane ───────────────────────────────────────────────────────────────

class Membrane {
  constructor(radius, opacity, color) {
    const geometry = new THREE.SphereGeometry(radius, 32, 32);
    this.material = new THREE.ShaderMaterial({
      vertexShader: `
        varying vec3 vNormal;
        varying vec3 vViewDir;
        void main() {
          vNormal = normalize(normalMatrix * normal);
          vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
          vViewDir = normalize(-mvPosition.xyz);
          gl_Position = projectionMatrix * mvPosition;
        }
      `,
      fragmentShader: `
        uniform vec3 uColor;
        uniform float uOpacity;
        varying vec3 vNormal;
        varying vec3 vViewDir;
        void main() {
          float fresnel = 1.0 - abs(dot(vNormal, vViewDir));
          fresnel = pow(fresnel, 4.0);
          gl_FragColor = vec4(uColor, fresnel * uOpacity);
        }
      `,
      uniforms: {
        uColor: { value: new THREE.Color(color) },
        uOpacity: { value: opacity },
      },
      transparent: true,
      side: THREE.BackSide,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    this.mesh = new THREE.Mesh(geometry, this.material);
  }
}

// ── Layout Engine ──────────────────────────────────────────────────────────

class LayoutEngine {
  constructor() {
    this.positions = [];
    this.nodes = [];
    this.settled = false;
  }

  initialize(nodes, edges) {
    this.nodes = nodes;
    this.settled = true;

    const count = nodes.length;
    this.positions = [];

    // Group nodes by region
    const coreNodes = [];
    const memoryNodes = [];
    const knowledgeNodes = [];
    const rimNodes = [];

    for (let i = 0; i < count; i++) {
      const node = nodes[i];
      if (node.region === 'core') coreNodes.push(i);
      else if (node.region === 'memory') memoryNodes.push(i);
      else if (node.region === 'knowledge') knowledgeNodes.push(i);
      else if (node.region === 'rim') rimNodes.push(i);
    }

    // Core at center
    for (const i of coreNodes) {
      this.positions[i] = { x: 0, y: 0, z: 0 };
    }

    // Memory: left side, spread vertically
    const memoryY = 4;
    const memorySpacing = 3;
    for (let k = 0; k < memoryNodes.length; k++) {
      const i = memoryNodes[k];
      this.positions[i] = {
        x: -8,
        y: memoryY + (k - (memoryNodes.length - 1) / 2) * memorySpacing,
        z: 0,
      };
    }

    // Knowledge: right side, spread vertically
    const knowledgeY = 4;
    const knowledgeSpacing = 3;
    for (let k = 0; k < knowledgeNodes.length; k++) {
      const i = knowledgeNodes[k];
      this.positions[i] = {
        x: 8,
        y: knowledgeY + (k - (knowledgeNodes.length - 1) / 2) * knowledgeSpacing,
        z: 0,
      };
    }

    // Rim: grid layout to guarantee spacing
    const rimCount = rimNodes.length;
    const cols = 6;
    const rows = Math.ceil(rimCount / cols);
    const spacing = 7;
    for (let k = 0; k < rimCount; k++) {
      const i = rimNodes[k];
      const row = Math.floor(k / cols);
      const col = k % cols;
      this.positions[i] = {
        x: (col - (cols - 1) / 2) * spacing,
        y: -10 - row * spacing,
        z: (Math.random() - 0.5) * 4,
      };
    }
  }

  step() {
    return true;
  }

  getNodeIndex(nodeId) {
    for (let i = 0; i < this.nodes.length; i++) {
      if (this.nodes[i].id === nodeId) return i;
    }
    return -1;
  }

  getPositions() {
    return this.positions;
  }

  isSettled() {
    return this.settled;
  }
}

// ── Main ───────────────────────────────────────────────────────────────────

class MindMap {
  constructor() {
    this.canvas = document.getElementById('scene');
    this.statsEl = document.getElementById('stats');
    this.loadingEl = document.getElementById('loading');

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(
      CONFIG.camera.fov,
      window.innerWidth / window.innerHeight,
      CONFIG.camera.near,
      CONFIG.camera.far,
    );
    this.camera.position.set(0, 5, 20);

    this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: true });
    this.renderer.setSize(window.innerWidth, window.innerHeight);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setClearColor(CONFIG.background, 1);

    this.scene.fog = new THREE.FogExp2(CONFIG.fog.color, CONFIG.fog.density);

    this.starfield = new Starfield(1500);
    this.scene.add(this.starfield.points);

    this.membrane = new Membrane(50, 0.02, 0x2dd4a8);
    this.scene.add(this.membrane.mesh);

    const ambientLight = new THREE.AmbientLight(0x404040, 0.5);
    this.scene.add(ambientLight);

    const pointLight = new THREE.PointLight(0xffffff, 1.0, 50);
    pointLight.position.set(0, 0, 0);
    this.scene.add(pointLight);

    this.nodeMeshes = [];
    this.edgeMeshes = [];
    this.nodeLabels = [];
    this.activeNodes = new Set();
    this.raycaster = new THREE.Raycaster();
    this.mouse = new THREE.Vector2();
    this.hoveredNode = null;
    this.selectedNode = null;
    this.flyTarget = null;

    this.layoutEngine = new LayoutEngine();
    this.initWebSocket();
    this.initNavigation();

    this.angle = 0;
    this.autoRotate = true;

    this.clock = new THREE.Clock();

    window.addEventListener('resize', () => this.onResize());
    this.canvas.addEventListener('mousemove', (e) => this.onMouseMove(e));
    this.canvas.addEventListener('click', (e) => this.onClick(e));
    this.canvas.addEventListener('wheel', (e) => this.onWheel(e), { passive: false });
    this.canvas.addEventListener('mousedown', (e) => this.onMouseDown(e));
    window.addEventListener('mouseup', (e) => this.onMouseUp(e));

    this.isDragging = false;
    this.dragStart = { x: 0, y: 0 };
    this.dragMoved = false;

    this.fetchSkeleton();
    this.animate();
  }

  initNavigation() {
    // Create tooltip
    this.tooltip = document.createElement('div');
    this.tooltip.style.cssText = 'position:fixed;display:none;padding:8px 12px;background:rgba(0,0,0,0.9);color:#fff;font-size:12px;font-family:monospace;border-radius:4px;pointer-events:none;z-index:1000;max-width:300px;border:1px solid rgba(255,255,255,0.2);';
    document.body.appendChild(this.tooltip);

    // Create inspect panel
    this.inspectPanel = document.createElement('div');
    this.inspectPanel.style.cssText = 'position:fixed;top:60px;right:20px;width:280px;max-height:400px;overflow-y:auto;background:rgba(0,0,0,0.9);color:#fff;font-size:12px;font-family:monospace;padding:16px;border-radius:8px;display:none;z-index:100;border:1px solid rgba(255,255,255,0.2);';
    document.body.appendChild(this.inspectPanel);

    // Create search
    const searchContainer = document.createElement('div');
    searchContainer.style.cssText = 'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);z-index:100;';
    searchContainer.innerHTML = '<input id="mind-search" type="text" placeholder="Search nodes..." style="padding:8px 16px;background:rgba(0,0,0,0.8);color:#fff;border:1px solid rgba(255,255,255,0.3);border-radius:4px;font-size:13px;font-family:monospace;width:300px;outline:none;" />';
    document.body.appendChild(searchContainer);

    // Create legend
    const legend = document.createElement('div');
    legend.style.cssText = 'position:fixed;bottom:20px;left:20px;z-index:100;background:rgba(0,0,0,0.8);padding:12px;border-radius:8px;border:1px solid rgba(255,255,255,0.2);font-size:11px;font-family:monospace;color:#fff;';
    legend.innerHTML = '<div style="font-weight:600;margin-bottom:8px;">Regions</div>' +
      '<div style="display:flex;align-items:center;margin:4px 0;"><span style="width:12px;height:12px;border-radius:50%;background:#2DD4A8;display:inline-block;margin-right:8px;"></span>Core</div>' +
      '<div style="display:flex;align-items:center;margin:4px 0;"><span style="width:12px;height:12px;border-radius:50%;background:#A78BFA;display:inline-block;margin-right:8px;"></span>Memory</div>' +
      '<div style="display:flex;align-items:center;margin:4px 0;"><span style="width:12px;height:12px;border-radius:50%;background:#F5A524;display:inline-block;margin-right:8px;"></span>Knowledge</div>' +
      '<div style="display:flex;align-items:center;margin:4px 0;"><span style="width:12px;height:12px;border-radius:50%;background:#8B93A1;display:inline-block;margin-right:8px;"></span>Rim (Tools)</div>';
    document.body.appendChild(legend);

    // Create controls
    const controls = document.createElement('div');
    controls.style.cssText = 'position:fixed;top:60px;left:20px;z-index:100;display:flex;flex-direction:column;gap:8px;';
    controls.innerHTML = `
      <button id="btn-zoom-in" style="width:36px;height:36px;background:rgba(0,0,0,0.8);color:#fff;border:1px solid rgba(255,255,255,0.3);border-radius:6px;cursor:pointer;font-size:18px;display:flex;align-items:center;justify-content:center;" title="Zoom In">+</button>
      <button id="btn-zoom-out" style="width:36px;height:36px;background:rgba(0,0,0,0.8);color:#fff;border:1px solid rgba(255,255,255,0.3);border-radius:6px;cursor:pointer;font-size:18px;display:flex;align-items:center;justify-content:center;" title="Zoom Out">−</button>
      <button id="btn-reset" style="width:36px;height:36px;background:rgba(0,0,0,0.8);color:#fff;border:1px solid rgba(255,255,255,0.3);border-radius:6px;cursor:pointer;font-size:14px;display:flex;align-items:center;justify-content:center;" title="Reset Camera">⟲</button>
      <button id="btn-rotate" style="width:36px;height:36px;background:rgba(0,0,0,0.8);color:#fff;border:1px solid rgba(255,255,255,0.3);border-radius:6px;cursor:pointer;font-size:14px;display:flex;align-items:center;justify-content:center;" title="Toggle Auto-Rotate">⏸</button>
    `;
    document.body.appendChild(controls);

    // Help button
    const helpBtn = document.createElement('button');
    helpBtn.id = 'btn-help';
    helpBtn.style.cssText = 'width:36px;height:36px;background:rgba(0,0,0,0.8);color:#fff;border:1px solid rgba(255,255,255,0.3);border-radius:6px;cursor:pointer;font-size:14px;display:flex;align-items:center;justify-content:center;';
    helpBtn.textContent = '?';
    helpBtn.title = 'Help';
    controls.appendChild(helpBtn);

    // Help panel
    const helpPanel = document.createElement('div');
    helpPanel.id = 'help-panel';
    helpPanel.style.cssText = 'position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:200;background:rgba(0,0,0,0.95);color:#fff;padding:24px;border-radius:12px;border:1px solid rgba(255,255,255,0.2);display:none;max-width:400px;';
    helpPanel.innerHTML = `
      <div style="font-weight:600;font-size:16px;margin-bottom:16px;">Navigation</div>
      <div style="display:grid;grid-template-columns:auto 1fr;gap:8px 16px;font-size:12px;">
        <span style="color:#888;">Scroll</span><span>Zoom in/out</span>
        <span style="color:#888;">Drag</span><span>Pan around</span>
        <span style="color:#888;">Click node</span><span>Inspect & fly to</span>
        <span style="color:#888;">Hover</span><span>Show label</span>
        <span style="color:#888;">Search</span><span>Find nodes by name</span>
        <span style="color:#888;">Enter</span><span>Fly to first result</span>
      </div>
      <div style="margin-top:16px;font-size:11px;color:#888;">Press ? or click outside to close</div>
    `;
    document.body.appendChild(helpPanel);

    helpBtn.addEventListener('click', () => {
      helpPanel.style.display = helpPanel.style.display === 'none' ? 'block' : 'none';
    });
    helpPanel.addEventListener('click', () => {
      helpPanel.style.display = 'none';
    });

    // Keyboard shortcut for help
    window.addEventListener('keydown', (e) => {
      if (e.key === '?' || (e.shiftKey && e.key === '/')) {
        helpPanel.style.display = helpPanel.style.display === 'none' ? 'block' : 'none';
      }
    });

    // Control handlers
    document.getElementById('btn-zoom-in').addEventListener('click', () => {
      this.camera.position.multiplyScalar(0.85);
    });
    document.getElementById('btn-zoom-out').addEventListener('click', () => {
      this.camera.position.multiplyScalar(1.18);
    });
    document.getElementById('btn-reset').addEventListener('click', () => {
      this.flyTarget = null;
      this.autoRotate = true;
      this.camera.position.set(0, 6, 30);
      document.getElementById('btn-rotate').textContent = '⏸';
    });
    document.getElementById('btn-rotate').addEventListener('click', () => {
      this.autoRotate = !this.autoRotate;
      document.getElementById('btn-rotate').textContent = this.autoRotate ? '⏸' : '▶';
    });

    // Search results dropdown
    this.searchResultsEl = document.createElement('div');
    this.searchResultsEl.style.cssText = 'position:fixed;bottom:70px;left:50%;transform:translateX(-50%);z-index:100;width:300px;max-height:200px;overflow-y:auto;background:rgba(0,0,0,0.9);border:1px solid rgba(255,255,255,0.3);border-radius:4px;display:none;';
    document.body.appendChild(this.searchResultsEl);

    // Search handler
    const searchInput = document.getElementById('mind-search');
    searchInput.addEventListener('input', (e) => this.onSearch(e.target.value));
    searchInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && this.searchResults.length > 0) {
        this.flyToNode(this.searchResults[0].id);
        this.searchResultsEl.style.display = 'none';
      }
    });
  }

  onMouseMove(event) {
    this.mouse.x = (event.clientX / window.innerWidth) * 2 - 1;
    this.mouse.y = -(event.clientY / window.innerHeight) * 2 + 1;

    if (this.isDragging) {
      const dx = event.clientX - this.dragStart.x;
      const dy = event.clientY - this.dragStart.y;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
        this.dragMoved = true;
      }
      const panSpeed = 0.02;
      this.camera.position.x -= dx * panSpeed;
      this.camera.position.y += dy * panSpeed;
      this.dragStart = { x: event.clientX, y: event.clientY };
      this.canvas.style.cursor = 'grabbing';
      return;
    }

    this.raycaster.setFromCamera(this.mouse, this.camera);
    const intersects = this.raycaster.intersectObjects(this.nodeMeshes);

    if (intersects.length > 0) {
      const mesh = intersects[0].object;
      const idx = this.nodeMeshes.indexOf(mesh);
      const node = this.skeleton?.nodes[idx];
      if (node) {
        this.hoveredNode = node;
        this.tooltip.style.display = 'block';
        this.tooltip.style.left = event.clientX + 15 + 'px';
        this.tooltip.style.top = event.clientY + 15 + 'px';
        this.tooltip.textContent = node.label;
        this.canvas.style.cursor = 'pointer';
      }
    } else {
      this.hoveredNode = null;
      this.tooltip.style.display = 'none';
      this.canvas.style.cursor = 'default';
    }
  }

  onWheel(event) {
    event.preventDefault();
    const zoomSpeed = 0.001;
    const factor = 1 + event.deltaY * zoomSpeed;
    this.camera.position.multiplyScalar(factor);
    const dist = this.camera.position.length();
    if (dist < 5) this.camera.position.setLength(5);
    if (dist > 80) this.camera.position.setLength(80);
  }

  onMouseDown(event) {
    if (event.button === 0) {
      this.isDragging = true;
      this.dragMoved = false;
      this.dragStart = { x: event.clientX, y: event.clientY };
    }
  }

  onMouseUp(event) {
    if (event.button === 0) {
      this.isDragging = false;
      this.canvas.style.cursor = 'default';
    }
  }

  onClick(event) {
    if (this.dragMoved) return;
    if (this.hoveredNode) {
      this.inspectNode(this.hoveredNode);
      this.flyToNode(this.hoveredNode.id);
    }
  }

  inspectNode(node) {
    this.selectedNode = node;
    this.inspectPanel.style.display = 'block';
    this.inspectPanel.innerHTML = `
      <div style="font-weight:600;font-size:14px;margin-bottom:8px;color:${node.color};">${node.label}</div>
      <div style="margin:4px 0;"><strong>Type:</strong> ${node.type}</div>
      <div style="margin:4px 0;"><strong>Region:</strong> ${node.region}</div>
      <div style="margin:4px 0;"><strong>Size:</strong> ${node.size.toFixed(2)}</div>
      <div style="margin:4px 0;"><strong>Freshness:</strong> ${node.freshness.toFixed(2)}</div>
      ${node.extra?.text ? `<div style="margin:8px 0;padding:8px;background:rgba(255,255,255,0.05);border-radius:4px;">${node.extra.text.substring(0, 200)}</div>` : ''}
      ${node.extra?.description ? `<div style="margin:8px 0;padding:8px;background:rgba(255,255,255,0.05);border-radius:4px;">${node.extra.description}</div>` : ''}
      <button id="close-inspect" style="margin-top:12px;padding:4px 12px;background:rgba(255,255,255,0.1);color:#fff;border:1px solid rgba(255,255,255,0.3);border-radius:4px;cursor:pointer;font-size:11px;">Close</button>
    `;
    document.getElementById('close-inspect').addEventListener('click', () => {
      this.inspectPanel.style.display = 'none';
      this.selectedNode = null;
    });
  }

  flyToNode(nodeId) {
    const idx = this.skeleton?.nodes.findIndex(n => n.id === nodeId);
    if (idx === undefined || idx < 0 || idx >= this.nodeMeshes.length) return;
    const mesh = this.nodeMeshes[idx];
    this.flyTarget = mesh.position.clone();
    this.autoRotate = false;
  }

  onSearch(query) {
    if (!query || !this.skeleton) {
      this.searchResults = [];
      this.searchResultsEl.style.display = 'none';
      return;
    }
    const q = query.toLowerCase();
    this.searchResults = this.skeleton.nodes.filter(n =>
      n.label.toLowerCase().includes(q) ||
      n.id.toLowerCase().includes(q)
    ).slice(0, 10);

    if (this.searchResults.length === 0) {
      this.searchResultsEl.style.display = 'none';
      return;
    }

    this.searchResultsEl.innerHTML = this.searchResults.map(n =>
      `<div class="search-result" data-id="${n.id}" style="padding:8px 12px;cursor:pointer;border-bottom:1px solid rgba(255,255,255,0.1);display:flex;align-items:center;" onmouseover="this.style.background='rgba(255,255,255,0.1)'" onmouseout="this.style.background='transparent'">
        <span style="width:10px;height:10px;border-radius:50%;background:${n.color};display:inline-block;margin-right:8px;flex-shrink:0;"></span>
        <span style="font-size:12px;">${n.label}</span>
      </div>`
    ).join('');
    this.searchResultsEl.style.display = 'block';

    this.searchResultsEl.querySelectorAll('.search-result').forEach(el => {
      el.addEventListener('click', () => {
        this.flyToNode(el.dataset.id);
        this.searchResultsEl.style.display = 'none';
      });
    });
  }

  initWebSocket() {
    try {
      this.ws = new WebSocket('ws://127.0.0.1:8793');
      this.ws.onopen = () => {
        console.log('WebSocket connected');
      };
      this.ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          this.handleLiveEvent(msg);
        } catch (e) {
          console.error('WebSocket message error:', e);
        }
      };
      this.ws.onclose = () => {
        console.log('WebSocket disconnected, retrying in 3s...');
        setTimeout(() => this.initWebSocket(), 3000);
      };
      this.ws.onerror = (err) => {
        console.error('WebSocket error:', err);
      };
    } catch (e) {
      console.error('WebSocket init failed:', e);
    }
  }

  handleLiveEvent(msg) {
    if (msg.type === 'node_activated') {
      const nodeId = msg.data?.node_id;
      if (nodeId) {
        this.highlightNode(nodeId);
      }
    } else if (msg.type === 'state_changed') {
      const state = msg.data?.state;
      if (state) {
        this.statsEl.textContent = `State: ${state}`;
      }
    }
  }

  highlightNode(nodeId) {
    // Find the node mesh by id and flash it
    const idx = this.skeleton?.nodes.findIndex(n => n.id === nodeId);
    if (idx === undefined || idx < 0 || idx >= this.nodeMeshes.length) return;

    const mesh = this.nodeMeshes[idx];
    const originalColor = mesh.material.color.getHex();
    mesh.material.color.setHex(0xffffff);
    setTimeout(() => {
      mesh.material.color.setHex(originalColor);
    }, 500);
  }

  async fetchSkeleton() {
    try {
      const response = await fetch('/api/mind-map');
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const skeleton = await response.json();
      this.skeleton = skeleton;
      this.createNodes(skeleton.nodes);
      this.layoutEngine.initialize(skeleton.nodes, skeleton.edges);
      const positions = this.layoutEngine.getPositions();
      for (let i = 0; i < this.nodeMeshes.length; i++) {
        this.nodeMeshes[i].position.set(positions[i].x, positions[i].y, positions[i].z);
      }
      this.createEdges(skeleton.edges, skeleton.nodes, positions);
      this.updateStats(skeleton);
    } catch (err) {
      console.error('Failed to fetch mind map:', err);
      this.statsEl.textContent = 'Error loading mind map';
    } finally {
      this.loadingEl.classList.add('hidden');
    }
  }

  updateStats(skeleton) {
    const nodeCount = skeleton.nodes.length;
    const edgeCount = skeleton.edges.length;
    this.statsEl.textContent = `${nodeCount} nodes · ${edgeCount} edges · memory: ${skeleton.stats.memory}`;
  }

  onResize() {
    this.camera.aspect = window.innerWidth / window.innerHeight;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(window.innerWidth, window.innerHeight);
  }

  createTextSprite(text, color) {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    const fontSize = 24;
    ctx.font = `${fontSize}px monospace`;
    const metrics = ctx.measureText(text);
    canvas.width = metrics.width + 20;
    canvas.height = fontSize + 16;
    const ctx2 = canvas.getContext('2d');
    ctx2.font = `${fontSize}px monospace`;
    ctx2.fillStyle = color;
    ctx2.textBaseline = 'middle';
    ctx2.fillText(text, 10, canvas.height / 2);
    const texture = new THREE.CanvasTexture(canvas);
    texture.minFilter = THREE.LinearFilter;
    const material = new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false });
    const sprite = new THREE.Sprite(material);
    sprite.scale.set(canvas.width / 40, canvas.height / 40, 1);
    return sprite;
  }

  createNodes(nodes) {
    for (const mesh of this.nodeMeshes) {
      this.scene.remove(mesh);
      mesh.geometry.dispose();
      mesh.material.dispose();
    }
    this.nodeMeshes = [];
    if (this.nodeLabels) {
      for (const label of this.nodeLabels) {
        this.scene.remove(label);
        label.material.map.dispose();
        label.material.dispose();
      }
    }
    this.nodeLabels = [];

    for (const node of nodes) {
      const geometry = new THREE.SphereGeometry(node.size, 16, 16);
      const material = new THREE.MeshBasicMaterial({ color: node.color });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.position.set(0, 0, 0);
      this.scene.add(mesh);
      this.nodeMeshes.push(mesh);

      const label = this.createTextSprite(node.label, node.color);
      label.position.set(0, node.size + 0.8, 0);
      mesh.add(label);
      this.nodeLabels.push(label);
    }
  }

  createEdges(edges, nodes, positions) {
    for (const mesh of this.edgeMeshes) {
      this.scene.remove(mesh);
      mesh.geometry.dispose();
      mesh.material.dispose();
    }
    this.edgeMeshes = [];

    const nodeMap = new Map();
    for (let i = 0; i < nodes.length; i++) {
      nodeMap.set(nodes[i].id, { node: nodes[i], pos: positions[i] });
    }

    for (const edge of edges) {
      const source = nodeMap.get(edge.source);
      const target = nodeMap.get(edge.target);
      if (!source || !target) continue;

      const p0 = new THREE.Vector3(source.pos.x, source.pos.y, source.pos.z);
      const p2 = new THREE.Vector3(target.pos.x, target.pos.y, target.pos.z);

      const direction = new THREE.Vector3().subVectors(p2, p0);
      const length = direction.length();
      if (length < 0.1) continue;

      const radius = 0.25 + edge.weight * 0.15;
      const geometry = new THREE.CylinderGeometry(radius, radius, length, 12);
      const color0 = new THREE.Color(source.node.color);
      const color1 = new THREE.Color(target.node.color);
      const colors = new Float32Array(geometry.attributes.position.count * 3);
      for (let i = 0; i < geometry.attributes.position.count; i++) {
        const t = (geometry.attributes.position.getY(i) + length / 2) / length;
        const c = new THREE.Color().lerpColors(color0, color1, t);
        colors[i * 3] = c.r;
        colors[i * 3 + 1] = c.g;
        colors[i * 3 + 2] = c.b;
      }
      geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
      const material = new THREE.MeshBasicMaterial({ vertexColors: true });
      const mesh = new THREE.Mesh(geometry, material);

      const mid = new THREE.Vector3().addVectors(p0, p2).multiplyScalar(0.5);
      mesh.position.copy(mid);
      mesh.lookAt(p2);
      mesh.rotateX(Math.PI / 2);

      this.scene.add(mesh);
      this.edgeMeshes.push(mesh);
    }
  }

  animate() {
    requestAnimationFrame(() => this.animate());

    const time = this.clock.getElapsedTime();

    this.starfield.update(time);

    if (this.skeleton && !this.layoutEngine.isSettled()) {
      this.layoutEngine.step();
      const positions = this.layoutEngine.getPositions();

      for (let i = 0; i < this.nodeMeshes.length; i++) {
        this.nodeMeshes[i].position.set(positions[i].x, positions[i].y, positions[i].z);
      }

      this.createEdges(this.skeleton.edges, this.skeleton.nodes, positions);
    }

    if (this.flyTarget) {
      // Smooth fly-to
      const targetPos = this.flyTarget.clone().add(new THREE.Vector3(0, 0, 8));
      this.camera.position.lerp(targetPos, 0.05);
      this.camera.lookAt(this.flyTarget);
      if (this.camera.position.distanceTo(targetPos) < 0.5) {
        this.flyTarget = null;
      }
    } else if (this.autoRotate) {
      this.angle += 0.002;
      const radius = 22;
      this.camera.position.x = Math.sin(this.angle) * radius;
      this.camera.position.z = Math.cos(this.angle) * radius;
      this.camera.lookAt(0, 0, 0);
    }

    this.renderer.render(this.scene, this.camera);
  }
}

new MindMap();
