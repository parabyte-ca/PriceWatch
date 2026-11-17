// Writes docs/user-guide.md from the walkthrough steps in src/components/Walkthrough.tsx (npm run guide).
import { readFileSync, writeFileSync } from "node:fs";
const src = readFileSync(process.argv[2], "utf8");
const block = src.slice(src.indexOf("export const STEPS"), src.indexOf("];", src.indexOf("export const STEPS")) + 2).replace("export const STEPS: Step[] =", "const STEPS =");
const STEPS = new Function(block + "; return STEPS;")();
let md = "# PriceWatch user guide\n\nThe same walkthrough the app shows after you first sign in (open it again from **Me, How PriceWatch works**).\n";
STEPS.forEach((s, i) => { md += `\n## ${i + 1}. ${s.title}\n\n` + s.text.map((t) => t).join("\n\n") + "\n"; });
writeFileSync(process.argv[3], md);
