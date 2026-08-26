import "./globals.css";

export const metadata = {
  title: "DFI Deal Flow Tracker",
  description:
    "Development finance institution commitments — DFC, IFC, EBRD, IDB Invest, ADB — compiled from public disclosures by RCFH Advisory.",
};

// Runs before first paint. Without it the page renders in the operating
// system's theme and then flips to the stored choice, which looks like a bug.
// Wrapped in try/catch because a private window can throw on localStorage.
const NO_FLASH = `(function(){try{
  var t = localStorage.getItem("rcfh-theme");
  if (t === "dark" || t === "light") {
    document.documentElement.setAttribute("data-theme", t);
  }
}catch(e){}})();`;

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head>
        <script dangerouslySetInnerHTML={{ __html: NO_FLASH }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
