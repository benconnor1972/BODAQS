// See https://svelte.dev/docs/kit/types#app.d.ts
// for information about these interfaces
declare global {
  namespace App {
    // interface Error {}
    // interface Locals {}
    // interface PageData {}
    // interface PageState {}
    // interface Platform {}
  }
}

// plotly.js-dist-min ships the same API as plotly.js but without type declarations;
// re-export from @types/plotly.js so strict TypeScript is satisfied.
declare module "plotly.js-dist-min" {
  export * from "plotly.js";
  import Plotly from "plotly.js";
  export default Plotly;
}

export {};
