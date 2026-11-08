/**
 * A hand-drawn Canvas2D companion.
 *
 * This is the default renderer until the Live2D Cubism runtime is dropped in
 * (see src/live2d/adapter.js and renderer/README.md). It exercises the same
 * bridge surface as a real model: expressions, motions, mouth sync, captions
 * and click reactions all work today.
 */

const SIZE = 420;

const PALETTE = {
  hairDark: "#5a4794",
  hairMid: "#8b74d8",
  hairLight: "#c8b6ff",
  hairShine: "#efe8ff",
  skin: "#ffe9df",
  skinShade: "#f7cfc4",
  blush: "rgba(255, 142, 168, 0.55)",
  dressDark: "#2b2648",
  dressMid: "#453a6d",
  dressLight: "#67579b",
  trim: "#f3eaff",
  accent: "#ff9ac1",
  accentDeep: "#e4669e",
  eyeTop: "#6a4fd8",
  eyeBottom: "#59d5e8",
  line: "#3b3159",
  gold: "#ffd479",
};

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function easeOutCubic(t) {
  return 1 - Math.pow(1 - t, 3);
}

function heartPath(ctx, x, y, size, rotation = 0) {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(rotation);
  ctx.beginPath();
  ctx.moveTo(0, size * 0.35);
  ctx.bezierCurveTo(-size, -size * 0.25, -size * 0.55, -size, 0, -size * 0.45);
  ctx.bezierCurveTo(size * 0.55, -size, size, -size * 0.25, 0, size * 0.35);
  ctx.closePath();
  ctx.restore();
}

function ellipse(ctx, x, y, rx, ry) {
  ctx.beginPath();
  ctx.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2);
}

export class PlaceholderCharacter {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d", { alpha: true });
    this.dpr = 0;
    this.expression = "neutral";
    this.expressionUntil = 0;
    this.speaking = false;
    this.mouth = 0;
    this.look = { x: 0, y: 0 };
    this.lookTarget = { x: 0, y: 0 };
    this.hearts = [];
    this.lastFrame = 0;
    this.blinkAt = 0;
    this.blinkEnd = 0;
    this.bounce = 0;
    this.nextBlink = performance.now() + 2200 + Math.random() * 2400;
    this.visible = true;
  }

  setVisible(value) {
    this.visible = value;
  }

  setExpression(name) {
    const allowed = new Set(["neutral", "happy", "sad", "surprised", "thinking"]);
    this.expression = allowed.has(name) ? name : "neutral";
    this.expressionUntil = 0;
  }

  playMotion(group = "", index = 0) {
    const label = String(group).toLowerCase();
    if (label.includes("happy") || label.includes("smile") || label.includes("joy")) {
      this.reactHappy();
    } else if (label.includes("sad") || label.includes("cry")) {
      this.setExpressionTemporarily("sad", 2600);
    } else if (label.includes("surprise") || label.includes("shock")) {
      this.setExpressionTemporarily("surprised", 1800);
    } else if (label.includes("think") || label.includes("idle")) {
      this.setExpressionTemporarily("thinking", 1600);
    } else {
      this.bounce = 1;
      this.spawnHearts(2);
    }
    this.lastMotion = { group, index };
  }

  setExpressionTemporarily(name, duration) {
    this.expression = name;
    this.expressionUntil = performance.now() + duration;
  }

  setSpeaking(value) {
    this.speaking = Boolean(value);
    if (!this.speaking) this.mouth = 0;
  }

  setMouth(value) {
    this.mouth = clamp(Number(value) || 0, 0, 1);
  }

  setLook(x, y) {
    this.lookTarget.x = clamp(x, -1, 1);
    this.lookTarget.y = clamp(y, -1, 1);
  }

  reactHappy() {
    this.setExpressionTemporarily("happy", 2400);
    this.bounce = 1;
    this.spawnHearts(5);
  }

  spawnHearts(count = 4) {
    for (let i = 0; i < count; i += 1) {
      this.hearts.push({
        x: 210 + (Math.random() - 0.5) * 100,
        y: 120 + Math.random() * 50,
        vy: -0.035 - Math.random() * 0.03,
        sway: Math.random() * Math.PI * 2,
        size: 5 + Math.random() * 5,
        age: 0,
        ttl: 1100 + Math.random() * 700,
      });
    }
  }

  _eyeBlink(now) {
    if (now >= this.nextBlink) {
      this.blinkEnd = now + 110 + Math.random() * 50;
      this.nextBlink = now + 2300 + Math.random() * 3200;
    }
    if (now < this.blinkEnd) {
      const progress = (this.blinkEnd - now) / 110;
      return clamp(1 - Math.abs(progress - 0.5) * 2, 0, 1);
    }
    return 0;
  }

  _resize(now) {
    const dpr = Math.min(window.devicePixelRatio || 1, 3);
    if (this.dpr !== dpr) {
      this.dpr = dpr;
      this.canvas.width = Math.round(SIZE * dpr);
      this.canvas.height = Math.round(SIZE * dpr);
    }
    const ctx = this.ctx;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, SIZE, SIZE);
    return ctx;
  }

  draw(now) {
    if (!this.visible) return;
    const dt = Math.min(50, this.lastFrame ? now - this.lastFrame : 16);
    this.lastFrame = now;
    if (this.expressionUntil && now > this.expressionUntil) {
      this.expression = "neutral";
      this.expressionUntil = 0;
    }
    const ctx = this._resize(now);
    const t = now / 1000;
    const blink = this._eyeBlink(now);
    const bob = Math.sin(t * 1.35) * 3.6 + this.bounce * 4;
    const sway = Math.sin(t * 0.72) * 2.6;
    this.look.x += (this.lookTarget.x - this.look.x) * 0.09;
    this.look.y += (this.lookTarget.y - this.look.y) * 0.09;
    this.bounce *= 0.92;

    ctx.save();
    ctx.translate(sway * 0.5, bob);
    this._drawAura(ctx, t);
    this._drawShadow(ctx);
    this._drawTails(ctx, t);
    this._drawBody(ctx, t);
    this._drawHead(ctx, t, blink);
    this._drawMouth(ctx, now);
    this._drawHairFront(ctx, t);
    this._drawAccessories(ctx, t);
    ctx.restore();

    this._drawHearts(ctx, dt);
    this._drawFrameTimer = now;
  }

  _drawAura(ctx, t) {
    const radius = 205 + Math.sin(t * 0.6) * 6;
    const gradient = ctx.createRadialGradient(210, 245, 20, 210, 245, radius);
    gradient.addColorStop(0, "rgba(189, 168, 255, 0.14)");
    gradient.addColorStop(0.55, "rgba(255, 154, 193, 0.06)");
    gradient.addColorStop(1, "rgba(255, 255, 255, 0)");
    ctx.fillStyle = gradient;
    ellipse(ctx, 210, 245, radius, radius * 0.86);
    ctx.fill();
  }

  _drawShadow(ctx) {
    const gradient = ctx.createRadialGradient(210, 402, 4, 210, 402, 110);
    gradient.addColorStop(0, "rgba(43, 31, 74, 0.28)");
    gradient.addColorStop(1, "rgba(43, 31, 74, 0)");
    ctx.fillStyle = gradient;
    ellipse(ctx, 210, 402, 100, 18);
    ctx.fill();
  }

  _tailPath(ctx, side, sway) {
    const dir = side === "left" ? 1 : -1;
    const x = 210 + dir * 78;
    ctx.beginPath();
    ctx.moveTo(x, 132);
    ctx.bezierCurveTo(x + dir * 66, 175 + sway, x + dir * 84, 260 - sway, x + dir * 40, 338);
    ctx.bezierCurveTo(x + dir * 22, 364, x + dir * 44, 380, x + dir * 8, 378);
    ctx.bezierCurveTo(x + dir * 8, 340, x + dir * 6, 300, x, 262);
    ctx.closePath();
  }

  _drawTails(ctx, t) {
    const sway = Math.sin(t * 0.9) * 5;
    const gradient = ctx.createLinearGradient(120, 140, 300, 350);
    gradient.addColorStop(0, PALETTE.hairMid);
    gradient.addColorStop(0.6, PALETTE.hairDark);
    gradient.addColorStop(1, "#493975");
    for (const side of ["left", "right"]) {
      this._tailPath(ctx, side, sway);
      ctx.fillStyle = gradient;
      ctx.fill();
      ctx.strokeStyle = "rgba(59, 49, 89, 0.55)";
      ctx.lineWidth = 2;
      ctx.stroke();
      // A soft ribbon of light down each tail.
      const dir = side === "left" ? 1 : -1;
      const x = 210 + dir * 78;
      ctx.beginPath();
      ctx.moveTo(x + dir * 18, 170 + sway);
      ctx.quadraticCurveTo(x + dir * 48, 255, x + dir * 18, 330);
      ctx.strokeStyle = "rgba(233, 222, 255, 0.35)";
      ctx.lineWidth = 3;
      ctx.stroke();
    }
  }

  _drawBody(ctx, t) {
    // Legs and shoes.
    for (const [x, dir] of [[191, -1], [229, 1]]) {
      ctx.fillStyle = PALETTE.skin;
      ctx.beginPath();
      ctx.roundRect(x - 9, 365, 18, 38, 8);
      ctx.fill();
      ctx.fillStyle = "#4b3a6c";
      ctx.beginPath();
      ctx.ellipse(x + dir * 2, 407, 15, 7, 0, 0, Math.PI * 2);
      ctx.fill();
    }

    // Skirt.
    const skirt = ctx.createLinearGradient(170, 315, 250, 395);
    skirt.addColorStop(0, PALETTE.dressLight);
    skirt.addColorStop(0.55, PALETTE.dressMid);
    skirt.addColorStop(1, PALETTE.dressDark);
    ctx.beginPath();
    ctx.moveTo(172, 312);
    ctx.bezierCurveTo(150, 340, 122, 366, 113, 386);
    ctx.quadraticCurveTo(210, 404, 307, 386);
    ctx.bezierCurveTo(298, 366, 270, 340, 248, 312);
    ctx.closePath();
    ctx.fillStyle = skirt;
    ctx.fill();
    ctx.strokeStyle = "rgba(59, 49, 89, 0.6)";
    ctx.lineWidth = 2;
    ctx.stroke();

    // Skirt folds and trim.
    ctx.strokeStyle = "rgba(243, 234, 255, 0.35)";
    ctx.lineWidth = 2;
    for (const x of [160, 200, 240, 276]) {
      ctx.beginPath();
      ctx.moveTo(210 + (x - 210) * 0.35, 322);
      ctx.quadraticCurveTo(x, 350, 210 + (x - 210) * 1.25, 388);
      ctx.stroke();
    }
    ctx.strokeStyle = "rgba(243, 234, 255, 0.75)";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(121, 383);
    ctx.quadraticCurveTo(210, 399, 299, 383);
    ctx.stroke();

    // Arms.
    for (const dir of [-1, 1]) {
      const shoulderX = 210 + dir * 52;
      const handX = 210 + dir * 82;
      const handY = 342 + Math.sin(t * 1.1 + dir) * 2;
      ctx.strokeStyle = PALETTE.skin;
      ctx.lineCap = "round";
      ctx.lineWidth = 17;
      ctx.beginPath();
      ctx.moveTo(shoulderX, 286);
      ctx.quadraticCurveTo(210 + dir * 88, 315, handX, handY);
      ctx.stroke();
      ctx.fillStyle = PALETTE.skin;
      ellipse(ctx, handX, handY + 4, 10, 12);
      ctx.fill();
      // Puff sleeve.
      ctx.fillStyle = PALETTE.dressMid;
      ctx.beginPath();
      ctx.ellipse(shoulderX, 286, 24, 19, dir * 0.35, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = "rgba(243, 234, 255, 0.35)";
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    // Bodice.
    const bodice = ctx.createLinearGradient(190, 260, 230, 330);
    bodice.addColorStop(0, PALETTE.dressMid);
    bodice.addColorStop(1, PALETTE.dressDark);
    ctx.beginPath();
    ctx.moveTo(171, 270);
    ctx.quadraticCurveTo(210, 258, 249, 270);
    ctx.lineTo(252, 314);
    ctx.quadraticCurveTo(210, 330, 168, 314);
    ctx.closePath();
    ctx.fillStyle = bodice;
    ctx.fill();
    ctx.strokeStyle = "rgba(59, 49, 89, 0.55)";
    ctx.lineWidth = 2;
    ctx.stroke();

    // Neck and collar.
    ctx.fillStyle = PALETTE.skin;
    ctx.beginPath();
    ctx.roundRect(196, 238, 28, 34, 12);
    ctx.fill();
    ctx.fillStyle = PALETTE.trim;
    ctx.beginPath();
    ctx.moveTo(182, 272);
    ctx.quadraticCurveTo(210, 258, 238, 272);
    ctx.quadraticCurveTo(226, 284, 210, 278);
    ctx.quadraticCurveTo(194, 284, 182, 272);
    ctx.closePath();
    ctx.fill();

    // Ribbon.
    ctx.fillStyle = PALETTE.accent;
    ctx.beginPath();
    ctx.moveTo(210, 282);
    ctx.lineTo(196, 272);
    ctx.lineTo(196, 292);
    ctx.closePath();
    ctx.fill();
    ctx.beginPath();
    ctx.moveTo(210, 282);
    ctx.lineTo(224, 272);
    ctx.lineTo(224, 292);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = PALETTE.accentDeep;
    ellipse(ctx, 210, 282, 4, 4);
    ctx.fill();
  }

  _drawHead(ctx, t, blink) {
    // Ears.
    for (const dir of [-1, 1]) {
      ctx.fillStyle = PALETTE.skin;
      ctx.beginPath();
      ctx.ellipse(210 + dir * 82, 180, 13, 22, dir * 0.18, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = "rgba(247, 207, 196, 0.8)";
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    // Face.
    const face = ctx.createRadialGradient(190, 145, 18, 210, 170, 98);
    face.addColorStop(0, "#fff5ef");
    face.addColorStop(0.75, PALETTE.skin);
    face.addColorStop(1, PALETTE.skinShade);
    ctx.fillStyle = face;
    ellipse(ctx, 210, 169, 86, 83);
    ctx.fill();
    ctx.strokeStyle = "rgba(59, 49, 89, 0.42)";
    ctx.lineWidth = 2;
    ctx.stroke();

    // Blush.
    ctx.fillStyle = PALETTE.blush;
    ellipse(ctx, 158, 205, 18, 9);
    ctx.fill();
    ellipse(ctx, 262, 205, 18, 9);
    ctx.fill();

    this._drawBrows(ctx);
    this._drawEyes(ctx, blink);
    this._drawNose(ctx);

    // Cheek sparkles on hover.
    if (this.expression === "happy") {
      ctx.fillStyle = "rgba(255,255,255,0.85)";
      for (const [x, y, r] of [[152, 190, 2.2], [268, 196, 1.8], [278, 186, 1.4]]) {
        ellipse(ctx, x, y, r, r);
        ctx.fill();
      }
    }
  }

  _drawBrows(ctx) {
    ctx.strokeStyle = "rgba(86, 67, 128, 0.72)";
    ctx.lineWidth = 4;
    ctx.lineCap = "round";
    const sad = this.expression === "sad";
    for (const dir of [-1, 1]) {
      const x = 210 + dir * 34;
      const y = sad ? 148 : 146;
      ctx.beginPath();
      ctx.moveTo(x - 17, y + (sad ? 4 : 0));
      ctx.quadraticCurveTo(x, y - 3, x + 17, y + (sad ? -3 : 0));
      ctx.stroke();
    }
  }

  _drawEyes(ctx, blink) {
    const happy = this.expression === "happy";
    const sad = this.expression === "sad";
    const surprised = this.expression === "surprised";
    const thinking = this.expression === "thinking";
    const open = clamp(1 - blink, 0.08, 1);
    const eyeScale = surprised ? 1.14 : sad ? 0.82 : happy ? 1.02 : 1;
    const lookX = this.look.x * 4.2;
    const lookY = this.look.y * 3.4 + (thinking ? -3 : 0);

    for (const dir of [-1, 1]) {
      const cx = 210 + dir * 33;
      const cy = 181;
      const rx = 22;
      const ry = 25 * eyeScale * open;

      ctx.save();
      ctx.translate(cx + lookX * 0.3, cy + lookY * 0.2);
      if (blink > 0.72 || (happy && this.expressionUntil === 0 && Math.sin(performance.now() / 900) > 0.92)) {
        ctx.strokeStyle = PALETTE.line;
        ctx.lineWidth = 4;
        ctx.lineCap = "round";
        ctx.beginPath();
        ctx.arc(0, 2, 17, 0.15 * Math.PI, 0.85 * Math.PI);
        ctx.stroke();
        ctx.restore();
        continue;
      }

      // Sclera.
      ctx.fillStyle = "#fffafd";
      ctx.beginPath();
      ctx.ellipse(0, 0, rx, Math.max(3, ry), 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = "rgba(90, 71, 148, 0.5)";
      ctx.lineWidth = 1.6;
      ctx.stroke();

      // Iris.
      const iris = ctx.createLinearGradient(0, -ry, 0, ry);
      iris.addColorStop(0, PALETTE.eyeTop);
      iris.addColorStop(1, PALETTE.eyeBottom);
      ctx.save();
      ctx.beginPath();
      ctx.ellipse(0, 0, rx, Math.max(3, ry), 0, 0, Math.PI * 2);
      ctx.clip();
      ctx.fillStyle = iris;
      ellipse(ctx, lookX, lookY, 17, 20 * eyeScale);
      ctx.fill();
      ctx.fillStyle = "rgba(36, 23, 76, 0.9)";
      ellipse(ctx, lookX, lookY + 1, 8, 11 * eyeScale);
      ctx.fill();
      ctx.fillStyle = "rgba(255, 255, 255, 0.95)";
      ellipse(ctx, lookX - 5, lookY - 7, 4.2, 5);
      ctx.fill();
      ellipse(ctx, lookX + 5, lookY + 6, 2, 2.4);
      ctx.fill();
      // Lower reflected light.
      ctx.fillStyle = "rgba(134, 240, 255, 0.55)";
      ellipse(ctx, lookX, lookY + 12, 7, 2.6);
      ctx.fill();
      ctx.restore();

      // Upper lash.
      ctx.strokeStyle = PALETTE.line;
      ctx.lineWidth = 3.5;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.ellipse(0, 0, rx, Math.max(3, ry), 0, Math.PI * 1.08, Math.PI * 1.92);
      ctx.stroke();
      // Outer lash flick.
      ctx.beginPath();
      ctx.moveTo(dir * (rx - 1), -ry * 0.22);
      ctx.lineTo(dir * (rx + 8), -ry * 0.42);
      ctx.stroke();
      ctx.restore();
    }

    if (happy) {
      ctx.fillStyle = "rgba(255, 255, 255, 0.95)";
      for (const dir of [-1, 1]) {
        const x = 210 + dir * 62;
        const y = 164;
        this._star(ctx, x, y, 4.5, 5);
        ctx.fill();
      }
    }
  }

  _drawNose(ctx) {
    ctx.strokeStyle = "rgba(214, 160, 150, 0.7)";
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(208, 202);
    ctx.quadraticCurveTo(211, 205, 214, 202);
    ctx.stroke();
  }

  _drawHairFront(ctx, t) {
    const sway = Math.sin(t * 0.9) * 2;
    // Back cap of hair.
    ctx.fillStyle = PALETTE.hairMid;
    ctx.beginPath();
    ctx.moveTo(124, 154);
    ctx.bezierCurveTo(124, 72, 172, 50, 210, 50);
    ctx.bezierCurveTo(248, 50, 296, 72, 296, 154);
    ctx.bezierCurveTo(280, 118, 254, 100, 210, 100);
    ctx.bezierCurveTo(166, 100, 140, 118, 124, 154);
    ctx.closePath();
    ctx.fill();

    // Bangs.
    const bangs = ctx.createLinearGradient(160, 90, 260, 180);
    bangs.addColorStop(0, PALETTE.hairLight);
    bangs.addColorStop(0.55, PALETTE.hairMid);
    bangs.addColorStop(1, PALETTE.hairDark);
    ctx.fillStyle = bangs;
    ctx.beginPath();
    ctx.moveTo(124, 152);
    ctx.bezierCurveTo(130, 92, 166, 66, 210, 64);
    ctx.bezierCurveTo(254, 66, 290, 92, 296, 152);
    ctx.quadraticCurveTo(276, 138, 264, 120);
    ctx.quadraticCurveTo(240, 156, 218, 168);
    ctx.quadraticCurveTo(208, 142, 198, 122);
    ctx.quadraticCurveTo(180, 156, 156, 168);
    ctx.quadraticCurveTo(146, 136, 124, 152);
    ctx.closePath();
    ctx.fill();
    ctx.strokeStyle = "rgba(59, 49, 89, 0.35)";
    ctx.lineWidth = 2;
    ctx.stroke();

    // Side locks framing the face.
    for (const dir of [-1, 1]) {
      ctx.fillStyle = dir === -1 ? PALETTE.hairMid : PALETTE.hairDark;
      ctx.beginPath();
      ctx.moveTo(210 + dir * 78, 108);
      ctx.quadraticCurveTo(210 + dir * 108, 160 + sway, 210 + dir * 98, 246);
      ctx.quadraticCurveTo(210 + dir * 82, 220, 210 + dir * 74, 176);
      ctx.closePath();
      ctx.fill();
    }

    // Ahoge.
    ctx.strokeStyle = PALETTE.hairDark;
    ctx.lineWidth = 5;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(206, 66);
    ctx.bezierCurveTo(196, 38 + sway, 226, 28, 232, 52);
    ctx.stroke();
    ctx.strokeStyle = PALETTE.hairLight;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(205, 64);
    ctx.bezierCurveTo(199, 44, 220, 36, 226, 52);
    ctx.stroke();

    // Shine.
    ctx.strokeStyle = "rgba(255, 255, 255, 0.52)";
    ctx.lineWidth = 3;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.arc(210, 122, 57, Math.PI * 1.16, Math.PI * 1.42);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(210, 122, 47, Math.PI * 1.12, Math.PI * 1.3);
    ctx.stroke();
  }

  _drawAccessories(ctx, t) {
    // Star hairpin.
    ctx.save();
    ctx.translate(270, 102);
    ctx.rotate(-0.2 + Math.sin(t * 1.2) * 0.04);
    ctx.fillStyle = PALETTE.gold;
    this._star(ctx, 0, 0, 13, 5);
    ctx.fill();
    ctx.fillStyle = "rgba(255, 255, 255, 0.75)";
    this._star(ctx, 0, 0, 6, 5);
    ctx.fill();
    ctx.restore();

    // Earrings.
    ctx.fillStyle = PALETTE.accent;
    for (const dir of [-1, 1]) {
      ellipse(ctx, 210 + dir * 92, 199, 3.5, 6);
      ctx.fill();
    }

    // Tiny sparkles around the silhouette.
    const sparkle = 0.5 + 0.5 * Math.sin(t * 2.1);
    ctx.fillStyle = `rgba(255, 220, 240, ${0.25 + sparkle * 0.35})`;
    this._star(ctx, 96, 250, 4 + sparkle * 2, 4);
    ctx.fill();
    this._star(ctx, 326, 300, 3 + sparkle * 1.5, 4);
    ctx.fill();
  }

  _star(ctx, x, y, outer, points) {
    ctx.beginPath();
    for (let i = 0; i < points * 2; i += 1) {
      const radius = i % 2 === 0 ? outer : outer * 0.44;
      const angle = (Math.PI / points) * i - Math.PI / 2;
      const px = x + Math.cos(angle) * radius;
      const py = y + Math.sin(angle) * radius;
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    }
    ctx.closePath();
  }

  _drawHearts(ctx, dt) {
    this.hearts = this.hearts.filter((heart) => heart.age < heart.ttl);
    for (const heart of this.hearts) {
      heart.age += dt;
      heart.y += heart.vy * dt;
      heart.sway += dt * 0.005;
      const progress = heart.age / heart.ttl;
      const alpha = Math.sin(Math.min(1, progress) * Math.PI) * 0.9;
      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.fillStyle = PALETTE.accent;
      heartPath(ctx, heart.x + Math.sin(heart.sway) * 8, heart.y, heart.size, Math.sin(heart.sway) * 0.2);
      ctx.fill();
      ctx.restore();
    }
  }

  _drawMouth(ctx, now) {
    const happy = this.expression === "happy";
    const sad = this.expression === "sad";
    const surprised = this.expression === "surprised";
    const thinking = this.expression === "thinking";
    let openness = this.mouth;
    if (this.speaking) {
      openness = Math.max(openness, 0.25 + 0.35 * (0.5 + 0.5 * Math.sin(now / 95)));
    }
    const x = 210;
    const y = 222;

    if (surprised) {
      ctx.fillStyle = "#7c3f57";
      ellipse(ctx, x, y, 7, 10);
      ctx.fill();
      ctx.strokeStyle = "rgba(59, 49, 89, 0.55)";
      ctx.lineWidth = 2;
      ctx.stroke();
      return;
    }
    if (happy) {
      ctx.fillStyle = "#8a405d";
      ctx.beginPath();
      ctx.moveTo(x - 13, y - 2);
      ctx.quadraticCurveTo(x, y + 17, x + 13, y - 2);
      ctx.quadraticCurveTo(x, y + 7, x - 13, y - 2);
      ctx.fill();
      ctx.fillStyle = "rgba(255, 160, 180, 0.9)";
      ctx.beginPath();
      ctx.ellipse(x, y + 7, 6, 3, 0, 0, Math.PI * 2);
      ctx.fill();
      return;
    }
    if (sad) {
      ctx.strokeStyle = "rgba(126, 73, 92, 0.9)";
      ctx.lineWidth = 3;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.arc(x, y + 7, 9, Math.PI * 1.17, Math.PI * 1.83);
      ctx.stroke();
      return;
    }
    if (thinking) {
      ctx.strokeStyle = "rgba(126, 73, 92, 0.9)";
      ctx.lineWidth = 3;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(x - 8, y + 2);
      ctx.quadraticCurveTo(x + 2, y + 5, x + 8, y + 1);
      ctx.stroke();
      return;
    }
    if (openness > 0.06) {
      const h = 5 + openness * 11;
      ctx.fillStyle = "#7c3f57";
      ellipse(ctx, x, y + 2, 8 + openness * 2, h);
      ctx.fill();
      ctx.strokeStyle = "rgba(59, 49, 89, 0.5)";
      ctx.lineWidth = 1.6;
      ctx.stroke();
      if (openness > 0.35) {
        ctx.fillStyle = "rgba(255, 143, 170, 0.85)";
        ctx.beginPath();
        ctx.ellipse(x, y + 2 + h * 0.45, 4.5, 2.6, 0, 0, Math.PI * 2);
        ctx.fill();
      }
      return;
    }
    ctx.strokeStyle = "rgba(126, 73, 92, 0.85)";
    ctx.lineWidth = 2.6;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(x - 7, y);
    ctx.quadraticCurveTo(x, y + 5.5, x + 7, y);
    ctx.stroke();
  }
}

export { SIZE };
