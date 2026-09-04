<template>
  <div class="immersive-backdrop" aria-hidden="true">
    <div class="immersive-backdrop__wash"></div>
    <div class="immersive-backdrop__word"><span>LEARN</span><span>MATE</span></div>
  </div>
</template>

<style>
.immersive-backdrop { position: absolute; inset: 0; z-index: -3; overflow: hidden; pointer-events: none; background: #1e3c34; }
.immersive-backdrop::before { content: ""; position: absolute; inset: 0; background: linear-gradient(120deg, rgba(3, 18, 13, .86) 0%, rgba(28, 68, 53, .68) 34%, rgba(5, 24, 17, .92) 68%, rgba(53, 93, 69, .56) 100%), radial-gradient(ellipse 80% 68% at 8% 92%, rgba(151, 184, 137, .5), transparent 66%), radial-gradient(ellipse 62% 62% at 92% 8%, rgba(2, 13, 10, .92), transparent 70%), #1e3c34; background-size: 180% 180%, 100% 100%, 100% 100%, 100% 100%; animation: immersiveMetalShift 18s ease-in-out infinite alternate; }
.immersive-backdrop::after { content: ""; position: absolute; inset: -30%; background: linear-gradient(112deg, transparent 30%, rgba(216, 239, 187, .08) 44%, rgba(255, 255, 255, .14) 48%, rgba(216, 239, 187, .04) 54%, transparent 68%); transform: translate3d(-18%, 0, 0) rotate(-3deg); animation: immersiveMetalSheen 14s ease-in-out infinite alternate; }
.immersive-backdrop__wash { position: absolute; inset: -18%; opacity: .62; filter: blur(96px); background: radial-gradient(ellipse at 35% 30%, rgba(209, 239, 148, .34), transparent 46%), radial-gradient(ellipse at 72% 72%, rgba(82, 147, 104, .38), transparent 52%); animation: immersiveWashDrift 12s ease-in-out infinite alternate; }
.immersive-backdrop__word { position: absolute; inset: 8% 0 0; display: grid; align-content: center; justify-items: center; color: rgba(173, 198, 178, .28); font-family: Georgia, "Times New Roman", serif; font-size: clamp(116px, 17.5vw, 282px); font-weight: 400; letter-spacing: -.045em; line-height: .76; user-select: none; }
.immersive-backdrop__word span { display: block; transform: scaleX(1.08); }
@keyframes immersiveWashDrift { from { transform: translate3d(-3%, -2%, 0) scale(.98); } to { transform: translate3d(3%, 2%, 0) scale(1.04); } }
@keyframes immersiveMetalShift { from { background-position: 0% 50%, 0 0, 0 0, 0 0; filter: saturate(.94) contrast(1.02); } to { background-position: 100% 50%, 0 0, 0 0, 0 0; filter: saturate(1.1) contrast(1.08); } }
@keyframes immersiveMetalSheen { from { transform: translate3d(-18%, 0, 0) rotate(-3deg); opacity: .45; } to { transform: translate3d(18%, 0, 0) rotate(-3deg); opacity: .88; } }
@media (prefers-reduced-motion: reduce) { .immersive-backdrop::before, .immersive-backdrop::after, .immersive-backdrop__wash { animation: none; } }
</style>
