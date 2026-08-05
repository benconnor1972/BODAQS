// @ts-check
import {defineConfig} from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
  site: 'https://bodaqs.net',
  redirects: {
    '/hardware-guide': '/logger-build-guide',
    '/hardware-guide/building': '/logger-build-guide/prototype-f/building-the-logger',
    '/hardware-guide/preparing-the-dev-board': '/logger-build-guide/prototype-f/preparing-the-dev-board',
    '/hardware-guide/installation': '/bike-installation-guide',
  },
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
        {icon: 'instagram', label: 'Instagram', href: 'https://www.instagram.com/bodaqs'},
        {icon: 'youtube', label: 'YouTube', href: 'https://www.youtube.com/@bodaqs'}
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
        { slug: 'buy-pcb-or-kit' },
        {
          label: 'Logger build guide',
          items: [
            {slug: 'logger-build-guide'},
            {
              label: 'BODAQS A8',
              items: [
                {slug: 'logger-build-guide/bodaqs-a8/sourcing-hardware'},
                {slug: 'logger-build-guide/bodaqs-a8/preparing-the-dev-board'},
                {slug: 'logger-build-guide/bodaqs-a8/building-the-logger'},
              ],
            },
            {
              label: 'Prototype F',
              items: [
                {slug: 'logger-build-guide/prototype-f/sourcing-hardware'},
                {slug: 'logger-build-guide/prototype-f/preparing-the-dev-board'},
                {slug: 'logger-build-guide/prototype-f/building-the-logger'},
              ],
            },
          ],
        }, {
          label: 'Sensor connection and wiring guide',
          items: [
            {slug: 'sensor-connection-and-wiring-guide'},
            {slug: 'sensor-connection-and-wiring-guide/connecting-and-configuring-sensors'},
            {slug: 'sensor-connection-and-wiring-guide/wiring-and-connector-tips'},
          ],
        }, {
          label: 'Bike installation guide',
          items: [
            {slug: 'bike-installation-guide'},
            {slug: 'bike-installation-guide/mounting-sensors'},
            {slug: 'bike-installation-guide/determining-leverage-curves'},
          ],
        }, {
          label: 'Software setup guide',
          autogenerate: {directory: 'software-guide'},
        }, {
          label: 'User guide',
          autogenerate: {directory: 'user-guide'},
        }, {
          label: 'Archive',
          autogenerate: {directory: 'archive'},
        },
      ],
    }),
  ],
});
