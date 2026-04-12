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
          content: `
          (function(c,l,a,r,i,t,y){
              c[a]=c[a]||function(){(c[a].q=c[a].q||[]).push(arguments)};
              t=l.createElement(r);t.async=1;t.src="https://www.clarity.ms/tag/"+i;
              y=l.getElementsByTagName(r)[0];y.parentNode.insertBefore(t,y);
          })(window, document, "clarity", "script", "w9v4spkbez");
          `,
        },
      ],
      sidebar: [
        { slug: 'what-is-bodaqs' },
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
