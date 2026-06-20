# Specification: BODocs Site

**Created**: 2025-06-20
**Status**: Draft
**Design Docs**: [docs/design/bodocs-site.md](../../design/bodocs-site.md)

## Scope

**What part of the design is being implemented:**
This spec documents the existing BODocs Site — the Astro/Starlight-powered
documentation website in `bodocs/`. It covers the Astro configuration, content
collection model, four custom components (Flag, Lede, Lightbox, MiniAside), the
`toCssUnit` utility, custom styles, content structure, and build/deploy setup.

**Out of scope for this spec:**
- The BODAQS firmware, analysis software, import manager, hardware, or mechanical designs (these are documented elsewhere)
- External deployment infrastructure (the site builds to `dist/`; deployment is external to this codebase)
- Content authoring guidelines (what should be written, only how the site renders it)

## Design Context

### Relevant Invariants
- **INV-1**: All documentation content is served from a single `docs` content collection using Starlight's `docsLoader()` and `docsSchema()`.
- **INV-2**: Content files must be `.md` or `.mdx` under `src/content/docs/`.
- **INV-3**: Sidebar is explicitly configured with one manual entry and four autogenerate-from-directory entries.
- **INV-4**: Site URL is `https://bodaqs.net`.
- **INV-5**: `toCssUnit` converts numbers to `${v}px`, passes strings through.
- **INV-6**: `Lightbox` resolves images via `import.meta.glob` matching lowercase extensions only; non-matching paths fall back to plain `<img>`. *(unverified intent — needs review)*
- **INV-7**: `Lightbox` generates random DOM IDs per instance.
- **INV-8**: `Flag` renders column < 600px, row ≥ 600px.
- **INV-9**: `Lede` renders 1.2em mobile, 1.5em ≥ 600px.
- **INV-10**: `MiniAside` hides Starlight's default aside title, renders custom bold title.
- **INV-11**: Custom CSS tokens: content width 60rem, accent #00FEDE (dark) / #008775 (light).
- **INV-12**: Path aliases `@src/*`, `@components/*`, `@assets/*`.
- **INV-13**: Microsoft Clarity analytics with project ID `w9v4spkbez`.
- **INV-14**: Build output is `dist/`, excluded from tsconfig.
- **INV-15**: `Lightbox` uses HTML Popover API with `command`/`commandfor` attributes.

### Relevant Contracts
- **Flag.astro**: Image-beside-content layout, delegates to Lightbox, responsive flex.
- **Lede.astro**: Pure presentational wrapper for intro text, no props.
- **Lightbox.astro**: Image zoom dialog with build-time glob resolution and `<img>` fallback.
- **MiniAside.astro**: Compact aside wrapper around Starlight's Aside, hides default title.
- **toCssUnit**: Pure function, number→px string, string→passthrough.

### Relevant Failure Modes
- Lightbox with uppercase extension images falls back to unoptimized `<img>`.
- Lightbox with non-existent src renders broken `<img>`.
- Invalid frontmatter causes build-time error.
- Instagram social link mislabeled as 'Discord' *(unverified intent — needs review)*.
- Empty `src` in Flag renders broken `<img>`.

---

## Component Specifications

### Astro Configuration — `bodocs/astro.config.mjs`

**Design doc reference:** [High-Level Architecture](../../design/bodocs-site.md#high-level-architecture)
**Depends on:** Starlight integration, content collection, assets

#### Interface Signatures

```javascript
// astro.config.mjs exports a default Astro config object
export default defineConfig({
  site: 'https://bodaqs.net',
  integrations: [starlight({...})]
})
```

#### Configuration Specification

| Field | Value | Behavior |
|-------|-------|----------|
| `site` | `'https://bodaqs.net'` | Canonical site URL for metadata and sitemap |
| `starlight.title` | `'Bodocs'` | Browser title and default header (overridden by logo) |
| `starlight.logo.replacesTitle` | `true` | Logo SVG replaces text title in header |
| `starlight.logo.light` | `'./src/assets/logo-light.svg'` | Light theme logo |
| `starlight.logo.dark` | `'./src/assets/logo-dark.svg'` | Dark theme logo |
| `starlight.customCss` | `['./src/styles/tokens.css']` | Brand color/width overrides |
| `starlight.social` | 3 entries (GitHub, Discord, Instagram) | Social link icons in header |
| `starlight.head` | Clarity analytics script | Inline script in `<head>` |
| `starlight.sidebar` | 5 entries (1 manual, 4 autogenerate) | Navigation sidebar structure |

#### Sidebar Configuration

| Entry | Type | Source |
|-------|------|--------|
| `what-is-bodaqs` | Manual (slug reference) | `src/content/docs/what-is-bodaqs.mdx` |
| Hardware guide | Autogenerate | `src/content/docs/hardware-guide/` |
| Software setup guide | Autogenerate | `src/content/docs/software-guide/` |
| User guide | Autogenerate | `src/content/docs/user-guide/` |
| Archive | Autogenerate | `src/content/docs/archive/` |

#### Social Links

| Icon | Label | href |
|------|-------|------|
| github | GitHub | https://github.com/benconnor1972/BODAQS |
| discord | Discord | https://discord.gg/BkWuT4S5kB |
| instagram | Discord *(unverified intent — needs review)* | https://www.instagram.com/bodaqs |

#### Acceptance Criteria

- **AC1:** Given the site is built, When a page is loaded, Then the `<head>` contains the Microsoft Clarity script with project ID `w9v4spkbez`.
- **AC2:** Given the sidebar is rendered, When a user views navigation, Then five top-level entries appear: "What is BODAQS?", "Hardware guide", "Software setup guide", "User guide", "Archive".
- **AC3:** Given the site is built, When the canonical URL is checked, Then it is `https://bodaqs.net`.
- **AC4:** Given a light theme is active, Then the logo from `logo-light.svg` is displayed and the accent color is `#008775`.
- **AC5:** Given a dark theme is active, Then the logo from `logo-dark.svg` is displayed and the accent color is `#00FEDE`.

---

### Content Collection — `bodocs/src/content.config.ts`

**Design doc reference:** [Data Model](../../design/bodocs-site.md#data-model)
**Depends on:** `@astrojs/starlight`

#### Interface Signatures

```typescript
import { defineCollection } from 'astro:content';
import { docsLoader } from '@astrojs/starlight/loaders';
import { docsSchema } from '@astrojs/starlight/schema';

export const collections = {
  docs: defineCollection({ loader: docsLoader(), schema: docsSchema() }),
};
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| File location | Must be under `src/content/docs/` | File not included in collection |
| File extension | Must be `.md` or `.mdx` | File not loaded by `docsLoader()` |
| Frontmatter `title` | Required by Starlight schema | Build-time schema validation error |
| Frontmatter `sidebar.order` | Optional number | Ignored if invalid |

#### Acceptance Criteria

- **AC1:** Given a `.mdx` file exists in `src/content/docs/hardware-guide/`, When the site is built, Then the file is included in the `docs` collection and appears in the sidebar under "Hardware guide".
- **AC2:** Given a content file is missing the `title` frontmatter field, When the site is built, Then the build fails with a schema validation error.
- **AC3:** Given a `.md` file exists in `src/content/docs/user-guide/`, When the site is built, Then it is loaded and rendered as a page.

---

### Lightbox.astro — `bodocs/src/components/Lightbox.astro`

**Design doc reference:** [Lightbox Component Contract](../../design/bodocs-site.md#lightboxastro)
**Depends on:** `astro:assets` (Image component), `toCssUnit` utility

#### Interface Signatures

```typescript
export interface Props {
  src: string;
  alt: string;
  class?: string;
  thumbnailWidth?: string | number;
  maxWidth?: string | number;
}
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `src` | String path. If matches `/src/assets/**/*.{png,jpg,jpeg,gif}`, uses Astro Image optimization | No error; falls back to plain `<img>` |
| `alt` | String, required for accessibility | No validation; empty string allowed |
| `thumbnailWidth` | String or number, default `200` | No validation |
| `maxWidth` | String or number, default `'90vw'` | No validation |

#### Error Specifications

| Error | When | Payload | Caller must |
|-------|------|---------|-------------|
| Fallback to `<img>` | `src` does not match glob or is not a resolvable path | Plain `<img>` with raw `src` | Ensure `src` is valid or accept unoptimized image |
| Broken image | `src` is empty or non-existent path | Browser broken image icon | Provide valid `src` |

#### Acceptance Criteria

- **AC1:** Given `src` is `/src/assets/pics/foo.png` and the file exists, When the component renders, Then Astro's `<Image>` component is used with optimized output.
- **AC2:** Given `src` is `https://example.com/image.png` (remote URL), When the component renders, Then a plain `<img>` is rendered (no optimization).
- **AC3:** Given `src` is `/src/assets/pics/logformat.JPG` (uppercase extension), When the component renders, Then a plain `<img>` is rendered because the glob only matches lowercase extensions. *(unverified intent — needs review)*
- **AC4:** Given the thumbnail is clicked, When the dialog opens, Then the full-size image is shown with a blurred dark backdrop and the image is constrained to `maxWidth` and `max-height: 90dvh`.
- **AC5:** Given the dialog is open, When the full-size image or backdrop is clicked, Then the dialog closes.
- **AC6:** Given two Lightbox instances on the same page, When both render, Then each has a unique DOM ID (random `lb-` prefix).

#### Integration Points

| Dependency | Call | Expected response | Error handling |
|------------|------|-------------------|----------------|
| `import.meta.glob` | Build-time path resolution | `{ default: ImageMetadata }` map | Missing key → `null` → fallback `<img>` |
| `astro:assets` `Image` | `<Image src={metadata} alt={alt} />` | Optimized `<img>` with srcset | Build error if metadata invalid |
| `toCssUnit` | `toCssUnit(thumbnailWidth)`, `toCssUnit(maxWidth)` | CSS length string | N/A (pure function) |

---

### Flag.astro — `bodocs/src/components/Flag.astro`

**Design doc reference:** [Flag Component Contract](../../design/bodocs-site.md#flagastro)
**Depends on:** `Lightbox.astro`, `toCssUnit` utility

#### Interface Signatures

```typescript
// Props inferred from destructuring (no exported interface)
const { src, alt, thumbnailWidth = 200, maxWidth } = Astro.props;
// Default slot for content
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `src` | String, passed to Lightbox | Delegates to Lightbox |
| `alt` | String, passed to Lightbox | Delegates to Lightbox |
| `thumbnailWidth` | String or number, default `200` | No validation |
| `maxWidth` | String or number, optional (passed to Lightbox, which defaults to `'90vw'`) | No validation |

#### Acceptance Criteria

- **AC1:** Given viewport width ≥ 600px, When Flag renders, Then the image and content are side-by-side (flex row).
- **AC2:** Given viewport width < 600px, When Flag renders, Then the image is above the content (flex column).
- **AC3:** Given `thumbnailWidth` is 400, When the thumbnail renders, Then its width is constrained to `min(400px, 100%)`.
- **AC4:** Given content in the default slot, When Flag renders, Then the content fills remaining flex space (`flex: 1`).

#### Integration Points

| Dependency | Call | Expected response | Error handling |
|------------|------|-------------------|----------------|
| `Lightbox` | `<Lightbox src={src} alt={alt} thumbnailWidth={thumbnailWidth} maxWidth={maxWidth} />` | Rendered lightbox thumbnail | Delegates to Lightbox |
| `toCssUnit` | `toCssUnit(thumbnailWidth)` | CSS length string | N/A |

---

### Lede.astro — `bodocs/src/components/Lede.astro`

**Design doc reference:** [Lede Component Contract](../../design/bodocs-site.md#ledeastro)
**Depends on:** None

#### Interface Signatures

```typescript
// No props. Default slot only.
```

#### Acceptance Criteria

- **AC1:** Given content in the default slot, When Lede renders on mobile, Then the font size is `1.2em`.
- **AC2:** Given content in the default slot, When Lede renders on viewport ≥ 600px, Then the font size is `1.5em`.
- **AC3:** Given the component renders, Then the font weight is `400`.

---

### MiniAside.astro — `bodocs/src/components/MiniAside.astro`

**Design doc reference:** [MiniAside Component Contract](../../design/bodocs-site.md#miniasideastro)
**Depends on:** `@astrojs/starlight/components` (Aside)

#### Interface Signatures

```typescript
const asideVariants = ['note', 'tip', 'caution', 'danger'] as const;

interface Props {
  title?: string;
  type?: (typeof asideVariants)[number];
}
```

#### Validation Rules

| Field | Rule | Error |
|-------|------|-------|
| `title` | Optional string | No validation |
| `type` | Optional, one of `'note'`, `'tip'`, `'caution'`, `'danger'` | Invalid value forwarded to Starlight Aside (behavior undefined) |

#### Acceptance Criteria

- **AC1:** Given `title` is provided, When MiniAside renders, Then the title appears as a bold paragraph before the slot content.
- **AC2:** Given `title` is not provided, When MiniAside renders, Then no title paragraph is shown.
- **AC3:** Given any MiniAside renders, Then Starlight's default aside title (`.starlight-aside__title`) is hidden via `display: none`.
- **AC4:** Given any MiniAside renders, Then the aside content has no block margin (`margin-block: 0`).

#### Integration Points

| Dependency | Call | Expected response | Error handling |
|------------|------|-------------------|----------------|
| `@astrojs/starlight/components` `Aside` | `<Aside type={type}>` | Rendered Starlight aside | Invalid type → Starlight determines behavior |

---

### toCssUnit — `bodocs/src/util/toCssUnit.ts`

**Design doc reference:** [toCssUnit Contract](../../design/bodocs-site.md#tocssunit-utility)
**Depends on:** None

#### Interface Signatures

```typescript
export function toCssUnit(v: string | number): string;
```

#### Validation Rules

| Input | Rule | Output |
|-------|------|--------|
| `number` | Any number | `${v}px` |
| `string` | Any string | Input unchanged |

#### Acceptance Criteria

- **AC1:** Given `toCssUnit(200)`, When called, Then it returns `"200px"`.
- **AC2:** Given `toCssUnit('90vw')`, When called, Then it returns `"90vw"`.
- **AC3:** Given `toCssUnit(0)`, When called, Then it returns `"0px"`.
- **AC4:** Given `toCssUnit('')`, When called, Then it returns `""`.

---

### Custom Styles — `bodocs/src/styles/tokens.css`

**Design doc reference:** [Branding](../../design/bodocs-site.md#branding)
**Depends on:** Starlight CSS custom properties

#### Specification

| Selector | Property | Dark Value | Light Value |
|----------|----------|------------|-------------|
| `:root` | `--sl-content-width` | `60rem` | `60rem` |
| `:root` | `--sl-color-text-accent` | `#00FEDE` | — |
| `:root[data-theme='light']` | `--sl-color-text-accent` | — | `#008775` |
| `:root[data-theme='light'] ::backdrop` | `--sl-color-text-accent` | — | `#008775` |

#### Acceptance Criteria

- **AC1:** Given the dark theme is active, When a page renders, Then the accent color is `#00FEDE` (bright teal).
- **AC2:** Given the light theme is active, When a page renders, Then the accent color is `#008775` (dark teal).
- **AC3:** Given any page renders, Then the content width is `60rem`.

---

### Content Structure — `bodocs/src/content/docs/`

**Design doc reference:** [Data Model](../../design/bodocs-site.md#data-model)
**Depends on:** Content collection, Starlight routing

#### Directory Structure

| Path | Type | Description |
|------|------|-------------|
| `index.mdx` | Splash page | Home page with hero, card grid linking to guides |
| `what-is-bodaqs.mdx` | Content page | Project overview, manually linked in sidebar |
| `hardware-guide/index.mdx` | Section index | Sourcing hardware (parts list, BOM) |
| `hardware-guide/preparing-the-dev-board.mdx` | Content page | Flashing firmware to ESP32 dev board |
| `hardware-guide/building.mdx` | Content page | Assembling the logger (Proto F build guide) |
| `hardware-guide/Installation.mdx` | WIP placeholder | Mounting logger and sensors (stub) |
| `software-guide/index.mdx` | Section index | Software overview and workflow options |
| `software-guide/setup-import-manager.mdx` | Content page | Installing BODAQS Import Manager |
| `software-guide/setup-syn-bike.mdx` | Content page | Setting up data.syn.bike |
| `software-guide/setup-python-and-jlab.mdx` | Content page | Python/JupyterLab environment setup |
| `user-guide/index.mdx` | Section index | Using the data logger (display, menu, logging) |
| `user-guide/accessing logs and configuration.mdx` | Content page | Web interface for logs and config |
| `user-guide/import-manager-user-guide.mdx` | Content page | Detailed Import Manager operation guide |
| `user-guide/import-manager-folder-structure-appendix.md` | Content page | Import Manager folder/file reference |
| `user-guide/analyzing your data with syn-bike.mdx` | Content page | Analysis with data.syn.bike |
| `user-guide/analyzing your data in Jupyter Lab.mdx` | Content page | Analysis with JupyterLab notebooks |
| `user-guide/analyzing your data on bodaqs-net.mdx` | WIP placeholder | Future BODAQS.net analysis (stub) |
| `archive/index.mdx` | WIP placeholder | Historical designs (stub) |
| `archive/building-e.mdx` | Content page | Deprecated Proto E build guide |

#### Acceptance Criteria

- **AC1:** Given the site is built, When a user navigates to `/`, Then the splash page renders with hero image and card grid.
- **AC2:** Given the sidebar autogenerates from `hardware-guide/`, When a user views the sidebar, Then all `.mdx`/`.md` files in that directory appear as navigation entries.
- **AC3:** Given a file has `sidebar.order` frontmatter, When the sidebar renders, Then entries are ordered by that value within their section.
- **AC4:** Given a file has `<WIP>` in its title, When the page renders, Then the title includes `<WIP>` (no special handling — rendered as literal text).

---

## Implementation Approach

### High-Level Architecture

The site is a static Astro build using the Starlight integration. Content is
authored as MDX/MD files in a single content collection. Custom components are
imported per-page. The build produces static HTML/CSS/JS in `dist/`.

```mermaid
graph LR
    subgraph "Build Pipeline"
        DEV[npm run dev<br/>astro dev] --> |local dev| LOCAL[localhost:4321]
        BUILD[npm run build<br/>astro build] --> |production| DIST[dist/]
        PREVIEW[npm run preview<br/>astro preview] --> |local preview| PREV[localhost:4321]
    end

    subgraph "Dependencies"
        ASTRO[Astro ^6.1.9]
        STARLIGHT[@astrojs/starlight ^0.38.4]
        SHARP[sharp ^0.34.5]
    end

    subgraph "Dev Dependencies"
        ESLINT[eslint ^10.2.1]
        STYLELINT[stylelint ^17.9.0]
        TS[typescript via astro/tsconfigs/strict]
    end

    ASTRO --> BUILD
    STARLIGHT --> BUILD
    SHARP --> |image optimization| BUILD
```

### Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Site framework | Astro + Starlight | Starlight provides docs-specific features (sidebar, search, theme) out of the box |
| Content format | MDX (primary) + MD | MDX allows importing custom components in content |
| Image handling | `import.meta.glob` with fallback | Allows content authors to pass string paths; Astro optimizes resolvable images |
| Lightbox mechanism | HTML Popover API (`<dialog>`) | Native browser dialog, no JS framework dependency |
| Analytics | Microsoft Clarity | Free, privacy-conscious session replay analytics |
| TypeScript config | `astro/tsconfigs/strict` | Strict type checking for component props |
| Path aliases | `@src/*`, `@components/*`, `@assets/*` | Shorter, cleaner imports in components and content |

### Research
No external research was performed. The site uses standard Astro/Starlight
patterns documented in the [Starlight docs](https://starlight.astro.build/).

### Alternatives Considered

| Alternative | Why not chosen |
|-------------|----------------|
| Docusaurus | Astro/Starlight was already chosen; no evidence of evaluation |
| GitBook | Astro/Starlight was already chosen; no evidence of evaluation |
| Plain Markdown (no framework) | Custom components (Lightbox, Flag) require a component framework |
| Client-side lightbox library | HTML Popover API is native and requires no dependency |

## Dependencies

### Design Dependencies
- None (this is a backfill of existing code)

### Spec Dependencies
- None (this is a backfill of existing code)

### Package Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `astro` | `^6.1.9` | Site framework |
| `@astrojs/starlight` | `^0.38.4` | Documentation theme/integration |
| `sharp` | `^0.34.5` | Image optimization (Astro dependency) |
| `eslint` | `^10.2.1` (dev) | Linting |
| `eslint-plugin-astro` | `^1.7.0` (dev) | Astro-specific lint rules |
| `@typescript-eslint/parser` | `^8.59.0` (dev) | TypeScript ESLint parser |
| `stylelint` | `^17.9.0` (dev) | CSS linting |
| `stylelint-config-standard` | `^40.0.0` (dev) | Standard CSS lint rules |
| `stylelint-config-html` | `^1.1.0` (dev) | HTML/CSS lint rules |
| `postcss-html` | `^1.8.1` (dev) | PostCSS for HTML |

## Open Questions

| # | Question | Blocks | Resolution |
|---|----------|--------|------------|
| 1 | Instagram social link labeled 'Discord' — copy-paste error or intentional? | Social links | UNRESOLVED *(unverified intent — needs review)* |
| 2 | `BODAQS_JupyterLab_Getting_Started_Windows.md` at bodocs root not in content collection — draft or orphan? | Nothing | UNRESOLVED *(unverified intent — needs review)* |
| 3 | Lightbox glob matches lowercase extensions only — intentional fallback or bug? | Lightbox image optimization | UNRESOLVED *(unverified intent — needs review)* |
| 4 | README.md is default Starlight starter template — should it be project-specific? | Nothing | UNRESOLVED *(unverified intent — needs review)* |

## Risks

| Risk | Mitigation |
|------|------------|
| Uppercase-extension images silently skip optimization | Audit `src/assets/pics/` for uppercase extensions; standardize or update glob pattern |
| No automated tests for components | Add component tests (Astro testing is available but not configured) |
| `Math.random()` IDs could theoretically collide | Probability is negligible for page-level IDs, but could use `crypto.randomUUID()` for guaranteed uniqueness |
| Microsoft Clarity loads without consent banner | Review privacy compliance requirements for target audience regions |

## Success Criteria

- [ ] The site builds successfully with `npm run build` producing static output in `dist/`
- [ ] All four custom components (Flag, Lede, Lightbox, MiniAside) render correctly in content pages
- [ ] The sidebar shows five top-level sections with autogenerate entries populated from their directories
- [ ] Light and dark themes apply correct logo and accent color variants
- [ ] Microsoft Clarity analytics script is present in the `<head>` of all pages
- [ ] The `toCssUnit` utility correctly converts numbers to px strings and passes strings through
- [ ] Content files with invalid frontmatter fail the build with a clear error
- [ ] The content structure matches the documented directory layout (4 guide sections, archive, top-level pages)
