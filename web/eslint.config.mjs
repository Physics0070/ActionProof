import next from "eslint-config-next";

const config = [{ ignores: [".next/**", "node_modules/**", "lib/api-types.ts", "reference/**", "**/*.d.mts"] }, ...next];

export default config;
