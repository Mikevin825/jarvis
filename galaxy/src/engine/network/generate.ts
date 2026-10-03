/**
 * Star network generation.
 *
 * Pure maths, no three.js. Given a seed, produce:
 *
 *   - 8 cluster centres on a shell 13–25 units from the middle
 *   - 6–8 nodes per cluster, spread within a few units of the centre
 *   - ~100 stray nodes in muted blue-grey
 *   - dust: a few hundred tiny faint points on a much larger shell
 *   - links, connecting nodes closer than ~10 units
 *   - per-cluster hues from a cool palette
 *
 * The layout is deterministic for a given seed, so it can be tested and so
 * restarts don't reshuffle the galaxy.
 */

export interface NetworkLayout {
  /** xyz per node (clusters + strays). */
  positions: Float32Array;
  /** Per-node size multiplier, 0.5..1.5. */
  sizes: Float32Array;
  /** Per-node phase offset for twinkling. */
  phases: Float32Array;
  /** Per-node colour index (0-7 for clusters, 8 for strays, 9 for dust). */
  colourIndices: Uint8Array;
  /** Pairs of node indices, one link per pair. */
  links: Uint32Array;
  /** xyz per cluster centre. */
  clusterCentres: Float32Array;
  /** Per-cluster hue as RGB 0..1. */
  clusterColours: Float32Array;
  /** xyz per dust particle. */
  dustPositions: Float32Array;
  nodeCount: number;
  linkCount: number;
  clusterCount: number;
  dustCount: number;
}

/** Mulberry32 — small, fast, deterministic. */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Box–Muller Gaussian, mean 0, stddev 1. */
function gaussian(rand: () => number): number {
  const u = Math.max(rand(), 1e-9);
  const v = rand();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

export interface GenerateOptions {
  seed?: number;
  clusterCount?: number;
  nodesPerCluster?: number;
  strayCount?: number;
  dustCount?: number;
  /** Max link distance in world units. */
  linkDistance?: number;
  /** Inner radius of the cluster shell. */
  shellInner?: number;
  /** Outer radius of the cluster shell. */
  shellOuter?: number;
}

/** The cool palette: teal, cyan, blue, purple, green-teal, indigo, blue-teal, violet. */
const CLUSTER_PALETTE: [number, number, number][] = [
  [0.16, 0.42, 0.42],   // teal
  [0.18, 0.78, 0.78],   // cyan
  [0.20, 0.45, 0.85],   // blue
  [0.55, 0.35, 0.85],   // purple
  [0.20, 0.65, 0.45],   // green-teal
  [0.35, 0.30, 0.75],   // indigo
  [0.25, 0.55, 0.75],   // blue-teal
  [0.60, 0.35, 0.80],   // violet
];

/**
 * Generate a star network layout.
 *
 * Clusters are placed on a shell 13–25 units out. Each cluster has its own
 * hue from the cool palette. Strays fill the rest in muted blue-grey. Dust
 * is a few hundred tiny points on a much larger shell.
 */
export function generateNetwork(options: GenerateOptions = {}): NetworkLayout {
  const {
    seed = 1337,
    clusterCount = 8,
    nodesPerCluster = 7,
    strayCount = 100,
    dustCount = 300,
    linkDistance = 10,
    shellInner = 13,
    shellOuter = 25,
  } = options;

  const rand = mulberry32(seed);

  // -- cluster centres ----------------------------------------------------
  // Placed on a shell 13–25 units out, with some vertical jitter.
  const clusterCentres = new Float32Array(clusterCount * 3);
  for (let c = 0; c < clusterCount; c++) {
    const angle = (c / clusterCount) * Math.PI * 2 + rand() * 0.5;
    const radius = shellInner + rand() * (shellOuter - shellInner);
    clusterCentres[c * 3 + 0] = Math.cos(angle) * radius;
    clusterCentres[c * 3 + 1] = gaussian(rand) * 2.5;
    clusterCentres[c * 3 + 2] = Math.sin(angle) * radius;
  }

  // -- cluster colours ----------------------------------------------------
  const clusterColours = new Float32Array(clusterCount * 3);
  for (let c = 0; c < clusterCount; c++) {
    const [r, g, b] = CLUSTER_PALETTE[c % CLUSTER_PALETTE.length];
    clusterColours[c * 3 + 0] = r;
    clusterColours[c * 3 + 1] = g;
    clusterColours[c * 3 + 2] = b;
  }

  // -- nodes (clusters + strays) ------------------------------------------
  const totalNodes = clusterCount * nodesPerCluster + strayCount;
  const positions = new Float32Array(totalNodes * 3);
  const sizes = new Float32Array(totalNodes);
  const phases = new Float32Array(totalNodes);
  const colourIndices = new Uint8Array(totalNodes);

  let nodeIndex = 0;

  // Cluster nodes
  for (let c = 0; c < clusterCount; c++) {
    const cx = clusterCentres[c * 3 + 0];
    const cy = clusterCentres[c * 3 + 1];
    const cz = clusterCentres[c * 3 + 2];

    for (let n = 0; n < nodesPerCluster; n++) {
      const spread = 1.5 + rand() * 2.0;
      positions[nodeIndex * 3 + 0] = cx + gaussian(rand) * spread;
      positions[nodeIndex * 3 + 1] = cy + gaussian(rand) * spread * 0.6;
      positions[nodeIndex * 3 + 2] = cz + gaussian(rand) * spread;
      sizes[nodeIndex] = 0.6 + rand() * 0.9;
      phases[nodeIndex] = rand();
      colourIndices[nodeIndex] = c;
      nodeIndex++;
    }
  }

  // Stray nodes — scattered in a larger volume, muted blue-grey
  for (let i = 0; i < strayCount; i++) {
    const angle = rand() * Math.PI * 2;
    const radius = 5 + rand() * 30;
    positions[nodeIndex * 3 + 0] = Math.cos(angle) * radius;
    positions[nodeIndex * 3 + 1] = gaussian(rand) * 4;
    positions[nodeIndex * 3 + 2] = Math.sin(angle) * radius;
    sizes[nodeIndex] = 0.4 + rand() * 0.6;
    phases[nodeIndex] = rand();
    colourIndices[nodeIndex] = 8; // stray colour index
    nodeIndex++;
  }

  // -- dust ---------------------------------------------------------------
  // A few hundred tiny faint points on a much larger shell.
  const dustPositions = new Float32Array(dustCount * 3);
  for (let i = 0; i < dustCount; i++) {
    const angle = rand() * Math.PI * 2;
    const radius = 30 + rand() * 40;
    dustPositions[i * 3 + 0] = Math.cos(angle) * radius;
    dustPositions[i * 3 + 1] = gaussian(rand) * 8;
    dustPositions[i * 3 + 2] = Math.sin(angle) * radius;
  }

  // -- links --------------------------------------------------------------
  // Connect any two nodes closer than linkDistance. O(n²) but done once.
  const linkList: number[] = [];
  const linkDistSq = linkDistance * linkDistance;

  for (let i = 0; i < totalNodes; i++) {
    const ix = i * 3;
    const ixx = positions[ix];
    const ixy = positions[ix + 1];
    const ixz = positions[ix + 2];

    for (let j = i + 1; j < totalNodes; j++) {
      const jx = j * 3;
      const dx = positions[jx] - ixx;
      const dy = positions[jx + 1] - ixy;
      const dz = positions[jx + 2] - ixz;
      const distSq = dx * dx + dy * dy + dz * dz;
      if (distSq < linkDistSq) {
        linkList.push(i, j);
      }
    }
  }

  return {
    positions,
    sizes,
    phases,
    colourIndices,
    links: new Uint32Array(linkList),
    clusterCentres,
    clusterColours,
    dustPositions,
    nodeCount: totalNodes,
    linkCount: linkList.length / 2,
    clusterCount,
    dustCount,
  };
}
