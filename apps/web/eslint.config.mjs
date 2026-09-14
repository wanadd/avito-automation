import nextVitals from "eslint-config-next/core-web-vitals";

const config = [
  ...nextVitals,
  {
    rules: {
      "@next/next/no-html-link-for-pages": "off"
    }
  }
];

export default config;
