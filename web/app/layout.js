import "./globals.css";

export const metadata = {
  title: "DFI Deal Flow Tracker",
  description:
    "Development finance institution commitments — DFC, IFC, EBRD, IDB Invest, ADB — compiled from public disclosures by RCFH Advisory.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
