import type { NextConfig } from "next";

const isProd = process.env.NODE_ENV === 'production';

const nextConfig: NextConfig = {
  typescript: {
    ignoreBuildErrors: true,
  },
  ...(isProd
    ? { output: 'export', trailingSlash: true }
    : {
        rewrites: async () => [
          {
            source: '/proxy-api/api/:path*',
            destination: `${process.env.BACKEND_URL || 'http://localhost:8011'}/api/:path*`,
          },
        ],
      }),
};

export default nextConfig;
