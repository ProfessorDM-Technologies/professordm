import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  // contracts ships TypeScript source (main: src/index.ts), so Next compiles it
  transpilePackages: ["@professordm/contracts"],
};

export default nextConfig;
