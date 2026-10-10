import QRCode from 'qrcode';

const CARD_W = 480;
const PADDING = 26;
const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif';
const ACCENT = '#e2b870';
const TEXT_COLOR = '#f5f0e8';
const MUTED_COLOR = '#b0b8c5';
const COVER_RADIUS = 16;
const TEXT_W = CARD_W - 2 * PADDING;

const HEADER_H = 35;
const HEADER_GAP = 13;
const DIVIDER_GAP = 16;
const TITLE_LINE_H = 45;
const MAX_TITLE_LINES = 2;
const TITLE_GAP = 16;
const MEDIA_H = 320;
const MEDIA_GAP = 19;
const DESC_LINE_H = 29;
const MAX_DESC_LINES = 5;
const DESC_MEASURE_FONT = `19px ${FONT}`;
const DESC_DRAW_FONT = `12px ${FONT}`;

function wrapLines(ctx, text, maxW, maxLines) {
    const chars = Array.from(text);
    const lines = [];
    let idx = 0;
    while (idx < chars.length && lines.length < maxLines) {
        let line = '';
        while (idx < chars.length) {
            const next = line + chars[idx];
            if (ctx.measureText(next).width > maxW) break;
            line = next;
            idx++;
        }
        if (!line) {
            line = chars[idx] || '';
            idx++;
        }
        lines.push(line);
    }
    if (idx < chars.length && lines.length > 0) {
        const ellipsis = '…';
        const last = Array.from(lines[lines.length - 1]);
        while (last.length > 0 && ctx.measureText(last.join('') + ellipsis).width > maxW) last.pop();
        lines[lines.length - 1] = last.join('') + ellipsis;
    }
    return lines;
}

function roundedRectPath(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
}

function loadImage(src) {
    return new Promise((resolve) => {
        const img = new Image();
        img.crossOrigin = 'anonymous';
        img.onload = () => resolve(img);
        img.onerror = () => resolve(null);
        img.src = src;
    });
}

function drawCover(ctx, img, x, y, w, h) {
    if (img) {
        ctx.save();
        ctx.shadowColor = 'rgba(0,0,0,0.4)';
        ctx.shadowBlur = 10;
        ctx.shadowOffsetX = 2;
        ctx.shadowOffsetY = 4;
        roundedRectPath(ctx, x, y, w, h, COVER_RADIUS);
        ctx.clip();
        ctx.drawImage(img, x, y, w, h);
        ctx.restore();

        ctx.save();
        ctx.shadowBlur = 0;
        ctx.strokeStyle = ACCENT + '40';
        ctx.lineWidth = 1.5;
        roundedRectPath(ctx, x, y, w, h, COVER_RADIUS);
        ctx.stroke();
        ctx.restore();
        return;
    }
    ctx.fillStyle = '#2a2a2e';
    roundedRectPath(ctx, x, y, w, h, COVER_RADIUS);
    ctx.fill();
    ctx.fillStyle = MUTED_COLOR;
    ctx.font = `16px ${FONT}`;
    ctx.textAlign = 'center';
    ctx.fillText('📖', x + w / 2, y + h / 2);
    ctx.textAlign = 'left';
}

async function drawQr(ctx, qrUrl, qrLabel, mediaY, halfW) {
    const size = Math.min(144, halfW - 32);
    const labelH = 22;
    const centerX = PADDING + halfW + Math.round((TEXT_W - halfW) / 2);
    const x = Math.round(centerX - size / 2);
    const y = Math.round(mediaY + (MEDIA_H - (size + 6 + labelH)) / 2);
    const bgPad = 4;

    ctx.fillStyle = '#f5efe5';
    roundedRectPath(ctx, x - bgPad, y - bgPad, size + bgPad * 2, size + bgPad * 2, 8);
    ctx.fill();

    const qrCanvas = document.createElement('canvas');
    await QRCode.toCanvas(qrCanvas, qrUrl, { width: size, margin: 1, color: { dark: '#1f1f28', light: '#f5efe5' } });
    ctx.drawImage(qrCanvas, x, y, size, size);

    ctx.font = `16px ${FONT}`;
    ctx.fillStyle = MUTED_COLOR;
    ctx.textAlign = 'center';
    ctx.fillText(qrLabel, centerX, y + size + 8);
    ctx.textAlign = 'left';
}

function drawHeader(ctx, siteTitle, y) {
    ctx.font = `500 19px ${FONT}`;
    ctx.fillStyle = TEXT_COLOR;
    ctx.fillText(siteTitle, PADDING, y + Math.round((HEADER_H - 19) / 2));

    const now = new Date();
    const dateStr = `${now.getFullYear()}.${String(now.getMonth() + 1).padStart(2, '0')}.${String(now.getDate()).padStart(2, '0')}`;
    ctx.font = `16px ${FONT}`;
    ctx.fillStyle = MUTED_COLOR;
    ctx.fillText(dateStr, CARD_W - PADDING - ctx.measureText(dateStr).width, y + Math.round((HEADER_H - 16) / 2));
}

function drawBackground(ctx, height) {
    const grad = ctx.createLinearGradient(0, 0, CARD_W, height);
    grad.addColorStop(0, '#2d4333');
    grad.addColorStop(1, '#134e5e');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, CARD_W, height);

    for (let i = 0; i < 80; i++) {
        const alpha = (0.1 + Math.random() * 0.3).toFixed(2);
        ctx.fillStyle = `rgba(255,62,47,${alpha})`;
        ctx.beginPath();
        ctx.arc(Math.random() * CARD_W, Math.random() * height, 1 + Math.random() * 10, 0, Math.PI * 2);
        ctx.fill();
    }
}

export async function renderBookShareCard({ title, comments, coverUrl, qrUrl, qrLabel = '扫码阅读', siteTitle = 'MyBooks' }) {
    const measureCtx = document.createElement('canvas').getContext('2d');
    measureCtx.font = `bold 32px ${FONT}`;
    const titleLines = wrapLines(measureCtx, title || '', TEXT_W, MAX_TITLE_LINES);
    const titleLineCount = Math.max(titleLines.length, 1);

    const commentText = (comments || '').replace(/<[^>]*>/g, '').trim();
    const hasComments = !!(commentText && commentText !== '暂无简介');
    measureCtx.font = DESC_MEASURE_FONT;
    const descLineCount = hasComments ? wrapLines(measureCtx, commentText, TEXT_W, MAX_DESC_LINES).length : 0;

    let cardH = PADDING + HEADER_H + HEADER_GAP + 1 + DIVIDER_GAP + titleLineCount * TITLE_LINE_H + TITLE_GAP + MEDIA_H;
    if (descLineCount > 0) cardH += MEDIA_GAP + descLineCount * DESC_LINE_H;
    cardH += PADDING;

    const canvas = document.createElement('canvas');
    canvas.width = CARD_W;
    canvas.height = cardH;
    const ctx = canvas.getContext('2d');
    ctx.shadowColor = 'transparent';
    ctx.shadowBlur = 0;

    ctx.save();
    roundedRectPath(ctx, 0, 0, CARD_W, cardH, 0);
    ctx.clip();
    drawBackground(ctx, cardH);

    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    let curY = PADDING;
    drawHeader(ctx, siteTitle, curY);
    curY += HEADER_H + HEADER_GAP;

    ctx.strokeStyle = ACCENT + '60';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(PADDING, curY);
    ctx.lineTo(CARD_W - PADDING, curY);
    ctx.stroke();
    curY += 1 + DIVIDER_GAP;

    ctx.font = `bold 32px ${FONT}`;
    ctx.fillStyle = TEXT_COLOR;
    ctx.textAlign = 'center';
    wrapLines(ctx, title || '', TEXT_W, MAX_TITLE_LINES).forEach((line, i) => ctx.fillText(line, CARD_W / 2, curY + i * TITLE_LINE_H));
    ctx.textAlign = 'left';
    curY += titleLineCount * TITLE_LINE_H + TITLE_GAP;

    const mediaY = curY;
    const halfW = Math.floor(TEXT_W / 2);
    const coverMaxW = halfW - 12;
    const coverH = Math.min(MEDIA_H - 8, Math.round(coverMaxW * 15 / 11));
    const coverW = Math.round(coverH * 11 / 15);
    const coverImg = await loadImage(coverUrl);
    drawCover(ctx, coverImg, Math.round(PADDING + (halfW - coverW) / 2), Math.round(mediaY + (MEDIA_H - coverH) / 2), coverW, coverH);
    await drawQr(ctx, qrUrl, qrLabel, mediaY, halfW);
    curY = mediaY + MEDIA_H;

    if (descLineCount > 0) {
        curY += MEDIA_GAP;
        ctx.font = DESC_DRAW_FONT;
        ctx.globalAlpha = 0.87;
        ctx.fillStyle = TEXT_COLOR;
        wrapLines(ctx, commentText, TEXT_W, MAX_DESC_LINES).forEach((line, i) => ctx.fillText(line, PADDING, curY + i * DESC_LINE_H));
        ctx.globalAlpha = 1;
    }
    ctx.restore();

    ctx.save();
    ctx.shadowBlur = 0;
    ctx.strokeStyle = ACCENT + '30';
    ctx.lineWidth = 2;
    roundedRectPath(ctx, 2, 2, CARD_W - 4, cardH - 4, 0);
    ctx.stroke();
    ctx.restore();

    return canvas.toDataURL('image/png');
}

export function downloadImage(dataUrl, fileName) {
    const a = document.createElement('a');
    a.download = fileName;
    a.href = dataUrl;
    a.click();
}

export function shareCardFileName(title) {
    return `${(title || 'book').replace(/[/\\:*?"<>|]/g, '_')}_分享卡片`;
}
