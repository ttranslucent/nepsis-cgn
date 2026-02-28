This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

Start the Nepsis backend API first (from repo root):

```bash
nepsiscgn-api --host 127.0.0.1 --port 8787
```

Then run the web development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

## Engine API Proxy

The web app now exposes backend proxy routes under `/api/engine/*`:

- `GET /api/engine/health`
- `GET /api/engine/routes`
- `POST /api/engine/sessions`
- `GET /api/engine/sessions`
- `GET /api/engine/sessions/:sessionId`
- `DELETE /api/engine/sessions/:sessionId`
- `POST /api/engine/sessions/:sessionId/step`
- `POST /api/engine/sessions/:sessionId/reframe`
- `GET /api/engine/sessions/:sessionId/packets`

By default these proxy to `http://127.0.0.1:8787`.

Override target with:

```bash
NEPSIS_API_BASE_URL=http://127.0.0.1:8787 npm run dev
```

Frontend helpers for these routes:

- Typed browser client: `src/lib/engineClient.ts`
- Hook/state wrapper: `src/lib/useEngineSession.ts`
- Live console page: `/engine` (`src/app/engine/page.tsx`)

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
