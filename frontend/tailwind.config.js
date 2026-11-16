/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "media",
  theme: {
    extend: {
      keyframes: {
        // the update progress bar's moving stripes, the success tick, and the top bar's light sweep (as in NetWatch)
        stripes: { "0%": { backgroundPosition: "0 0" }, "100%": { backgroundPosition: "28px 0" } },
        draw: { "0%": { strokeDashoffset: "48" }, "100%": { strokeDashoffset: "0" } },
        sweep: { "0%": { transform: "translateX(-100%)" }, "100%": { transform: "translateX(400%)" } },
      },
      animation: {
        stripes: "stripes 0.8s linear infinite",
        draw: "draw 0.6s ease-out 0.15s both",
        sweep: "sweep 1.6s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
