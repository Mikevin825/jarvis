/**
 * Star network generation.
 *
 * Pure maths, no three.js. Given a seed and a count, produce:
 *
 *   - cluster centres, scattered in a rough disc
 *   - stars, scattered around those centres with a Gaussian falloff
 *   - links, connecting each star to its nearest neighbours within a max distance
 *
 * The layout is deterministic for a given seed, so it can be tested and so
 * restarts don't reshuffle the galaxy.
 */

export interface NetworkLayout {
  /** xyz per star. */
  positions: Float32Array;
  /** Per-star size multiplier, 0.5..1.5. */
  sizes: Float32Array;
  /** Per-star phase offset for twinkling. */
  phases: Float32Array;
  /** Pairs of star indices, one link per pair. */
  links: Uint32Array;
  /** xyz per cluster centre (for the dust field). */
  clusterCentres: Float32Array;
  starCount: number;
  linkCount: number;
  clusterCount: number;
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
  starCount?: number;
  clusterCount?: number;
  /** Max link distance in world units. */
  linkDistance?: number;
  /** How many nearest neighbours to try linking to. */
  maxLinksPerStar?: number;
  /** Radius of the disc the clusters sit in. */
  discRadius?: number;
}

/**
 * Generate a star network layout.
 *
 * Clusters are placed on a rough disc with some vertical jitter. Stars scatter
 * around each centre with a Gaussian falloff, so the network reads as distinct
 * clumps rather than a uniform field.
 */
export function generateNetwork(options: GenerateOptions = {}): NetworkLayout {
  const {
    seed = 1337,
    starCount = 220,
    clusterCount = 7,
    linkDistance = 2.8,
    maxLinksPerStar = 3,
    discRadius = 6,
  } = options;

  const rand = mulberry32(seed);

  // -- cluster centres ----------------------------------------------------
  // Placed on a disc with vertical jitter, so the network has a plane but
  // isn't perfectly flat.
  const clusterCentres = new Float32Array(clusterCount * 3);
  for (let c = 0; c < clusterCount; c++) {
    const angle = rand() * Math.PI * 2;
    const radius = discRadius * (0.25 + rand() * 0.75);
    clusterCentres[c * 3 + 0] = Math.cos(angle) * radius;
    clusterCentres[c * 3 + 1] = gaussian(rand) * 0.8;
    clusterCentres[c * 3 + 2] = Math.sin(angle) * radius;
  }

  // -- stars --------------------------------------------------------------
  const positions = new Float32Array(starCount * 3);
  const sizes = new Float32Array(starCount);
  const phases = new Float32Array(starCount);

  for (let i = 0; i < starCount; i++) {
    // Pick a cluster, weighted toward the centre so the middle is denser.
    const c = Math.floor(Math.pow(rand(), 0.7) * clusterCount) % clusterCount;
    const cx = clusterCentres[c * 3 + 0];
    const cy = clusterCentres[c * 3 + 1];
    const cz = clusterCentres[c * 3 + 2];

    // Gaussian scatter around the centre. The spread varies per cluster so
    // some are tight and some are loose.
    const spread = 0.9 + rand() * 1.4;
    positions[i * 3 + 0] = cx + gaussian(rand) * spread;
    positions[i * 3 + 1] = cy + gaussian(rand) * spread * 0.6;
    positions[i * 3 + 2] = cz + gaussian(rand) * spread;

    sizes[i] = 0.5 + rand();
    phases[i] = rand();
  }

  // -- links --------------------------------------------------------------
  // For each star, find the nearest neighbours within linkDistance and connect.
  // O(n²) but done once at init, and n is small.
  //
  // Track how many links each star already has so the per-star limit holds in
  // both directions: a star must not be the target of more links than the limit
  // just because many other stars want to connect to it.
  const linkList: number[] = [];
  const linkDistSq = linkDistance * linkDistance;
  const linkCounts = new Uint8Array(starCount);

  for (let i = 0; i < starCount; i++) {
    if (linkCounts[i] >= maxLinksPerStar) continue;

    const ix = i * 3;
    const ixx = positions[ix];
    const ixy = positions[ix + 1];
    const ixz = positions[ix + 2];

    // Collect candidates with their distances.
    const candidates: { index: number; distSq: number }[] = [];
    for (let j = 0; j < starCount; j++) {
      if (j === i) continue;
      if (linkCounts[j] >= maxLinksPerStar) continue;
      const jx = j * 3;
      const dx = positions[jx] - ixx;
      const dy = positions[jx + 1] - ixy;
      const dz = positions[jx + 2] - ixz;
      const distSq = dx * dx + dy * dy + dz * dz;
      if (distSq < linkDistSq) {
        candidates.push({ index: j, distSq });
      }
    }

    // Sort by distance, take the nearest few.
    candidates.sort((a, b) => a.distSq - b.distSq);
    const limit = Math.min(maxLinksPerStar - linkCounts[i], candidates.length);
    for (let k = 0; k < limit; k++) {
      // Only add each link once: i < j.
      if (candidates[k].index > i) {
        linkList.push(i, candidates[k].index);
        linkCounts[i]++;
        linkCounts[candidates[k].index]++;
      }
    }
  }

  return {
    positions,
    sizes,
    phases,
    links: new Uint32Array(linkList),
    clusterCentres,
    starCount,
    linkCount: linkList.length / 2,
    clusterCount,
  };
}
