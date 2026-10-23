const mobile = { width: 375, height: 812 }
const tablet = { width: 768, height: 1024 }
const desktop = { width: 1440, height: 900 }

const config = {
  testDir: "../../tests/web/w3",
  projects: [
    { name: "chromium", use: { browserName: "chromium", viewport: desktop } },
    { name: "firefox", use: { browserName: "firefox", viewport: desktop } },
    { name: "mobile-375", use: { browserName: "chromium", viewport: mobile } },
    { name: "tablet-768", use: { browserName: "chromium", viewport: tablet } },
    { name: "desktop-1440", use: { browserName: "chromium", viewport: desktop } },
  ],
}

export default config
