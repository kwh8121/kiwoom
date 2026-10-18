import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "키움 조건검색",
  description: "저장 조건식을 조합하는 키움 조건검색 도구",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="ko"><body className="min-h-screen antialiased">{children}</body></html>;
}
