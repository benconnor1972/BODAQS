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
        {icon: 'discord', label: 'Discord', href: 'https://discord.gg/BkWuT4S5kB'},
        {icon: 'instagram', label: 'Discord', href: 'https://www.instagram.com/bodaqs'}
      ],
      head: [
        {
          tag: 'script',
          attrs: {
            src: 'https://www.googletagmanager.com/gtag/js?id=G-',
            async: true,
          },
        },
        {
          tag: 'script',
          content: `
            window.dataLayer = window.dataLayer || [];
            function gtag(){dataLayer.push(arguments);}
            gtag('js', new Date());
            gtag('config', 'G-');
          `,
        },
      ],
      sidebar: [
        {
          label: 'Hardware guide',
          autogenerate: {directory: 'hardware-guide'},
        }, {
          label: 'Software guide',
          autogenerate: {directory: 'software-guide'},
        },
      ],
    }),
  ],
});
