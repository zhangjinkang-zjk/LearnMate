<template>
  <main class="home-cover">
    <section
      class="hero"
      :class="{ 'is-open': isOpen }"
      aria-label="LearnMate home"
    >
      <div class="background-word" aria-hidden="true">
        <span>LEARN</span>
        <span>MATE</span>
      </div>

      <div class="hero-copy">
        <p class="kicker">PERSONAL LEARNING COMPANION</p>
        <h1>LearnMate</h1>
        <p class="tagline">
          Make every study session feel a little more alive.
        </p>
      </div>

      <router-link class="login-link" to="/profile">
        <span>LOGIN</span>
        <span class="login-arrow" aria-hidden="true">↗</span>
      </router-link>

      <div class="object-field" aria-label="Learning tools">
        <button
          v-for="item in floatingItems"
          :key="item.file"
          class="floating-item"
          :class="{ 'is-link': item.to }"
          type="button"
          :aria-label="item.label"
          :title="item.label"
          :style="item.style"
          @click="openItem(item)"
        >
          <img :src="item.image" :alt="item.label" draggable="false" />
        </button>
      </div>

      <div class="backpack-stage" :class="{ 'is-open': isOpen }">
        <button
          class="backpack-trigger"
          type="button"
          aria-label="Replay the backpack animation"
          @click="replayAnimation"
        >
          <img
            class="backpack-image"
            :src="backpackImage"
            alt="LearnMate backpack"
            draggable="false"
          />
        </button>
      </div>

      <div class="platform" aria-hidden="true">
        <span class="platform-top"></span>
        <span class="platform-edge"></span>
      </div>

      <router-link class="enter-link" to="/chat">
        <span>LET'S GO</span>
        <span class="enter-arrow" aria-hidden="true">↗</span>
      </router-link>
    </section>
  </main>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import tabletImage from "../assets/homepic/kr-100.png";
import laptopImage from "../assets/homepic/kr-65.png";
import monitorImage from "../assets/homepic/kr-68.png";
import headsetImage from "../assets/homepic/kr-75.png";
import routerImage from "../assets/homepic/kr-76.png";
import keyboardImage from "../assets/homepic/kr-84.png";
import mouseImage from "../assets/homepic/kr-89.png";
import penTabletImage from "../assets/homepic/kr-93.png";
import gpuImage from "../assets/homepic/kr-94.png";
import fanImage from "../assets/homepic/kr-95.png";
import backpackImage from "../assets/homepic/65f0199b0fe8d.png";

const router = useRouter();
const isOpen = ref(false);

const item = (image, file, label, x, y, rotate, size, delay, to = "") => ({
  image,
  file,
  label,
  to,
  style: {
    "--x": x,
    "--y": y,
    "--r": `${rotate}deg`,
    "--size": `${size}px`,
    "--delay": `${delay}ms`,
  },
});

const floatingItems = [
  item(
    tabletImage,
    "kr-100-a.png",
    "Learning path",
    "-26vw",
    "-19vh",
    -16,
    112,
    80,
    "/learning-path"
  ),
  item(
    laptopImage,
    "kr-65-a.png",
    "AI chat",
    "-16vw",
    "-25vh",
    12,
    108,
    150,
    "/chat"
  ),
  item(
    monitorImage,
    "kr-68-a.png",
    "Resource center",
    "16vw",
    "-24vh",
    11,
    114,
    220,
    "/resources"
  ),
  item(
    headsetImage,
    "kr-75-a.png",
    "Study room",
    "27vw",
    "-17vh",
    18,
    110,
    290,
    "/study-room"
  ),
  item(
    routerImage,
    "kr-76-a.png",
    "LearnMate network",
    "-29vw",
    "-2vh",
    -11,
    108,
    360
  ),
  item(
    keyboardImage,
    "kr-84-a.png",
    "Practice keyboard",
    "-20vw",
    "13vh",
    -8,
    126,
    430,
    "/chat"
  ),
  item(
    mouseImage,
    "kr-89-a.png",
    "Learning situation",
    "24vw",
    "2vh",
    12,
    106,
    500,
    "/learning-situation"
  ),
  item(
    penTabletImage,
    "kr-93-a.png",
    "Notes and review",
    "18vw",
    "15vh",
    -12,
    116,
    570,
    "/learning-resources"
  ),
  item(
    gpuImage,
    "kr-94-a.png",
    "Resource generation",
    "-4vw",
    "-29vh",
    7,
    112,
    640,
    "/resources"
  ),
  item(
    fanImage,
    "kr-95-a.png",
    "Focus mode",
    "4vw",
    "21vh",
    -8,
    116,
    710,
    "/study-room"
  ),
  item(
    tabletImage,
    "kr-100-b.png",
    "Learning path detail",
    "-12vw",
    "-3vh",
    9,
    92,
    780,
    "/learning-path"
  ),
  item(
    monitorImage,
    "kr-68-b.png",
    "Resource preview",
    "12vw",
    "-4vh",
    -9,
    94,
    850,
    "/resources"
  ),
  item(
    laptopImage,
    "kr-65-b.png",
    "Study notes",
    "-11vw",
    "16vh",
    -13,
    94,
    920,
    "/learning-resources"
  ),
  item(
    headsetImage,
    "kr-75-b.png",
    "Focus listening",
    "11vw",
    "17vh",
    14,
    96,
    990,
    "/study-room"
  ),
];

const openItem = (target) => {
  if (target.to) router.push(target.to);
};

onMounted(() => {
  window.setTimeout(() => {
    isOpen.value = true;
  }, 420);
});

const replayAnimation = () => {
  isOpen.value = false;
  window.setTimeout(() => {
    isOpen.value = true;
  }, 180);
};
</script>

<style scoped>
@font-face {
  font-family: "Smiley Sans";
  src: url("../assets/fonts/SmileySans-Oblique.woff2") format("woff2");
  font-weight: 400 900;
  font-style: oblique;
  font-display: swap;
}

.home-cover {
  min-height: 100%;
  overflow: hidden;
  color: #f3f0e7;
  background: #1e3c34 !important;
  font-family: Inter, "Helvetica Neue", Arial, sans-serif;
}

.hero {
  position: relative;
  min-height: 100vh;
  overflow: hidden;
  isolation: isolate;
  display: grid;
  place-items: center;
  padding: 34px 28px 38px;
}

.hero::before {
  content: "";
  position: absolute;
  inset: 0;
  z-index: -2;
  pointer-events: none;
  background: radial-gradient(
      ellipse 72% 86% at -5% 104%,
      rgba(121, 162, 126, 0.36),
      transparent 68%
    ),
    radial-gradient(
      ellipse 62% 76% at 106% -4%,
      rgba(6, 25, 19, 0.62),
      transparent 70%
    ),
    radial-gradient(
      circle at 50% 42%,
      rgba(107, 151, 119, 0.2),
      transparent 31%
    ),
    linear-gradient(124deg, rgba(124, 161, 129, 0.22), transparent 38%), #1e3c34;
}

.hero::after {
  content: "";
  position: absolute;
  inset: 0;
  z-index: 8;
  pointer-events: none;
  opacity: 0.18;
  background-image: radial-gradient(
    rgba(226, 244, 82, 0.18) 0.7px,
    transparent 0.7px
  );
  background-size: 6px 6px;
  mix-blend-mode: screen;
}

.background-word {
  position: absolute;
  inset: 8% 0 0;
  z-index: -1;
  display: grid;
  align-content: center;
  justify-items: center;
  color: rgba(173, 198, 178, 0.35);
  font-family: Georgia, "Times New Roman", serif;
  font-size: clamp(116px, 17.5vw, 282px);
  font-weight: 400;
  letter-spacing: -0.045em;
  line-height: 0.76;
  user-select: none;
}

.background-word span {
  display: block;
  transform: scaleX(1.08);
}

.hero-copy {
  position: absolute;
  top: 8%;
  z-index: 4;
  text-align: center;
  pointer-events: none;
}

.kicker {
  margin: 0 0 10px;
  color: #e2f452;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.2em;
}

.hero-copy h1 {
  margin: 0;
  color: #f3f0e7;
  font-family: "Smiley Sans", Georgia, serif;
  font-size: clamp(42px, 5vw, 76px);
  font-weight: 800;
  letter-spacing: 0;
  line-height: 0.9;
}

.tagline {
  margin: 12px 0 0;
  color: rgba(243, 240, 231, 0.72);
  font-size: 12px;
  letter-spacing: 0.02em;
}

.login-link {
  position: absolute;
  top: 28px;
  right: clamp(22px, 5vw, 74px);
  z-index: 10;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #e2f452;
  font-size: 11px;
  font-weight: 850;
  letter-spacing: 0.14em;
  text-decoration: none;
  transition: color 0.2s ease, transform 0.2s ease;
}

.login-link:hover {
  color: #fff8c2;
  transform: translateY(-2px);
}

.login-arrow {
  font-size: 18px;
  line-height: 0.7;
}

.object-field {
  position: absolute;
  inset: 6% 0 10%;
  z-index: 5;
  pointer-events: none;
  transform: translateY(9vh);
}

.floating-item {
  position: absolute;
  left: 50%;
  top: 50%;
  width: var(--size);
  height: var(--size);
  padding: 0;
  border: 0;
  background: transparent;
  opacity: 0;
  pointer-events: none;
  transform: translate(-50%, -50%) translate(0, 38px) scale(0.08) rotate(0deg);
  transition: transform 1.15s cubic-bezier(0.17, 0.84, 0.35, 1.16) var(--delay),
    opacity 0.5s ease var(--delay);
}

.floating-item img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
  filter: drop-shadow(0 16px 14px rgba(4, 20, 15, 0.34));
  user-select: none;
}

.is-open .floating-item img {
  animation: item-drift 5.6s ease-in-out infinite;
  animation-delay: calc(var(--delay) + 1.35s);
}

.is-open .floating-item {
  opacity: 1;
  pointer-events: auto;
  transform: translate(-50%, -50%) translate(var(--x), var(--y)) scale(1)
    rotate(var(--r));
}

.floating-item:hover {
  z-index: 2;
  transform: translate(-50%, -50%) translate(var(--x), var(--y)) scale(1.08)
    rotate(var(--r));
}

@keyframes item-drift {
  0%,
  100% {
    transform: translate3d(0, 0, 0) rotate(0deg);
  }

  50% {
    transform: translate3d(0, -7px, 0) rotate(1.5deg);
  }
}

.backpack-stage {
  position: absolute;
  left: 50%;
  bottom: 23%;
  z-index: 6;
  width: min(360px, 40vw);
  height: min(250px, 28vh);
  transform: translateX(-50%);
  perspective: 900px;
  pointer-events: none;
}

.backpack-trigger {
  position: absolute;
  left: 50%;
  bottom: -6px;
  width: min(460px, 45vw);
  height: min(340px, 38vh);
  padding: 0;
  border: 0;
  background: transparent;
  transform: translateX(-50%) translateY(18px) scale(0.08);
  cursor: pointer;
  pointer-events: auto;
  filter: drop-shadow(0 24px 18px rgba(3, 16, 12, 0.46));
  opacity: 0;
  transition: transform 1.25s cubic-bezier(0.17, 0.84, 0.35, 1.1),
    opacity 0.55s ease;
}

.backpack-image {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
  user-select: none;
}

.backpack-stage.is-open .backpack-trigger {
  opacity: 1;
  transform: translateX(-50%) translateY(-28px) scale(1);
}

.backpack-stage.is-open .backpack-image {
  animation: backpack-drift 5.8s ease-in-out 1.3s infinite;
}

@keyframes backpack-drift {
  0%,
  100% {
    transform: translateY(0) rotate(0deg);
  }

  50% {
    transform: translateY(-8px) rotate(-1deg);
  }
}

.box-shell {
  position: absolute;
  left: 50%;
  bottom: 0;
  width: 212px;
  height: 156px;
  display: block;
  transform: translateX(-50%) rotateX(9deg) rotateZ(-4deg);
  transform-style: preserve-3d;
}

.box-body {
  position: absolute;
  left: 0;
  bottom: 0;
  width: 100%;
  height: 112px;
  display: block;
  overflow: hidden;
  border: 2px solid #0d241e;
  border-radius: 6px 6px 12px 12px;
  background: linear-gradient(145deg, #bacd4a 0%, #8da32d 56%, #50671e 100%);
  box-shadow: inset 8px 0 0 rgba(237, 248, 145, 0.2),
    inset -13px -10px 0 rgba(32, 57, 20, 0.22), 0 10px 0 #31471a;
  transform: translateZ(0);
}

.box-inner-glow {
  position: absolute;
  left: 15px;
  right: 15px;
  top: 9px;
  height: 23px;
  border-radius: 50%;
  background: radial-gradient(
    ellipse,
    rgba(23, 48, 35, 0.95),
    rgba(23, 48, 35, 0.2) 72%,
    transparent 73%
  );
  opacity: 0.9;
  transition: opacity 0.45s ease 0.3s;
}

.is-open .box-inner-glow {
  opacity: 1;
}

.box-front-face {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: end center;
  padding-bottom: 20px;
  color: rgba(27, 51, 30, 0.76);
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.24em;
}

.box-side-face {
  position: absolute;
  right: -17px;
  top: 10px;
  width: 17px;
  height: 99px;
  border-radius: 0 5px 9px 0;
  background: linear-gradient(180deg, #789021, #3a5119);
  transform: skewY(-24deg);
  transform-origin: left top;
}

.box-lid {
  position: absolute;
  left: -1px;
  top: 5px;
  z-index: 2;
  width: 214px;
  height: 52px;
  display: block;
  border: 2px solid #0d241e;
  border-radius: 7px;
  transform-origin: 12% 92%;
  transform-style: preserve-3d;
  transition: transform 0.95s cubic-bezier(0.2, 0.82, 0.25, 1),
    box-shadow 0.95s ease;
}

.box-lid-face {
  position: absolute;
  inset: 0;
  display: block;
  border-radius: 5px;
  background: linear-gradient(145deg, #d9eb67 0%, #a7ba3a 60%, #718723 100%);
  box-shadow: inset 0 4px 0 rgba(248, 255, 174, 0.36),
    inset -10px -8px 0 rgba(39, 64, 19, 0.16);
}

.box-lid-highlight {
  position: absolute;
  left: 12px;
  right: 34px;
  top: 8px;
  height: 5px;
  display: block;
  border-radius: 50%;
  background: rgba(255, 255, 208, 0.42);
  transform: skewX(-22deg);
}

.is-open .box-lid {
  transform: translate(-7px, -42px) rotate(-34deg) rotateX(16deg);
  box-shadow: -9px 22px 10px rgba(3, 16, 12, 0.25);
}

.box-mark {
  position: absolute;
  left: 50%;
  top: 50%;
  z-index: 1;
  color: #1e3c34;
  font-family: Georgia, serif;
  font-size: 22px;
  font-weight: 800;
  letter-spacing: 0.08em;
  transform: translate(-50%, -50%);
}

.platform {
  position: absolute;
  left: 50%;
  bottom: 6%;
  z-index: 3;
  width: min(420px, 44vw);
  height: 54px;
  transform: translateX(-50%);
  filter: drop-shadow(0 24px 18px rgba(3, 16, 12, 0.42));
}

.platform-top,
.platform-edge {
  position: absolute;
  left: 50%;
  display: block;
  transform: translateX(-50%);
}

.platform-top {
  top: 0;
  width: 90%;
  height: 38px;
  border-radius: 50%;
  background: #e2f452;
  box-shadow: inset 0 -9px 0 rgba(123, 143, 22, 0.28),
    0 0 0 1px rgba(238, 255, 125, 0.2);
}

.platform-edge {
  top: 25px;
  width: 84%;
  height: 24px;
  border-radius: 0 0 50% 50%;
  background: #a3b92c;
  z-index: -1;
}

.enter-link {
  position: absolute;
  right: clamp(22px, 5vw, 74px);
  bottom: 30px;
  z-index: 7;
  display: inline-flex;
  align-items: center;
  gap: 9px;
  min-height: 48px;
  padding: 0 20px 0 22px;
  border-radius: 5px;
  background: #e2f452;
  color: #1e3c34;
  font-size: 13px;
  font-weight: 900;
  letter-spacing: 0.12em;
  text-decoration: none;
  box-shadow: 0 12px 26px rgba(4, 20, 15, 0.3), inset 0 1px 0 rgba(255, 255, 210, 0.62);
  transition: color 0.2s ease, background 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;
}

.enter-link:hover {
  background: #f0ff75;
  color: #152f28;
  transform: translateY(-2px);
  box-shadow: 0 16px 30px rgba(4, 20, 15, 0.38), inset 0 1px 0 rgba(255, 255, 210, 0.72);
}

.enter-arrow {
  font-size: 20px;
  line-height: 0.65;
}

@media (max-width: 840px) {
  .hero {
    min-height: 100vh;
    padding-inline: 16px;
  }

  .background-word {
    font-size: 22vw;
  }

  .hero-copy {
    top: 7%;
  }

  .login-link {
    top: 20px;
    right: 22px;
  }

  .tagline {
    font-size: 11px;
  }

  .floating-item {
    --size: 110px !important;
  }

  .platform {
    width: min(360px, 58vw);
    bottom: 9%;
  }

  .backpack-stage {
    width: min(330px, 56vw);
    bottom: 24%;
  }

  .enter-link {
    right: 50%;
    bottom: 20px;
    transform: translateX(50%);
  }

  .enter-link:hover {
    transform: translate(50%, -2px);
  }
}

@media (max-width: 560px) {
  .hero-copy h1 {
    font-size: 48px;
  }

  .kicker {
    font-size: 8px;
  }

  .background-word {
    inset: 14% 0 0;
    font-size: 25vw;
  }

  .object-field {
    inset: 10% -10% 14%;
  }

  .floating-item {
    --size: 84px !important;
  }

  .platform {
    width: 270px;
    bottom: 12%;
  }

  .backpack-stage {
    width: 260px;
    height: 220px;
    bottom: 26%;
  }

  .backpack-trigger {
    transform: translateX(-50%) scale(0.82);
  }
}

@media (prefers-reduced-motion: reduce) {
  .floating-item,
  .enter-link {
    transition-duration: 0.01ms !important;
  }
}
</style>
