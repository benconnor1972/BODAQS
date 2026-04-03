// @ts-check
import {defineConfig} from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
  site: 'https://bodaqs.net',
  integrations: [
    starlight({
      title: 'Bodocs',
      logo: {
        replacesTitle: true,
        light: './src/assets/logo-light.svg',
        dark: './src/assets/logo-dark.svg',
      },
      customCss: [
        './src/styles/tokens.css',
      ],
      social: [
        {icon: 'github', label: 'GitHub', href: 'https://github.com/benconnor1972/BODAQS'},
        {icon: 'discord', label: 'Discord', href: 'https://discord.gg/BkWuT4S5kB'}
      ],
      sidebar: [
        {
          label: 'Hardware guide',
          autogenerate: {directory: 'hardware-guide'},
        },
      ],
    }),
  ],
});
