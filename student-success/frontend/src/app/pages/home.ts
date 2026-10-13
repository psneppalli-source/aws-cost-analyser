import { AfterViewInit, Component, ElementRef, OnDestroy, viewChild } from '@angular/core';
import { RouterLink } from '@angular/router';

/**
 * Public home page: a human head in light with an AI brain inside (canvas, no libraries), preview cards that tilt
 * with the pointer, and the main features. Still for people who prefer reduced motion.
 */
@Component({
  selector: 'app-home-page',
  imports: [RouterLink],
  styles: [`
    :host{display:block;background:#07131f;color:#e8f1f8;min-height:100vh;overflow-x:hidden}
    .nav{position:fixed;inset:0 0 auto 0;z-index:20;display:flex;align-items:center;gap:14px;padding:14px clamp(16px,4vw,48px);
      background:linear-gradient(180deg,rgba(7,19,31,.85),rgba(7,19,31,0));backdrop-filter:blur(4px)}
    .logo{display:flex;align-items:center;gap:10px;font-weight:700;color:#fff;text-decoration:none}
    .mark{width:38px;height:38px;border-radius:11px;display:grid;place-items:center;color:#07131f;font-weight:800;
      background:linear-gradient(135deg,#7fe0dc,#14a3a3);box-shadow:0 6px 20px rgba(20,163,163,.5)}
    .nav .sp{flex:1} .nav a.link{color:#b8c8d8;text-decoration:none;font-size:14px} .nav a.link:hover{color:#fff}
    .btn-l{display:inline-flex;align-items:center;gap:8px;border-radius:12px;padding:10px 18px;font-weight:600;text-decoration:none;font-size:15px;transition:transform .15s,box-shadow .15s}
    .btn-l.primary{color:#fff;background:linear-gradient(135deg,#14a3a3,#0b6e6e);box-shadow:0 10px 28px rgba(20,163,163,.35)}
    .btn-l.primary:hover{transform:translateY(-2px);box-shadow:0 14px 34px rgba(20,163,163,.45)}
    .btn-l.ghost{color:#e8f1f8;border:1px solid rgba(255,255,255,.22);background:rgba(255,255,255,.04)}
    .btn-l.ghost:hover{background:rgba(255,255,255,.1)}

    .hero{position:relative;min-height:100vh;min-height:100svh;display:grid;align-items:center;padding:110px clamp(16px,5vw,64px) 60px;
      background:radial-gradient(1000px 600px at 75% 40%,rgba(20,163,163,.18),transparent 60%),radial-gradient(800px 600px at 10% 90%,rgba(111,91,214,.16),transparent 60%)}
    canvas{position:absolute;inset:0;width:100%;height:100%;display:block}
    .hero-grid{position:relative;z-index:2;display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,1fr);gap:40px;align-items:center;max-width:1240px;margin:0 auto;width:100%}
    .eyebrow{display:inline-flex;align-items:center;gap:8px;font-size:13px;font-weight:600;color:#7fe0dc;background:rgba(127,224,220,.1);
      border:1px solid rgba(127,224,220,.25);border-radius:999px;padding:5px 12px;margin-bottom:18px}
    h1{font-size:clamp(34px,5.2vw,64px);line-height:1.05;margin:0 0 18px;letter-spacing:-.03em;color:#fff}
    h1 span{background:linear-gradient(90deg,#7fe0dc,#a9b8ff);-webkit-background-clip:text;background-clip:text;color:transparent}
    .lede{font-size:clamp(16px,1.6vw,19px);line-height:1.6;color:#b8c8d8;max-width:560px;margin:0 0 28px}
    .ctas{display:flex;gap:12px;flex-wrap:wrap} .trust{display:flex;gap:18px;flex-wrap:wrap;margin-top:26px;color:#8ea4bf;font-size:13px}
    .trust span{display:inline-flex;align-items:center;gap:6px}

    .stage{position:relative;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;perspective:1100px}
    .float{position:relative;border-radius:18px;padding:16px 18px;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.14);
      backdrop-filter:blur(10px);box-shadow:0 30px 60px rgba(0,0,0,.35);transform-style:preserve-3d;transition:transform .25s ease-out}
    .f1{animation:bob 7s ease-in-out infinite} .f2{animation:bob 8s ease-in-out -2s infinite}
    .f3{grid-column:1 / -1;animation:bob 9s ease-in-out -4s infinite}
    @keyframes bob{0%,100%{translate:0 0}50%{translate:0 -12px}}
    .brain-slot{grid-column:1 / -1;height:clamp(300px,52vh,440px)}
    .k{font-size:12px;color:#9fb4c9} .big{font-size:40px;font-weight:700;color:#fff;letter-spacing:-.02em} .up{color:#7fe0a0;font-size:13px;font-weight:600}
    .pill{display:inline-block;font-size:11.5px;padding:2px 9px;border-radius:999px;margin:6px 6px 0 0;background:rgba(127,224,220,.16);color:#bdeeea}
    .pill.red{background:rgba(255,120,110,.16);color:#ffb3ab}
    .row3{display:flex;align-items:center;gap:10px}
    .dot{width:10px;height:10px;border-radius:50%} .bar{height:6px;border-radius:4px;background:rgba(255,255,255,.12);overflow:hidden;margin-top:6px}
    .bar i{display:block;height:100%;border-radius:4px}
    .ai-line{font-size:13px;color:#d6e2ee;margin:6px 0 0;line-height:1.45}

    section.block{padding:84px clamp(16px,5vw,64px);max-width:1240px;margin:0 auto}
    .sec-h{text-align:center;max-width:680px;margin:0 auto 40px} .sec-h h2{font-size:clamp(26px,3vw,38px);margin:0 0 10px;color:#fff;letter-spacing:-.02em}
    .sec-h p{color:#9fb4c9;margin:0;font-size:16px}
    .features{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:18px}
    .feat{border-radius:18px;padding:22px;background:linear-gradient(180deg,rgba(255,255,255,.06),rgba(255,255,255,.02));border:1px solid rgba(255,255,255,.1);
      transition:transform .2s,border-color .2s} .feat:hover{transform:translateY(-4px);border-color:rgba(127,224,220,.4)}
    .ic{width:44px;height:44px;border-radius:12px;display:grid;place-items:center;margin-bottom:14px;color:#7fe0dc;background:rgba(127,224,220,.12)}
    .feat h3{margin:0 0 6px;color:#fff;font-size:17px} .feat p{margin:0;color:#9fb4c9;font-size:14.5px;line-height:1.55}
    .steps{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;counter-reset:s}
    .step{position:relative;padding:22px 22px 22px 70px;border-radius:18px;background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.08)}
    .step::before{counter-increment:s;content:counter(s);position:absolute;left:20px;top:20px;width:34px;height:34px;border-radius:10px;display:grid;place-items:center;
      font-weight:700;color:#07131f;background:linear-gradient(135deg,#7fe0dc,#14a3a3)}
    .step h3{margin:0 0 4px;color:#fff;font-size:16px} .step p{margin:0;color:#9fb4c9;font-size:14px}
    .cta{margin:0 clamp(16px,5vw,64px) 70px;max-width:1100px;border-radius:24px;padding:40px clamp(20px,4vw,48px);display:flex;align-items:center;gap:24px;flex-wrap:wrap;
      background:linear-gradient(135deg,rgba(20,163,163,.25),rgba(111,91,214,.22));border:1px solid rgba(255,255,255,.12)}
    .cta h2{margin:0 0 6px;color:#fff;font-size:26px} .cta p{margin:0;color:#c9d6e6} .cta .sp{flex:1}
    footer{text-align:center;color:#6f86a0;font-size:13px;padding:0 16px 40px}
    .reveal{opacity:0;transform:translateY(24px);transition:opacity .7s ease,transform .7s ease} .reveal.in{opacity:1;transform:none}
    .btn-l{white-space:nowrap} .logo{white-space:nowrap}
    @media (min-width:1164px){ .cta{margin-inline:auto} }
    /* tablets and phones: the preview cards sit in the page flow (no 3D float) so nothing overlaps or leaves gaps */
    @media (max-width:900px){
      .hero{min-height:auto;padding-top:104px;padding-bottom:56px} .hero-grid{grid-template-columns:1fr;gap:32px}
      .nav a.link{display:none} .nav{background:rgba(7,19,31,.88);backdrop-filter:blur(10px)}
      .stage{perspective:none}
      .float{transform:none !important;animation:none}
      .brain-slot{height:clamp(240px,52vw,340px)}
      .steps{grid-template-columns:1fr}
      section.block{padding-top:56px;padding-bottom:56px}
    }
    @media (max-width:600px){
      .stage{grid-template-columns:1fr} .f3{grid-column:auto}
      .nav .ghost{display:none} .nav{padding:10px 16px} .mark{width:34px;height:34px}
      .eyebrow{font-size:12px} .lede{font-size:15.5px}
      .ctas{flex-direction:column} .ctas .btn-l{justify-content:center;white-space:normal;text-align:center}
      .trust{gap:8px 14px}
      .big{font-size:34px}
      .cta{padding:28px 20px;flex-direction:column;align-items:stretch;text-align:left} .cta .sp{display:none}
      .cta .btn-l{justify-content:center} .cta h2{font-size:22px}
      .sec-h{margin-bottom:28px} .feat{padding:18px} .step{padding:18px 18px 18px 64px} .step::before{left:16px;top:18px}
    }
    @media (max-width:360px){ .btn-l{padding:9px 12px;font-size:14px} h1{font-size:30px} }
    @media (prefers-reduced-motion: reduce){ .float{animation:none} .reveal{opacity:1;transform:none;transition:none} }
  `],
  template: `
    <header class="nav">
      <a class="logo" routerLink="/home"><span class="mark">SC</span>Smart Campus</a>
      <span class="sp"></span>
      <a class="link" href="#features">Features</a><a class="link" href="#how">How it works</a>
      <a class="btn-l ghost" routerLink="/register">Create account</a>
      <a class="btn-l primary" routerLink="/login">Sign in</a>
    </header>

    <section class="hero" (pointermove)="tilt($event)" (pointerleave)="tilt(null)">
      <canvas #cv aria-hidden="true"></canvas>
      <div class="hero-grid">
        <div>
          <span class="eyebrow">✨ Student success, powered by clear data and helpful AI</span>
          <h1>See every student's progress, <span>and act early.</span></h1>
          <p class="lede">Marks, attendance, skills and placement readiness come together in one Success Score. Mentors see who needs support,
            students see how to improve, and AI turns the figures into plain-language next steps.</p>
          <div class="ctas">
            <a class="btn-l primary" routerLink="/login">Sign in
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg></a>
            <a class="btn-l ghost" routerLink="/register">New student? Create your account</a>
          </div>
          <div class="trust"><span>🔒 Two-step sign-in</span><span>👥 Role-based access</span><span>🛡️ No names sent to AI</span></div>
        </div>
        <div class="stage" aria-hidden="true">
          <div class="brain-slot" #slot></div>
          <div class="float f1" [style.transform]="t(1)">
            <div class="k">Success Score · Sep 2026</div>
            <div class="row3"><span class="big">72.4</span><span class="up">▲ +6.2 since April</span></div>
            <span class="pill">On track</span><span class="pill">Complete data</span>
            <div class="bar"><i style="width:72%;background:linear-gradient(90deg,#14a3a3,#7fe0dc)"></i></div>
          </div>
          <div class="float f2" [style.transform]="t(2)">
            <div class="k">Early warning</div>
            <div class="row3" style="margin-top:6px"><span class="dot" style="background:#ff7a6e"></span><strong style="color:#fff">Attendance fell 18 points</strong></div>
            <div class="row3" style="margin-top:6px"><span class="dot" style="background:#ffc04d"></span><span style="color:#d6e2ee">Coding score below 55</span></div>
            <span class="pill red">Support plan suggested</span>
          </div>
          <div class="float f3" [style.transform]="t(3)">
            <div class="k">✨ AI assistant</div>
            <p class="ai-line"><strong style="color:#fff">Your weekly plan:</strong> practise coding 3 × 20 minutes, submit the 2 open assignments,
              and book 15 minutes with your mentor.</p>
          </div>
        </div>
      </div>
    </section>

    <section class="block" id="features">
      <div class="sec-h reveal"><h2>Everything a college needs to support students</h2>
        <p>One platform for staff and students, with each person seeing only what their role allows.</p></div>
      <div class="features">
        @for (f of features; track f.t) {
          <article class="feat reveal"><div class="ic" aria-hidden="true"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path [attr.d]="f.i"/></svg></div><h3>{{ f.t }}</h3><p>{{ f.d }}</p></article>
        }
      </div>
    </section>

    <section class="block" id="how">
      <div class="sec-h reveal"><h2>How it works</h2><p>From records to action in three steps.</p></div>
      <div class="steps">
        <div class="step reveal"><h3>Bring the data together</h3><p>Staff enter or import marks, attendance, LMS activity, skills and placement results.</p></div>
        <div class="step reveal"><h3>See who needs support</h3><p>Transparent rules score each student and flag early warnings, with the reasons shown.</p></div>
        <div class="step reveal"><h3>Act and follow up</h3><p>Mentors agree support plans, record outcomes, and students get a clear weekly plan.</p></div>
      </div>
    </section>

    <div class="cta reveal">
      <div><h2>Ready to begin?</h2><p>Staff accounts are created by your College Administrator. Students can register with their student ID and date of birth.</p></div>
      <span class="sp"></span>
      <a class="btn-l ghost" routerLink="/register">Create account</a>
      <a class="btn-l primary" routerLink="/login">Sign in</a>
    </div>
    <footer>© {{ year }} Smart Campus · Student success analytics</footer>
  `,
})
export class HomePage implements AfterViewInit, OnDestroy {
  private cv = viewChild.required<ElementRef<HTMLCanvasElement>>('cv');
  private slot = viewChild.required<ElementRef<HTMLElement>>('slot');
  private raf = 0;
  private io?: IntersectionObserver;
  private mx = 0; private my = 0;
  private tx = 0; private ty = 0;
  year = new Date().getFullYear();
  reduce = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  features = [
    { t: 'One Success Score', d: 'Academic results, attendance, LMS activity, skills, engagement and placement readiness in one transparent score.',
      i: 'M3 3v18h18M7 15l4-4 3 3 6-6' },
    { t: 'Early warning', d: 'Clear, rules-based flags with the evidence behind them, so support reaches students before results slip.',
      i: 'M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0zM12 9v4M12 17h.01' },
    { t: 'AI assistant', d: 'Plain-language summaries, meeting briefs, support-plan drafts and weekly plans. People always check and decide.',
      i: 'M12 2l1.9 5.6L19.5 9.5l-5.6 1.9L12 17l-1.9-5.6L4.5 9.5l5.6-1.9z' },
    { t: 'Private and secure', d: 'Two-step sign-in, role-based access checked on every request, and a full audit history.',
      i: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z' },
  ];

  t(n: number) {
    const k = [0, 1, 0.7, 0.5][n];
    return `rotateY(${(-8 + this.tx * 14 * k).toFixed(2)}deg) rotateX(${(6 - this.ty * 10 * k).toFixed(2)}deg) translateZ(${n * 10}px)`;
  }
  tilt(e: PointerEvent | null) {
    if (!e) { this.tx = this.ty = 0; this.mx = this.my = 0; return; }
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    this.tx = (e.clientX - r.left) / r.width - 0.5; this.ty = (e.clientY - r.top) / r.height - 0.5;
    this.mx = this.tx; this.my = this.ty;
  }

  ngAfterViewInit() {
    this.io = new IntersectionObserver((es) => es.forEach((x) => x.isIntersecting && x.target.classList.add('in')), { threshold: 0.12 });
    document.querySelectorAll('app-home-page .reveal').forEach((el) => this.io!.observe(el));
    this.draw();
  }
  ngOnDestroy() { cancelAnimationFrame(this.raf); this.io?.disconnect(); }

  /**
   * A human head in profile, drawn in light, with an AI brain inside: the head is filled with points, the brain's
   * links fire signals, circuit lines carry signals in from an "AI" chip, and a scan line sweeps across the face.
   * Coordinates are in a unit box (x 0..1, y 0..1.2) with the face looking right; it is mirrored to look at the text.
   */
  private draw() {
    const canvas = this.cv().nativeElement;
    const ctx = canvas.getContext('2d'); if (!ctx) return;
    type V = [number, number];
    const head: V[][] = [  // start point, then cubic Bezier segments [c1, c2, end]
      [[0.33, 1.18]],
      [[0.33, 1.05], [0.30, 0.98], [0.24, 0.90]], [[0.10, 0.80], [0.06, 0.62], [0.08, 0.46]],
      [[0.10, 0.20], [0.30, 0.04], [0.52, 0.05]], [[0.72, 0.06], [0.84, 0.18], [0.85, 0.36]],
      [[0.86, 0.40], [0.88, 0.42], [0.87, 0.45]], [[0.86, 0.48], [0.88, 0.52], [0.93, 0.58]],
      [[0.95, 0.61], [0.93, 0.64], [0.88, 0.64]], [[0.87, 0.66], [0.90, 0.69], [0.89, 0.71]],
      [[0.88, 0.73], [0.86, 0.73], [0.87, 0.75]], [[0.89, 0.77], [0.88, 0.80], [0.85, 0.81]],
      [[0.84, 0.84], [0.86, 0.88], [0.82, 0.91]], [[0.76, 0.95], [0.68, 0.93], [0.64, 0.95]],
      [[0.62, 1.02], [0.63, 1.10], [0.64, 1.18]],
    ];
    const trace = (c: CanvasRenderingContext2D, m: (p: V) => V) => {
      c.beginPath(); c.moveTo(...m(head[0][0]));
      for (const seg of head.slice(1)) c.bezierCurveTo(...m(seg[0]), ...m(seg[1]), ...m(seg[2]));
      c.closePath();
    };
    // points that fill the head (sampled once on a small offscreen canvas)
    const off = document.createElement('canvas').getContext('2d');
    const fill: V[] = [];
    const brainC: V = [0.41, 0.33], brainR: V = [0.25, 0.2];
    const inBrain = (x: number, y: number) => ((x - brainC[0]) / brainR[0]) ** 2 + ((y - brainC[1]) / brainR[1]) ** 2 < 1;
    if (off) {
      trace(off, (p) => [p[0] * 1000, p[1] * 1000]);
      for (let y = 0.02; y < 1.18; y += 0.021) for (let x = 0.04; x < 0.98; x += 0.021) {
        const jx = x + (Math.sin(x * 91 + y * 37) * 0.5) * 0.012, jy = y + (Math.cos(x * 53 - y * 71) * 0.5) * 0.012;
        if (off.isPointInPath(jx * 1000, jy * 1000) && !inBrain(jx, jy)) fill.push([jx, jy]);
      }
    }
    // the brain: points in a folded oval, linked to near neighbours
    const brain: V[] = [];
    for (let i = 0; i < 170; i++) {
      const r = Math.sqrt((i + 0.5) / 170), t = i * Math.PI * (3 - Math.sqrt(5));
      brain.push([brainC[0] + Math.cos(t) * r * brainR[0] * 0.95, brainC[1] + Math.sin(t) * r * brainR[1] * 0.95]);
    }
    const links: [number, number][] = [], adj: number[][] = brain.map(() => []);
    for (let i = 0; i < brain.length; i++) for (let j = i + 1; j < brain.length; j++) {
      if ((brain[i][0] - brain[j][0]) ** 2 + (brain[i][1] - brain[j][1]) ** 2 < 0.0019) { adj[i].push(links.length); adj[j].push(links.length); links.push([i, j]); }
    }
    const glow = new Float32Array(brain.length);
    // circuit lines from outside the head into the brain; the middle one starts at the AI chip
    const circuits: V[][] = [
      [[0.03, 0.17], [0.20, 0.17], [0.20, 0.26], [0.30, 0.26]],
      [[-0.13, 0.40], [0.06, 0.40], [0.20, 0.40], [0.27, 0.36]],
      [[0.01, 0.62], [0.17, 0.62], [0.17, 0.47], [0.30, 0.45]],
      [[0.26, -0.03], [0.44, -0.03], [0.44, 0.16]],
      [[0.62, -0.02], [0.56, 0.06], [0.52, 0.16]],
    ];
    const lens = circuits.map((c) => c.slice(1).reduce((s, p, i) => s + Math.hypot(p[0] - c[i][0], p[1] - c[i][1]), 0));
    const along = (c: number, f: number): V => {  // a point a fraction f of the way along circuit c
      let d = f * lens[c]; const pts = circuits[c];
      for (let i = 1; i < pts.length; i++) {
        const l = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
        if (d <= l) return [pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * d / l, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * d / l];
        d -= l;
      }
      return pts[pts.length - 1];
    };
    const wires = circuits.map((_, c) => ({ c, f: Math.random() }));
    type Pulse = { l: number; from: number; t: number; hops: number; c: string };
    const colours = ['#7fe0dc', '#a9b8ff', '#ffffff', '#ffc04d'];
    const nearest = (p: V) => brain.reduce((best, q, i) => ((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2 < (brain[best][0] - p[0]) ** 2 + (brain[best][1] - p[1]) ** 2 ? i : best), 0);
    const ends = circuits.map((c) => nearest(c[c.length - 1]));
    const spawn = (at?: number): Pulse => {
      const node = at ?? (Math.random() * brain.length) | 0, ls = adj[node];
      const l = ls.length ? ls[(Math.random() * ls.length) | 0] : (Math.random() * links.length) | 0;
      return { l, from: links[l][0] === node || !ls.length ? links[l][0] : links[l][1], t: 0, hops: 5 + ((Math.random() * 8) | 0), c: colours[(Math.random() * colours.length) | 0] };
    };
    const pulses: Pulse[] = links.length ? Array.from({ length: 22 }, () => spawn()) : [];
    let clock = 0;
    const frame = () => {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const w = canvas.clientWidth, h = canvas.clientHeight;
      if (canvas.width !== w * dpr || canvas.height !== h * dpr) { canvas.width = w * dpr; canvas.height = h * dpr; }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
      // the head is drawn over its own space in the page, above the preview cards
      const cr = canvas.getBoundingClientRect(), sr = this.slot().nativeElement.getBoundingClientRect();
      const S = Math.min(sr.height / 1.25, sr.width / 1.3);
      const cx = sr.left - cr.left + sr.width / 2 - S * 0.12, cy = sr.top - cr.top + sr.height / 2 + S * 0.04;
      clock += this.reduce ? 0 : 1;
      const bob = Math.sin(clock * 0.02) * 4, k = Math.max(0.6, Math.min(1, S / 420));
      // mirror so the face looks left, towards the headline; inner layers move a little more with the pointer (depth)
      const at = (p: V, depth = 0): V => [cx + (0.5 - p[0]) * S + this.mx * depth * 14, cy + (p[1] - 0.6) * S + bob + this.my * depth * 10];
      // soft glow behind the head
      const gc = at(brainC, 1), g = ctx.createRadialGradient(gc[0], gc[1], 0, gc[0], gc[1], S * 0.7);
      g.addColorStop(0, 'rgba(20,163,163,0.20)'); g.addColorStop(1, 'rgba(20,163,163,0)');
      ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
      // head: points, then the outline drawn in light
      const scan = 0.35 + ((clock * 0.004) % 1) * 0.75;               // the scan line moves from the back of the head to the face
      for (const p of fill) {
        const near = Math.max(0, 1 - Math.abs(p[0] - scan) / 0.05);
        const q = at(p, 0.3); ctx.globalAlpha = (0.22 + near * 0.6) * Math.min(1, (1.18 - p[1]) / 0.22); ctx.fillStyle = near > 0.2 ? '#ffffff' : '#5aa9ff';
        ctx.beginPath(); ctx.arc(q[0], q[1], (1 + near * 0.8) * k, 0, Math.PI * 2); ctx.fill();
      }
      ctx.globalAlpha = 1;
      ctx.save(); ctx.shadowColor = 'rgba(127,224,220,0.9)'; ctx.shadowBlur = 14 * k;
      const n0 = at([0.5, 0.9]), n1 = at([0.5, 1.18]), ng = ctx.createLinearGradient(n0[0], n0[1], n1[0], n1[1]);  // the neck fades out
      ng.addColorStop(0, 'rgba(127,224,220,0.95)'); ng.addColorStop(1, 'rgba(127,224,220,0)');
      ctx.strokeStyle = ng; ctx.lineWidth = 2 * k; trace(ctx, (p) => at(p)); ctx.stroke(); ctx.restore();
      // eye and ear
      ctx.strokeStyle = 'rgba(127,224,220,0.7)'; ctx.lineWidth = 1.4 * k;
      const e1 = at([0.74, 0.46]), e2 = at([0.80, 0.47]), em = at([0.77, 0.445]), en = at([0.77, 0.485]);
      ctx.beginPath(); ctx.moveTo(...e1); ctx.quadraticCurveTo(em[0], em[1], e2[0], e2[1]); ctx.quadraticCurveTo(en[0], en[1], e1[0], e1[1]); ctx.stroke();
      const r1 = at([0.44, 0.50]), r2 = at([0.36, 0.52]), r3 = at([0.37, 0.64]), r4 = at([0.44, 0.63]);
      ctx.beginPath(); ctx.moveTo(...r1); ctx.bezierCurveTo(r2[0], r2[1], r3[0], r3[1], r4[0], r4[1]); ctx.stroke();
      // scan line
      const s1 = at([scan, 0.02], 0.3), s2 = at([scan, 1.16], 0.3), sg = ctx.createLinearGradient(s1[0], s1[1], s2[0], s2[1]);
      sg.addColorStop(0, 'rgba(127,224,220,0)'); sg.addColorStop(0.5, 'rgba(127,224,220,0.35)'); sg.addColorStop(1, 'rgba(127,224,220,0)');
      ctx.strokeStyle = sg; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.moveTo(...s1); ctx.lineTo(...s2); ctx.stroke();
      // circuit lines and the AI chip
      ctx.lineWidth = 1.6 * k; ctx.strokeStyle = 'rgba(169,184,255,0.55)';
      for (const c of circuits) { ctx.beginPath(); c.forEach((p, i) => (i ? ctx.lineTo(...at(p, 1)) : ctx.moveTo(...at(p, 1)))); ctx.stroke(); }
      ctx.fillStyle = '#a9b8ff';
      for (const c of circuits) { const q = at(c[0], 1); ctx.beginPath(); ctx.arc(q[0], q[1], 3.2 * k, 0, Math.PI * 2); ctx.fill(); }
      const chip = at([-0.2, 0.40], 1), cs = 0.13 * S;
      ctx.save(); ctx.shadowColor = 'rgba(111,91,214,0.9)'; ctx.shadowBlur = 18 * k;
      ctx.fillStyle = '#16233a'; ctx.strokeStyle = '#a9b8ff'; ctx.lineWidth = 1.6 * k;
      ctx.beginPath(); ctx.roundRect(chip[0] - cs / 2, chip[1] - cs / 2, cs, cs, cs * 0.18); ctx.fill(); ctx.stroke(); ctx.restore();
      ctx.strokeStyle = 'rgba(169,184,255,0.7)'; ctx.lineWidth = 1.2 * k;
      for (let i = -1; i <= 1; i++) for (const [dx, dy] of [[0, -1], [0, 1], [-1, 0]] as V[]) {
        const o = i * cs * 0.28, ax = chip[0] + (dx ? dx * cs / 2 : o), ay = chip[1] + (dy ? dy * cs / 2 : o);
        ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(ax + dx * cs * 0.16, ay + dy * cs * 0.16); ctx.stroke();
      }
      ctx.fillStyle = '#e8f1f8'; ctx.font = `700 ${Math.round(cs * 0.42)}px Inter, system-ui, sans-serif`;
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('AI', chip[0], chip[1] + 1);
      // signals running along the circuits into the brain
      ctx.globalCompositeOperation = 'lighter';
      for (const wv of wires) {
        const q = at(along(wv.c, wv.f), 1);
        ctx.globalAlpha = 0.95; ctx.fillStyle = '#ffffff'; ctx.beginPath(); ctx.arc(q[0], q[1], 2.4 * k, 0, Math.PI * 2); ctx.fill();
        ctx.globalAlpha = 0.3; ctx.fillStyle = '#a9b8ff'; ctx.beginPath(); ctx.arc(q[0], q[1], 7 * k, 0, Math.PI * 2); ctx.fill();
        if (!this.reduce) wv.f += 0.006 + wv.c * 0.0008;
        if (wv.f >= 1) { wv.f = 0; glow[ends[wv.c]] = 1; if (pulses.length) pulses[(Math.random() * pulses.length) | 0] = spawn(ends[wv.c]); }
      }
      ctx.globalCompositeOperation = 'source-over';
      // brain: folded outline, links, points, firing signals
      ctx.strokeStyle = 'rgba(199,155,255,0.55)'; ctx.lineWidth = 1.3 * k; ctx.beginPath();
      for (let i = 0; i <= 120; i++) {
        const t = (i / 120) * Math.PI * 2, r = 1 + 0.06 * Math.sin(t * 11);
        const q = at([brainC[0] + Math.cos(t) * brainR[0] * r, brainC[1] + Math.sin(t) * brainR[1] * r], 1);
        if (i) ctx.lineTo(...q); else ctx.moveTo(...q);
      }
      ctx.stroke();
      ctx.lineWidth = 0.7; ctx.strokeStyle = 'rgba(127,224,220,0.22)';
      for (const [i, j] of links) { ctx.beginPath(); ctx.moveTo(...at(brain[i], 1)); ctx.lineTo(...at(brain[j], 1)); ctx.stroke(); }
      for (let i = 0; i < brain.length; i++) {
        glow[i] *= 0.93; const q = at(brain[i], 1);
        ctx.globalAlpha = 0.55 + glow[i] * 0.45; ctx.fillStyle = i % 4 ? '#7fe0dc' : '#c79bff';
        ctx.beginPath(); ctx.arc(q[0], q[1], (1.7 + glow[i] * 2.6) * k, 0, Math.PI * 2); ctx.fill();
      }
      ctx.globalCompositeOperation = 'lighter';
      for (let n = 0; n < pulses.length; n++) {
        const pl = pulses[n], [i, j] = links[pl.l], to = pl.from === i ? j : i;
        const a = at(brain[pl.from], 1), b = at(brain[to], 1), x = a[0] + (b[0] - a[0]) * pl.t, y = a[1] + (b[1] - a[1]) * pl.t;
        ctx.globalAlpha = 0.95; ctx.fillStyle = pl.c; ctx.beginPath(); ctx.arc(x, y, 2.2 * k, 0, Math.PI * 2); ctx.fill();
        ctx.globalAlpha = 0.25; ctx.beginPath(); ctx.arc(x, y, 6 * k, 0, Math.PI * 2); ctx.fill();
        if (!this.reduce) pl.t += 0.07;
        if (pl.t >= 1) {
          glow[to] = 1;
          const next = adj[to].filter((l) => l !== pl.l);
          if (--pl.hops <= 0 || !next.length) pulses[n] = spawn();
          else { pl.l = next[(Math.random() * next.length) | 0]; pl.from = to; pl.t = 0; }
        }
      }
      ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1;
      if (!this.reduce) this.raf = requestAnimationFrame(frame);
    };
    frame();
  }
}
