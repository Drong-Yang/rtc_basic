// Expose only authenticated RTC callbacks and the reviewed demo documents.
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const files = new Set(Array.from({length: 4}, (_, i) => `ecommerce_demo_v1_${i}.md`));
http.createServer((req, res) => {
  const file = req.url.startsWith('/knowledge/') ? req.url.slice('/knowledge/'.length) : '';
  if (req.method === 'GET' && files.has(file)) {
    res.setHeader('Content-Type', 'text/markdown; charset=utf-8');
    fs.createReadStream(path.join(__dirname, '../rag_llm_server/knowledge', file)).pipe(res);
    return;
  }
  if (req.method !== 'POST' || !['/api/chat_callback', '/api/rtc_events'].includes(req.url)) {
    res.writeHead(404); res.end(); return;
  }
  const upstream = http.request({hostname: '127.0.0.1', port: 3001, path: req.url,
    method: 'POST', headers: req.headers}, response => {
    res.writeHead(response.statusCode, response.headers); response.pipe(res);
  });
  upstream.on('error', () => { if (!res.headersSent) res.writeHead(502); res.end(); });
  req.on('aborted', () => upstream.destroy());
  res.on('close', () => upstream.destroy());
  req.pipe(upstream);
}).listen(3002, '127.0.0.1', () => console.log('Callback gateway: http://127.0.0.1:3002'));
