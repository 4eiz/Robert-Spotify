import type { Metadata } from 'next';
import { connection } from 'next/server';
import '@fontsource/poppins/400.css';
import '@fontsource/poppins/500.css';
import '@fontsource/poppins/600.css';
import '@fontsource/manrope/cyrillic-400.css';
import '@fontsource/manrope/cyrillic-500.css';
import '@fontsource/manrope/cyrillic-600.css';
import './globals.css';
import './refinements.css';
export const metadata: Metadata = {title: 'Robert Spotify — семьи и подписки', description: 'Личный кабинет управления подписками', robots: {index: false, follow: false}};
export default async function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
  await connection();
  return <html lang="ru" suppressHydrationWarning><body>{children}</body></html>;
}
