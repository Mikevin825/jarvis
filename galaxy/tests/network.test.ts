import { describe, expect, it } from "vitest";
import { generateNetwork } from "../src/engine/network/generate";

describe("generateNetwork", () => {
  it("produces the requested number of clusters", () => {
    const net = generateNetwork({ clusterCount: 5 });
    expect(net.clusterCount).toBe(5);
    expect(net.clusterCentres.length).toBe(15);
  });

  it("produces nodes for each cluster", () => {
    const net = generateNetwork({ clusterCount: 5, nodesPerCluster: 7 });
    // 5 clusters * 7 nodes + 100 strays = 135
    expect(net.nodeCount).toBe(5 * 7 + 100);
    expect(net.positions.length).toBe(net.nodeCount * 3);
    expect(net.sizes.length).toBe(net.nodeCount);
    expect(net.phases.length).toBe(net.nodeCount);
  });

  it("produces the requested number of strays", () => {
    const net = generateNetwork({ strayCount: 50 });
    // 8 clusters * 7 nodes + 50 strays = 106
    expect(net.nodeCount).toBe(8 * 7 + 50);
  });

  it("produces dust particles", () => {
    const net = generateNetwork({ dustCount: 200 });
    expect(net.dustCount).toBe(200);
    expect(net.dustPositions.length).toBe(600);
  });

  it("is deterministic for the same seed", () => {
    const a = generateNetwork({ seed: 42 });
    const b = generateNetwork({ seed: 42 });
    expect(Array.from(a.positions)).toEqual(Array.from(b.positions));
    expect(Array.from(a.links)).toEqual(Array.from(b.links));
  });

  it("produces different layouts for different seeds", () => {
    const a = generateNetwork({ seed: 1 });
    const b = generateNetwork({ seed: 2 });
    expect(Array.from(a.positions)).not.toEqual(Array.from(b.positions));
  });

  it("links only connect nodes that exist", () => {
    const net = generateNetwork();
    for (let i = 0; i < net.links.length; i++) {
      expect(net.links[i]).toBeGreaterThanOrEqual(0);
      expect(net.links[i]).toBeLessThan(net.nodeCount);
    }
  });

  it("never links a star to itself", () => {
    const net = generateNetwork();
    for (let i = 0; i < net.links.length; i += 2) {
      expect(net.links[i]).not.toBe(net.links[i + 1]);
    }
  });

  it("produces an even number of link indices (pairs)", () => {
    const net = generateNetwork();
    expect(net.links.length % 2).toBe(0);
    expect(net.linkCount).toBe(net.links.length / 2);
  });

  it("keeps all positions finite", () => {
    const net = generateNetwork();
    for (let i = 0; i < net.positions.length; i++) {
      expect(Number.isFinite(net.positions[i])).toBe(true);
    }
  });

  it("keeps sizes in a reasonable range", () => {
    const net = generateNetwork();
    for (let i = 0; i < net.sizes.length; i++) {
      expect(net.sizes[i]).toBeGreaterThan(0);
      expect(net.sizes[i]).toBeLessThanOrEqual(2);
    }
  });

  it("keeps phases in 0..1", () => {
    const net = generateNetwork();
    for (let i = 0; i < net.phases.length; i++) {
      expect(net.phases[i]).toBeGreaterThanOrEqual(0);
      expect(net.phases[i]).toBeLessThanOrEqual(1);
    }
  });

  it("clusters are within the shell radius", () => {
    const net = generateNetwork({ shellInner: 13, shellOuter: 25 });
    for (let c = 0; c < net.clusterCount; c++) {
      const x = net.clusterCentres[c * 3];
      const z = net.clusterCentres[c * 3 + 2];
      const dist = Math.sqrt(x * x + z * z);
      expect(dist).toBeGreaterThanOrEqual(13 * 0.9); // small tolerance
      expect(dist).toBeLessThanOrEqual(25 * 1.1);
    }
  });

  it("produces per-cluster colours", () => {
    const net = generateNetwork({ clusterCount: 8 });
    expect(net.clusterColours.length).toBe(24); // 8 clusters * 3 (RGB)
    for (let c = 0; c < 8; c++) {
      const r = net.clusterColours[c * 3];
      const g = net.clusterColours[c * 3 + 1];
      const b = net.clusterColours[c * 3 + 2];
      expect(r).toBeGreaterThanOrEqual(0);
      expect(r).toBeLessThanOrEqual(1);
      expect(g).toBeGreaterThanOrEqual(0);
      expect(g).toBeLessThanOrEqual(1);
      expect(b).toBeGreaterThanOrEqual(0);
      expect(b).toBeLessThanOrEqual(1);
    }
  });

  it("assigns colour indices to nodes", () => {
    const net = generateNetwork({ clusterCount: 8, nodesPerCluster: 7 });
    // First 56 nodes (8*7) should have cluster colours 0-7
    for (let i = 0; i < 56; i++) {
      expect(net.colourIndices[i]).toBeLessThan(8);
    }
    // Remaining strays should have colour index 8
    for (let i = 56; i < net.nodeCount; i++) {
      expect(net.colourIndices[i]).toBe(8);
    }
  });

  it("produces more links with a larger link distance", () => {
    const tight = generateNetwork({ linkDistance: 5 });
    const loose = generateNetwork({ linkDistance: 15 });
    expect(loose.linkCount).toBeGreaterThan(tight.linkCount);
  });
});
