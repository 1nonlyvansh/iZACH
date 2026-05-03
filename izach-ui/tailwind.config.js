/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        mono: ['"JetBrains Mono"', '"Fira Code"', 'monospace'],
        display: ['"Share Tech Mono"', 'monospace'],
      },
      colors: {
        cyan: {
          DEFAULT: '#00e5ff',
          dim: '#005060',
          dark: '#002030',
          glow: '#00e5ff33',
        },
        bg: {
          deep: '#050d1a',
          panel: '#071020',
          card: '#0a1628',
        },
        green: {
          neon: '#1db954',
          dim: '#0a4a22',
        },
        amber: { DEFAULT: '#ffb300' },
        red: { neon: '#ff3d3d' },
        border: {
          DEFAULT: '#0d2a3a',
          hi: '#1a4a5a',
        }
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'scan': 'scan 2s linear infinite',
        'glow': 'glow 2s ease-in-out infinite alternate',
        'fadeIn': 'fadeIn 0.3s ease-out',
        'slideUp': 'slideUp 0.3s ease-out',
        'spin-slow': 'spin 8s linear infinite',
        'orbit': 'orbit 12s linear infinite',
      },
      keyframes: {
        scan: {
          '0%': { transform: 'translateY(-100%)' },
          '100%': { transform: 'translateY(100vh)' }
        },
        glow: {
          '0%': { boxShadow: '0 0 5px #00e5ff44, 0 0 20px #00e5ff22' },
          '100%': { boxShadow: '0 0 15px #00e5ff88, 0 0 40px #00e5ff44' }
        },
        fadeIn: {
          '0%': { opacity: '0', transform: 'translateY(4px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' }
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' }
        },
        orbit: {
          '0%': { transform: 'rotate(0deg) translateX(60px) rotate(0deg)' },
          '100%': { transform: 'rotate(360deg) translateX(60px) rotate(-360deg)' }
        }
      }
    },
  },
  plugins: [],
}