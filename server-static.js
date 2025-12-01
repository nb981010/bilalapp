import http from 'http';
import fs from 'fs';
import path from 'path';
import url from 'url';

const PORT = process.env.PORT || 3000;
const DIST = path.join(path.dirname(new URL(import.meta.url).pathname), 'dist');

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
    // Serve with long-lived caching by default (matches previous behavior)
    res.writeHead(200, { 'Content-Type': contentType, 'Cache-Control': 'public, max-age=31536000' });
    res.end(content);
  });
}

function proxyToBackend(req, res) {
  const backendOpts = {
    hostname: '127.0.0.1',
    port: 5000,
    path: req.url,
    method: req.method,
    headers: req.headers,
  };
  const pres = http.request(backendOpts, (presp) => {
    const headers = presp.headers;
    res.writeHead(presp.statusCode || 200, headers);
    presp.pipe(res);
  });
  pres.on('error', (err) => {
    res.writeHead(502, { 'Content-Type': 'text/plain' });
    res.end('Bad Gateway');
  });
  req.pipe(pres);
}

const server = http.createServer((req, res) => {
  try {
    const parsed = url.parse(req.url || '/');
    let pathname = decodeURIComponent(parsed.pathname || '/');
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
