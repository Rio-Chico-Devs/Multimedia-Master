const express = require('express');
const multer = require('multer');
const sharp = require('sharp');
const archiver = require('archiver');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');

const app = express();
const PORT = 3000;

// Directories
const UPLOADS_DIR = path.join(__dirname, 'uploads');
const CONVERTED_DIR = path.join(__dirname, 'converted');

[UPLOADS_DIR, CONVERTED_DIR].forEach(dir => {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
});

// Multer config — accept images up to 100MB
const storage = multer.diskStorage({
  destination: UPLOADS_DIR,
  filename: (req, file, cb) => {
    const uniqueName = crypto.randomUUID() + path.extname(file.originalname);
    cb(null, uniqueName);
  },
});

const upload = multer({
  storage,
  limits: { fileSize: 100 * 1024 * 1024 },
  fileFilter: (req, file, cb) => {
    const ALLOWED_MIME = [
      'image/jpeg', 'image/png', 'image/webp', 'image/avif',
      'image/tiff', 'image/gif', 'image/bmp', 'image/svg+xml',
    ];
    if (ALLOWED_MIME.includes(file.mimetype)) {
      cb(null, true);
    } else {
      cb(new Error(`Formato non supportato: ${file.mimetype}`));
    }
  },
});

// Quality presets — best compromise between quality and file size
const FORMAT_PRESETS = {
  jpeg: { quality: 85, progressive: true, mozjpeg: true },
  jpg:  { quality: 85, progressive: true, mozjpeg: true },
  png:  { compressionLevel: 6, adaptiveFiltering: true, palette: false },
  webp: { quality: 85, effort: 4, smartSubsample: true },
  avif: { quality: 62, effort: 4, chromaSubsampling: '4:4:4' },
  tiff: { quality: 90, compression: 'lzw' },
  gif:  { colours: 256, effort: 7 },
};

// Supported output formats per input format
const FORMAT_MAP = {
  jpeg: ['jpeg', 'png', 'webp', 'avif', 'tiff', 'gif'],
  jpg:  ['jpeg', 'png', 'webp', 'avif', 'tiff', 'gif'],
  png:  ['png', 'jpeg', 'webp', 'avif', 'tiff', 'gif'],
  webp: ['webp', 'jpeg', 'png', 'avif', 'tiff', 'gif'],
  avif: ['avif', 'jpeg', 'png', 'webp', 'tiff'],
  tiff: ['tiff', 'jpeg', 'png', 'webp', 'avif'],
  gif:  ['gif', 'jpeg', 'png', 'webp'],
  bmp:  ['jpeg', 'png', 'webp', 'avif', 'tiff', 'gif'],
  svg:  ['png', 'jpeg', 'webp'],
};

app.use(express.static('public'));
app.use(express.json());

// ─── GET /api/formats ─────────────────────────────────────────────────────────
// Returns supported output formats for a given input extension
app.get('/api/formats', (req, res) => {
  const ext = (req.query.ext || '').toLowerCase().replace('.', '');
  const formats = FORMAT_MAP[ext] || ['jpeg', 'png', 'webp', 'avif'];
  res.json({ formats });
});

// ─── POST /api/convert ────────────────────────────────────────────────────────
app.post('/api/convert', upload.array('files', 50), async (req, res) => {
  if (!req.files || req.files.length === 0) {
    return res.status(400).json({ error: 'Nessun file caricato.' });
  }

  const {
    format = 'webp',
    quality,         // optional override (1–100)
    width,           // optional resize
    height,          // optional resize
    fit = 'inside',  // cover | contain | fill | inside | outside
    withoutEnlargement = 'true',
    stripMeta = 'true',
  } = req.body;

  const results = [];
  const errors = [];

  for (const file of req.files) {
    try {
      const outputFormat = format.toLowerCase();
      const preset = { ...FORMAT_PRESETS[outputFormat] };

      // Apply user quality override (maps 1-100 for all formats)
      if (quality !== undefined && quality !== '') {
        const q = parseInt(quality, 10);
        if (!isNaN(q) && q >= 1 && q <= 100) {
          if (outputFormat === 'png') {
            // PNG: quality maps to compressionLevel 0–9
            preset.compressionLevel = Math.round((100 - q) / 11);
          } else if (outputFormat === 'gif') {
            preset.colours = Math.max(2, Math.round((q / 100) * 256));
          } else {
            preset.quality = q;
          }
        }
      }

      const outputExt = outputFormat === 'jpeg' ? 'jpg' : outputFormat;
      const outputName = path.parse(file.originalname).name + '_converted.' + outputExt;
      const outputId = crypto.randomUUID();
      const outputPath = path.join(CONVERTED_DIR, outputId + '.' + outputExt);

      let pipeline = sharp(file.path, { failOn: 'none' });

      // Preserve ICC color profile and convert to sRGB if needed (prevents color shift)
      pipeline = pipeline.keepIccProfile();

      // Resize (only if requested)
      if ((width && width !== '') || (height && height !== '')) {
        const resizeOpts = {
          fit,
          withoutEnlargement: withoutEnlargement === 'true',
          kernel: sharp.kernel.lanczos3, // highest quality downsampling
        };
        if (width && width !== '') resizeOpts.width = parseInt(width, 10);
        if (height && height !== '') resizeOpts.height = parseInt(height, 10);
        pipeline = pipeline.resize(resizeOpts);
      }

      // Strip EXIF metadata if requested (reduces size, keeps color profile)
      if (stripMeta === 'true') {
        pipeline = pipeline.withMetadata({ icc: true }); // keep ICC, strip the rest
      } else {
        pipeline = pipeline.withMetadata(); // keep all metadata
      }

      // Apply output format
      switch (outputFormat) {
        case 'jpeg':
        case 'jpg':
          pipeline = pipeline.jpeg(preset);
          break;
        case 'png':
          pipeline = pipeline.png(preset);
          break;
        case 'webp':
          pipeline = pipeline.webp(preset);
          break;
        case 'avif':
          pipeline = pipeline.avif(preset);
          break;
        case 'tiff':
          pipeline = pipeline.tiff(preset);
          break;
        case 'gif':
          pipeline = pipeline.gif(preset);
          break;
        default:
          pipeline = pipeline.toFormat(outputFormat);
      }

      const info = await pipeline.toFile(outputPath);

      const originalSize = file.size;
      const convertedSize = fs.statSync(outputPath).size;
      const saving = Math.round((1 - convertedSize / originalSize) * 100);

      results.push({
        id: outputId,
        originalName: file.originalname,
        outputName,
        outputExt,
        originalSize,
        convertedSize,
        saving,
        width: info.width,
        height: info.height,
      });
    } catch (err) {
      errors.push({ file: file.originalname, error: err.message });
    } finally {
      // Clean up upload temp file
      fs.unlink(file.path, () => {});
    }
  }

  res.json({ results, errors });
});

// ─── GET /api/download/:id ────────────────────────────────────────────────────
app.get('/api/download/:id', (req, res) => {
  const { id } = req.params;
  const { name, ext } = req.query;

  // Sanitize id — only allow UUID chars
  if (!/^[0-9a-f-]{36}$/.test(id)) {
    return res.status(400).json({ error: 'ID non valido.' });
  }

  const safeExt = (ext || 'jpg').replace(/[^a-z0-9]/gi, '').toLowerCase();
  const filePath = path.join(CONVERTED_DIR, `${id}.${safeExt}`);

  if (!fs.existsSync(filePath)) {
    return res.status(404).json({ error: 'File non trovato.' });
  }

  const downloadName = name || `converted.${safeExt}`;
  res.download(filePath, downloadName, () => {
    // Auto-cleanup after download
    setTimeout(() => fs.unlink(filePath, () => {}), 5000);
  });
});

// ─── POST /api/download-zip ────────────────────────────────────────────────────
app.post('/api/download-zip', express.json(), (req, res) => {
  const { files } = req.body; // [{ id, name, ext }, ...]

  if (!Array.isArray(files) || files.length === 0) {
    return res.status(400).json({ error: 'Nessun file specificato.' });
  }

  res.setHeader('Content-Type', 'application/zip');
  res.setHeader('Content-Disposition', 'attachment; filename="converted_images.zip"');

  const archive = archiver('zip', { zlib: { level: 0 } }); // no extra compression for images
  archive.pipe(res);

  const paths = [];
  for (const f of files) {
    if (!/^[0-9a-f-]{36}$/.test(f.id)) continue;
    const safeExt = (f.ext || 'jpg').replace(/[^a-z0-9]/gi, '').toLowerCase();
    const filePath = path.join(CONVERTED_DIR, `${f.id}.${safeExt}`);
    if (fs.existsSync(filePath)) {
      archive.file(filePath, { name: f.name || `${f.id}.${safeExt}` });
      paths.push(filePath);
    }
  }

  archive.finalize();

  archive.on('end', () => {
    // Cleanup after short delay
    setTimeout(() => paths.forEach(p => fs.unlink(p, () => {})), 5000);
  });
});

// ─── Cleanup old files every hour ─────────────────────────────────────────────
function cleanupOldFiles() {
  const maxAge = 60 * 60 * 1000; // 1 hour
  const now = Date.now();
  [UPLOADS_DIR, CONVERTED_DIR].forEach(dir => {
    fs.readdir(dir, (err, files) => {
      if (err) return;
      files.forEach(file => {
        const p = path.join(dir, file);
        fs.stat(p, (err, stat) => {
          if (!err && now - stat.mtimeMs > maxAge) {
            fs.unlink(p, () => {});
          }
        });
      });
    });
  });
}
setInterval(cleanupOldFiles, 60 * 60 * 1000);

app.listen(PORT, () => {
  console.log(`\n✅  Multimedia Master in esecuzione su http://localhost:${PORT}\n`);
});
