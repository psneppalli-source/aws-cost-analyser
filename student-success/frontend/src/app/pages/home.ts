import { AfterViewInit, Component, ElementRef, OnDestroy, viewChild } from '@angular/core';
import { RouterLink } from '@angular/router';

interface P3 { x: number; y: number; z: number; c: string; r: number; }

/**
 * Public home page: a 3D network of students (canvas, no libraries) behind the headline, floating 3D preview
 * cards that follow the pointer, and the main features. Still for people who prefer reduced motion.
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

    .stage{position:relative;height:460px;perspective:1100px}
    .float{position:absolute;border-radius:18px;padding:16px 18px;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.14);
      backdrop-filter:blur(10px);box-shadow:0 30px 60px rgba(0,0,0,.35);transform-style:preserve-3d;transition:transform .25s ease-out}
    .f1{left:6%;top:10%;width:280px;animation:bob 7s ease-in-out infinite}
    .f2{right:2%;top:42%;width:250px;animation:bob 8s ease-in-out -2s infinite}
    .f3{left:16%;bottom:2%;width:270px;animation:bob 9s ease-in-out -4s infinite}
    @keyframes bob{0%,100%{translate:0 0}50%{translate:0 -12px}}
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
      .stage{height:auto;perspective:none;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
      .float{position:static;width:auto;transform:none !important;animation:none}
      .f3{grid-column:1 / -1}
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

  /** A slowly turning sphere of students (points coloured by band) with links between near neighbours. */
  private draw() {
    const canvas = this.cv().nativeElement;
    const ctx = canvas.getContext('2d'); if (!ctx) return;
    const colours = ['#7fe0dc', '#7fe0dc', '#5aa9ff', '#5aa9ff', '#ffc04d', '#ff7a6e'];
    const N = 260, pts: P3[] = [];
    for (let i = 0; i < N; i++) {  // Fibonacci sphere: evenly spread points
      const y = 1 - (i / (N - 1)) * 2, rad = Math.sqrt(1 - y * y), th = Math.PI * (3 - Math.sqrt(5)) * i;
      pts.push({ x: Math.cos(th) * rad, y, z: Math.sin(th) * rad, c: colours[i % colours.length], r: 1.2 + (i % 3) * 0.6 });
    }
    const near: [number, number][] = [];
    for (let i = 0; i < N; i++) for (let j = i + 1; j < N; j++) {
      const d = (pts[i].x - pts[j].x) ** 2 + (pts[i].y - pts[j].y) ** 2 + (pts[i].z - pts[j].z) ** 2;
      if (d < 0.045) near.push([i, j]);
    }
    let a = 0, b = 0.35;
    const frame = () => {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const w = canvas.clientWidth, h = canvas.clientHeight;
      if (canvas.width !== w * dpr || canvas.height !== h * dpr) { canvas.width = w * dpr; canvas.height = h * dpr; }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
      const narrow = w < 900;  // phones and tablets: a smaller, dimmer globe above the text so it stays readable
      const R = narrow ? Math.min(w * 0.42, 260) : Math.min(w, h) * 0.36, cx = narrow ? w * 0.78 : w * 0.70, cy = narrow ? Math.min(h * 0.2, 220) : h * 0.52;
      const dim = narrow ? 0.3 : 1;
      a += this.reduce ? 0 : 0.0022; b += ((0.35 + this.my * 0.5) - b) * 0.04;
      const ay = a + this.mx * 0.6, ca = Math.cos(ay), sa = Math.sin(ay), cb = Math.cos(b), sb = Math.sin(b);
      const proj = pts.map((p) => {
        const x1 = p.x * ca - p.z * sa, z1 = p.x * sa + p.z * ca;
        const y2 = p.y * cb - z1 * sb, z2 = p.y * sb + z1 * cb;
        const s = 2.4 / (2.4 + z2);
        return { x: cx + x1 * R * s, y: cy + y2 * R * s, z: z2, s };
      });
      ctx.lineWidth = 0.6;
      for (const [i, j] of near) {
        const p = proj[i], q = proj[j], depth = (2 - (p.z + q.z) / 2) / 3;
        ctx.strokeStyle = `rgba(127,224,220,${((0.05 + depth * 0.22) * dim).toFixed(3)})`;
        ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y); ctx.stroke();
      }
      proj.map((p, i) => ({ ...p, i })).sort((u, v) => v.z - u.z).forEach((p) => {
        const alpha = 0.35 + (1 - (p.z + 1) / 2) * 0.65;
        ctx.globalAlpha = alpha * dim; ctx.fillStyle = pts[p.i].c;
        ctx.beginPath(); ctx.arc(p.x, p.y, pts[p.i].r * p.s * 1.6, 0, Math.PI * 2); ctx.fill();
      });
      ctx.globalAlpha = 1;
      if (!this.reduce) this.raf = requestAnimationFrame(frame);
    };
    frame();
  }
}
