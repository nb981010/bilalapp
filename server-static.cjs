const http = require('http');
const fs = require('fs');
const path = require('path');
const url = require('url');

const PORT = process.env.PORT || 3000;
const DIST = path.join(__dirname, 'dist');

const mime = {
  '.html': 'text/html',
  '.js': 'application/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.map': 'application/octet-stream',
};

function sendFile(res, filePath) {
  const ext = path.extname(filePath);
  const contentType = mime[ext] || 'application/octet-stream';
  fs.readFile(filePath, (err, content) => {
    if (err) {
      res.writeHead(404, { 'Content-Type': 'text/plain' });
      res.end('404 Not Found');
      return;
    }
    res.writeHead(200, { 'Content-Type': contentType, 'Cache-Control': 'public, max-age=31536000' });
    res.end(content);
  });
}

const httpProxy = require('http');

function proxyToBackend(req, res) {
  const backendOpts = {
    hostname: '127.0.0.1',
    port: 5000,
    path: req.url,
    method: req.method,
    headers: req.headers,
  };
  const pres = httpProxy.request(backendOpts, (presp) => {
    // copy status and headers
    const headers = presp.headers;
    res.writeHead(presp.statusCode || 200, headers);
    presp.pipe(res);
  });
  pres.on('error', (err) => {
    res.writeHead(502, { 'Content-Type': 'text/plain' });
    res.end('Bad Gateway');
  });
  // pipe request body
  req.pipe(pres);
}

const server = http.createServer((req, res) => {
  try {
    const parsed = url.parse(req.url || '/');
    let pathname = decodeURIComponent(parsed.pathname || '/');
    // Proxy API and audio requests to backend
    if (pathname.startsWith('/api') || pathname.startsWith('/audio')) {
      return proxyToBackend(req, res);
    }
    if (pathname === '/') pathname = '/index.html';
    const safePath = path.normalize(path.join(DIST, pathname));
    if (!safePath.startsWith(DIST)) {
      res.writeHead(403);
      res.end('Forbidden');
      return;
    }
    fs.stat(safePath, (err, stats) => {
      if (!err && stats.isFile()) {
        return sendFile(res, safePath);
      }
      // Fallback to index.html for SPA routing
      const indexFile = path.join(DIST, 'index.html');
      if (fs.existsSync(indexFile)) {
        return sendFile(res, indexFile);
      }
      res.writeHead(404);
      res.end('Not found');
    });
  } catch (e) {
    res.writeHead(500);
    res.end('Server Error');
  }
});

server.listen(PORT, () => {
  console.log(`Static server serving ${DIST} on port ${PORT}`);
});
