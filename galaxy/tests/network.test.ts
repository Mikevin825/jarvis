import { describe, expect, it } from "vitest";
import { generateNetwork } from "../src/engine/network/generate";

describe("generateNetwork", () => {
  it("produces the requested number of stars", () => {
    const net = generateNetwork({ starCount: 100, clusterCount: 5 });
    expect(net.starCount).toBe(100);
    expect(net.positions.length).toBe(300);
    expect(net.sizes.length).toBe(100);
    expect(net.phases.length).toBe(100);
  });

  it("produces the requested number of clusters", () => {
    const net = generateNetwork({ starCount: 50, clusterCount: 7 });
    expect(net.clusterCount).toBe(7);
    expect(net.clusterCentres.length).toBe(21);
  });

  it("is deterministic for the same seed", () => {
    const a = generateNetwork({ seed: 42, starCount: 80 });
    const b = generateNetwork({ seed: 42, starCount: 80 });
    expect(Array.from(a.positions)).toEqual(Array.from(b.positions));
    expect(Array.from(a.links)).toEqual(Array.from(b.links));
  });

  it("produces different layouts for different seeds", () => {
    const a = generateNetwork({ seed: 1, starCount: 80 });
    const b = generateNetwork({ seed: 2, starCount: 80 });
    expect(Array.from(a.positions)).not.toEqual(Array.from(b.positions));
  });

  it("links only connect stars that exist", () => {
    const net = generateNetwork({ starCount: 60, clusterCount: 4 });
    for (let i = 0; i < net.links.length; i++) {
      expect(net.links[i]).toBeGreaterThanOrEqual(0);
      expect(net.links[i]).toBeLessThan(net.starCount);
    }
  });

  it("never links a star to itself", () => {
    const net = generateNetwork({ starCount: 60, clusterCount: 4 });
    for (let i = 0; i < net.links.length; i += 2) {
      expect(net.links[i]).not.toBe(net.links[i + 1]);
    }
  });

  it("produces an even number of link indices (pairs)", () => {
    const net = generateNetwork({ starCount: 60, clusterCount: 4 });
    expect(net.links.length % 2).toBe(0);
    expect(net.linkCount).toBe(net.links.length / 2);
  });

  it("respects the max links per star", () => {
    const net = generateNetwork({
      starCount: 100,
      clusterCount: 5,
      maxLinksPerStar: 2,
    });
    // Count how many links each star participates in.
    const counts = new Array(net.starCount).fill(0);
    for (let i = 0; i < net.links.length; i += 2) {
      counts[net.links[i]]++;
      counts[net.links[i + 1]]++;
    }
    const max = Math.max(...counts);
    expect(max).toBeLessThanOrEqual(2);
  });

  it("produces more links with a larger link distance", () => {
    const tight = generateNetwork({ starCount: 80, clusterCount: 5, linkDistance: 1.5 });
    const loose = generateNetwork({ starCount: 80, clusterCount: 5, linkDistance: 4.0 });
    expect(loose.linkCount).toBeGreaterThan(tight.linkCount);
  });

  it("keeps all positions finite", () => {
    const net = generateNetwork({ starCount: 100, clusterCount: 5 });
    for (let i = 0; i < net.positions.length; i++) {
      expect(Number.isFinite(net.positions[i])).toBe(true);
    }
  });

  it("keeps sizes in a reasonable range", () => {
    const net = generateNetwork({ starCount: 100, clusterCount: 5 });
    for (let i = 0; i < net.sizes.length; i++) {
      expect(net.sizes[i]).toBeGreaterThan(0);
      expect(net.sizes[i]).toBeLessThanOrEqual(2);
    }
  });

  it("keeps phases in 0..1", () => {
    const net = generateNetwork({ starCount: 100, clusterCount: 5 });
    for (let i = 0; i < net.phases.length; i++) {
      expect(net.phases[i]).toBeGreaterThanOrEqual(0);
      expect(net.phases[i]).toBeLessThanOrEqual(1);
    }
  });

  it("clusters are within the disc radius", () => {
    const radius = 9;
    const net = generateNetwork({ starCount: 100, clusterCount: 5, discRadius: radius });
    for (let c = 0; c < net.clusterCount; c++) {
      const x = net.clusterCentres[c * 3];
      const z = net.clusterCentres[c * 3 + 2];
      const dist = Math.sqrt(x * x + z * z);
      expect(dist).toBeLessThanOrEqual(radius * 1.01); // small tolerance for float
    }
  });

  it("stars cluster around their centres rather than filling the disc uniformly", () => {
    // With a small spread, most stars should be near a cluster centre.
    const net = generateNetwork({
      starCount: 200,
      clusterCount: 5,
      discRadius: 9,
    });
    let nearCentre = 0;
    for (let i = 0; i < net.starCount; i++) {
      const sx = net.positions[i * 3];
      const sz = net.positions[i * 3 + 2];
      // Check distance to nearest cluster centre.
      let minDist = Infinity;
      for (let c = 0; c < net.clusterCount; c++) {
        const cx = net.clusterCentres[c * 3];
        const cz = net.clusterCentres[c * 3 + 2];
        const d = Math.sqrt((sx - cx) ** 2 + (sz - cz) ** 2);
        if (d < minDist) minDist = d;
      }
      if (minDist < 3) nearCentre++;
    }
    // Most stars should be near a centre, not scattered uniformly.
    expect(nearCentre).toBeGreaterThan(net.starCount * 0.6);
  });
});
