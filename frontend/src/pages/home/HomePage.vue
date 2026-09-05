<template>
  <main class="home-cover">
    <section
      class="hero"
      :class="{ 'is-open': isOpen, 'is-collected': isCollected }"
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

      <button class="login-link" type="button" @click="handleTopLogin">
        <span>{{ isAuthenticated ? (displayUsername || "ACCOUNT") : "LOGIN" }}</span>
        <span class="login-arrow" aria-hidden="true">↗</span>
      </button>

      <div class="object-field" aria-label="Learning tools">
        <div
          v-for="item in floatingItems"
          :key="item.file"
          class="floating-item"
          role="img"
          :aria-label="item.label"
          :title="item.label"
          :style="item.style"
        >
          <img :src="item.image" :alt="item.label" draggable="false" />
        </div>
      </div>

      <div class="backpack-stage" :class="{ 'is-open': isOpen, 'is-collected': isCollected }">
        <button
          class="backpack-trigger"
          type="button"
          :aria-label="isCollected ? 'Release the learning tools' : 'Collect the learning tools'"
          :aria-pressed="isCollected"
          @click="toggleBackpack"
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

      <p v-if="entryMessage" class="entry-status" role="status">{{ entryMessage }}</p>
      <button class="enter-link" type="button" :disabled="isEntering" @click="handleEnter">
        <span>{{ isEntering ? "PREPARING" : "LET'S GO" }}</span>
        <span class="enter-arrow" aria-hidden="true">↗</span>
      </button>

      <div v-if="isLoginOpen" class="login-modal-backdrop" @click.self="closeLogin">
        <section class="login-modal" role="dialog" aria-modal="true" aria-labelledby="login-modal-title">
          <button class="login-modal-close" type="button" aria-label="Close login" @click="closeLogin">×</button>
          <p class="login-modal-kicker">LEARNMATE ACCESS</p>
          <h2 id="login-modal-title">{{ isRegistering ? "Create your account" : "Welcome back" }}</h2>
          <p class="login-modal-intro">
            {{ isRegistering ? "Save your learning path and keep your progress in sync." : "Log in to continue your learning journey." }}
          </p>
          <form class="login-modal-form" @submit.prevent="submitLogin">
            <label>
              <span>USERNAME</span>
              <input v-model.trim="loginUsername" type="text" autocomplete="username" required />
            </label>
            <label v-if="isRegistering">
              <span>EMAIL</span>
              <input v-model.trim="loginEmail" type="email" autocomplete="email" required />
            </label>
            <label v-if="isRegistering">
              <span>EMAIL CODE</span>
              <div class="login-modal-code-row">
                <input v-model.trim="loginCode" inputmode="numeric" autocomplete="one-time-code" maxlength="6" required />
                <button class="login-modal-code" type="button" :disabled="isSendingCode || codeCountdown > 0 || !loginEmail" @click="sendCode">
                  {{ isSendingCode ? "SENDING" : codeCountdown > 0 ? `${codeCountdown}s` : "GET CODE" }}
                </button>
              </div>
            </label>
            <label>
              <span>PASSWORD</span>
              <input v-model="loginPassword" type="password" :autocomplete="isRegistering ? 'new-password' : 'current-password'" required />
            </label>
            <label v-if="isRegistering">
              <span>CONFIRM PASSWORD</span>
              <input v-model="loginConfirmPassword" type="password" autocomplete="new-password" required />
            </label>
            <p v-if="loginError" class="login-modal-error">{{ loginError }}</p>
            <button class="login-modal-submit" type="submit" :disabled="isLoggingIn">
              <span>{{ isLoggingIn ? (isRegistering ? "CREATING..." : "LOGGING IN...") : (isRegistering ? "CREATE ACCOUNT" : "LOGIN") }}</span>
              <span aria-hidden="true">↗</span>
            </button>
          </form>
          <button class="login-modal-register" type="button" @click="toggleAuthMode">
            {{ isRegistering ? "Already have an account? Log in" : "Create an account" }}
          </button>
        </section>
      </div>
    </section>
  </main>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { authApi } from "../../shared/api/authApi";
import { learningApi } from "../../shared/api/learningApi";

import tabletImage from "../../shared/assets/home/hdi-circle-8e23f1ab774009a1e1d254d85249c2f3-7g50i6bj4rpq-cutout.png";
import laptopImage from "../../shared/assets/home/Late_2016_MacBook_Pro-cutout.png";
import monitorImage from "../../shared/assets/home/800x-cutout.png";
import headsetImage from "../../shared/assets/home/airpods-red-cutout.png";
import headsetAltImage from "../../shared/assets/home/airpods-red-alt-cutout.png";
import routerImage from "../../shared/assets/home/493349971887985986-cutout.png";
import keyboardImage from "../../shared/assets/home/GSKBC065E_ML-cutout.png";
import mouseImage from "../../shared/assets/home/mouse-red-cutout.png";
import penTabletImage from "../../shared/assets/home/IBM_PC-IMG_7271_(transparent).png";
import gpuImage from "../../shared/assets/home/Sapphire-Radeon-HD-5570-Video-Card-cutout.png";
import fanImage from "../../shared/assets/home/493349971887985986-cutout.png";
import backpackImage from "../../shared/assets/home/65f0199b0fe8d.png";

const router = useRouter();
const isOpen = ref(false);
const isCollected = ref(false);
const isLoginOpen = ref(false);
const isAuthenticated = ref(Boolean(localStorage.getItem("token")));
const displayUsername = ref(localStorage.getItem("learnmate_username") || "");
const isLoggingIn = ref(false);
const loginUsername = ref("");
const loginEmail = ref("");
const loginCode = ref("");
const loginPassword = ref("");
const loginConfirmPassword = ref("");
const isRegistering = ref(false);
const isSendingCode = ref(false);
const codeCountdown = ref(0);
let codeTimer;
const loginError = ref("");
const loginIntent = ref("overview");
const isEntering = ref(false);
const entryMessage = ref("");

const openLogin = (intent = "overview") => {
  loginIntent.value = intent;
  loginError.value = "";
  isLoginOpen.value = true;
};

const handleTopLogin = () => {
  if (isAuthenticated.value) {
    void enterLearningSpace();
    return;
  }
  openLogin("overview");
};

const getResponseData = response => response?.data?.data ?? response?.data ?? response;
const hasOverviewContent = overview => Boolean(
  overview?.path?.id ||
  (Array.isArray(overview?.subjects) && overview.subjects.some(subject => subject?.id || subject?.name)),
);

const enterLearningSpace = async () => {
  if (isEntering.value) return;
  isEntering.value = true;
  entryMessage.value = "";
  let hasSavedProfile = Boolean(
    String(localStorage.getItem("learnmate_direction") || "").trim(),
  );
  try {
    const currentPathResponse = await learningApi.getCurrentPath();
    const currentPath = getResponseData(currentPathResponse);
    if (currentPath?.path_id) {
      await router.push("/learning/overview");
      return;
    }

    // 画像已经保存但路径生成中断时，复用服务端画像自动补建路径，避免回到首次定向。
    const overviewResponse = await learningApi.getOverview();
    const overview = getResponseData(overviewResponse);
    const profile = overview?.profile || {};
    hasSavedProfile = hasSavedProfile || Boolean(String(profile.direction || "").trim());
    if (String(profile.direction || "").trim()) {
      const generatedResponse = await learningApi.generatePathsFromDirection(profile.direction, profile.goal || "");
      const generated = getResponseData(generatedResponse);
      const hasPath = Array.isArray(generated?.paths) && generated.paths.some(path => path?.path_id);
      if (hasPath) {
        const refreshedOverview = getResponseData(await learningApi.getOverview());
        if (hasOverviewContent(refreshedOverview)) {
          localStorage.setItem("learnmate_onboarding_complete", "1");
          await router.push("/learning/overview");
          return;
        }
      }
    }
  } catch {
    // 已有画像时保留当前入口，允许用户稍后重试生成，不再回到首次定向形成循环。
    if (hasSavedProfile) {
      entryMessage.value = "学习概览正在准备，请稍后再次进入。";
      return;
    }
  } finally {
    isEntering.value = false;
  }
  if (hasSavedProfile) {
    entryMessage.value = "学习概览正在准备，请稍后再次进入。";
    return;
  }
  await router.push(`/select-identity?fresh=${Date.now()}`);
};

const handleEnter = () => {
  if (isAuthenticated.value) {
    void enterLearningSpace();
    return;
  }
  openLogin("identity");
};

const closeLogin = () => {
  if (isLoggingIn.value) return;
  isLoginOpen.value = false;
};

const toggleAuthMode = () => {
  isRegistering.value = !isRegistering.value;
  loginEmail.value = "";
  loginCode.value = "";
  loginPassword.value = "";
  loginConfirmPassword.value = "";
  loginError.value = "";
  if (codeTimer) window.clearInterval(codeTimer);
  codeTimer = undefined;
  codeCountdown.value = 0;
};

const sendCode = async () => {
  if (isSendingCode.value || codeCountdown.value > 0 || !loginEmail.value) return;
  isSendingCode.value = true;
  loginError.value = "";
  try {
    await authApi.sendEmailCode(loginEmail.value);
    codeCountdown.value = 60;
    codeTimer = window.setInterval(() => {
      codeCountdown.value -= 1;
      if (codeCountdown.value <= 0) {
        window.clearInterval(codeTimer);
        codeTimer = undefined;
      }
    }, 1000);
  } catch (error) {
    loginError.value = error?.message || "Could not send the code.";
  } finally {
    isSendingCode.value = false;
  }
};

const submitLogin = async () => {
  if (isLoggingIn.value) return;
  isLoggingIn.value = true;
  loginError.value = "";
  try {
    if (isRegistering.value && loginPassword.value !== loginConfirmPassword.value) {
      throw new Error("Passwords do not match.");
    }
    const data = isRegistering.value
      ? await authApi.registerByEmail(loginUsername.value, loginEmail.value, loginPassword.value, loginCode.value)
      : await authApi.login(loginUsername.value, loginPassword.value);
    localStorage.setItem("token", data.token);
    const username = data.username || loginUsername.value;
    if (username) {
      localStorage.setItem("learnmate_username", username);
      displayUsername.value = username;
    }
    isAuthenticated.value = true;
    isLoginOpen.value = false;
    await enterLearningSpace();
  } catch (error) {
    loginError.value = error?.message || "Login failed. Please try again.";
  } finally {
    isLoggingIn.value = false;
  }
};

onBeforeUnmount(() => {
  if (codeTimer) window.clearInterval(codeTimer);
});

const item = (image, file, label, x, y, rotate, size, delay) => ({
  image,
  file,
  label,
  style: {
    "--x": x,
    "--y": y,
    "--r": `${rotate}deg`,
    "--size": `${size}px`,
    "--delay": `${delay}ms`,
    "--collect-delay": `${Math.round(delay * 0.35)}ms`,
  },
});

const floatingItems = [
  item(
    tabletImage,
    "hdi-board-a.png",
    "Learning path",
    "16vw",
    "-24vh",
    -16,
    132,
    80
  ),
  item(
    laptopImage,
    "macbook-a.png",
    "AI chat",
    "-16vw",
    "-25vh",
    12,
    127,
    150
  ),
  item(
    monitorImage,
    "speakers-a.png",
    "Resource center",
    "-26vw",
    "-19vh",
    11,
    135,
    220
  ),
  item(
    headsetImage,
    "airpods-red-a.png",
    "Study room",
    "27vw",
    "-17vh",
    18,
    130,
    290
  ),
  item(
    routerImage,
    "chip-a.png",
    "LearnMate network",
    "24vw",
    "2vh",
    -11,
    127,
    360
  ),
  item(
    keyboardImage,
    "keyboard-a.png",
    "Practice keyboard",
    "-20vw",
    "13vh",
    -8,
    149,
    430
  ),
  item(
    mouseImage,
    "mouse-red-a.png",
    "Learning situation",
    "-25vw",
    "1vh",
    12,
    200,
    500
  ),
  item(
    penTabletImage,
    "ibm-pc-a.png",
    "Notes and review",
    "18vw",
    "15vh",
    -12,
    137,
    570
  ),
  item(
    gpuImage,
    "gpu-a.png",
    "Resource generation",
    "-4vw",
    "-29vh",
    7,
    132,
    640
  ),
  item(
    fanImage,
    "chip-b.png",
    "Focus mode",
    "4vw",
    "21vh",
    -8,
    137,
    710
  ),
  item(
    tabletImage,
    "hdi-board-b.png",
    "Learning path detail",
    "-12vw",
    "-3vh",
    9,
    108,
    780
  ),
  item(
    monitorImage,
    "speakers-b.png",
    "Resource preview",
    "12vw",
    "-4vh",
    -9,
    111,
    850
  ),
  item(
    laptopImage,
    "macbook-b.png",
    "Study notes",
    "-11vw",
    "16vh",
    -13,
    111,
    920
  ),
  item(
    headsetAltImage,
    "airpods-red-alt-b.png",
    "Focus listening",
    "11vw",
    "17vh",
    14,
    113,
    990
  ),
];

onMounted(() => {
  window.setTimeout(() => {
    isOpen.value = true;
  }, 420);
});

const toggleBackpack = () => {
  isCollected.value = !isCollected.value;
};
</script>

<style scoped>
@font-face {
  font-family: "Smiley Sans";
  src: url("../../shared/assets/fonts/SmileySans-Oblique.woff2") format("woff2");
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
  padding: 0;
  border: 0;
  background: transparent;
  font-family: inherit;
  cursor: pointer;
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

.is-collected .floating-item {
  opacity: 0;
  pointer-events: none;
  transform: translate(-50%, -50%) translate(0, 12vh) scale(0.08) rotate(0deg);
  transition-delay: var(--collect-delay);
}

.floating-item:hover {
  z-index: 2;
  transform: translate(-50%, -50%) translate(var(--x), var(--y)) scale(1.08)
    rotate(var(--r));
}

.is-collected .floating-item:hover {
  transform: translate(-50%, -50%) translate(0, 12vh) scale(0.08) rotate(0deg);
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
  pointer-events: none;
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
  pointer-events: auto;
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
  border: 0;
  font-family: inherit;
  cursor: pointer;
  box-shadow: 0 12px 26px rgba(4, 20, 15, 0.3), inset 0 1px 0 rgba(255, 255, 210, 0.62);
  transition: color 0.2s ease, background 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;
}

.enter-link:hover {
  background: #f0ff75;
  color: #152f28;
  transform: translateY(-2px);
  box-shadow: 0 16px 30px rgba(4, 20, 15, 0.38), inset 0 1px 0 rgba(255, 255, 210, 0.72);
}

.enter-link:disabled {
  cursor: wait;
  opacity: 0.72;
}

.entry-status {
  position: absolute;
  right: clamp(22px, 5vw, 74px);
  bottom: 88px;
  z-index: 7;
  max-width: min(300px, calc(100vw - 44px));
  margin: 0;
  color: rgba(243, 240, 231, 0.82);
  font-size: 12px;
  line-height: 1.5;
  text-align: right;
}

.enter-arrow {
  font-size: 20px;
  line-height: 0.65;
}

.login-modal-backdrop {
  position: absolute;
  inset: 0;
  z-index: 30;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(5, 23, 17, 0.62);
  backdrop-filter: blur(5px) saturate(1.08);
  animation: modalFadeIn 0.35s ease both;
}

.login-modal {
  position: relative;
  width: min(430px, 100%);
  padding: 34px 36px 30px;
  border: 1px solid rgba(226, 244, 82, 0.34);
  border-radius: 24px;
  background:
    radial-gradient(circle at 86% 8%, rgba(226, 244, 82, 0.2), transparent 38%),
    linear-gradient(145deg, rgba(36, 76, 58, 0.98), rgba(11, 37, 27, 0.98));
  color: #f3f0e7;
  box-shadow: 0 32px 90px rgba(2, 14, 9, 0.54), inset 0 1px 0 rgba(243, 240, 231, 0.08);
  animation: modalRiseIn 0.55s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.login-modal-close {
  position: absolute;
  top: 16px;
  right: 18px;
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: 50%;
  background: rgba(243, 240, 231, 0.1);
  color: rgba(243, 240, 231, 0.76);
  font-size: 22px;
  line-height: 1;
  cursor: pointer;
  transition: transform 0.3s ease, background 0.3s ease, color 0.3s ease;
}

.login-modal-close:hover {
  background: rgba(226, 244, 82, 0.2);
  color: #e2f452;
  transform: rotate(90deg);
}

.login-modal-kicker {
  margin: 0 0 12px;
  color: #e2f452;
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.2em;
}

.login-modal h2 {
  margin: 0;
  font-family: "Smiley Sans", Georgia, serif;
  font-size: clamp(32px, 5vw, 46px);
  font-weight: 700;
  line-height: 0.98;
}

.login-modal-intro {
  margin: 14px 0 26px;
  color: rgba(243, 240, 231, 0.7);
  font-size: 13px;
  line-height: 1.6;
}

.login-modal-form {
  display: grid;
  gap: 16px;
}

.login-modal-form label {
  display: grid;
  gap: 7px;
}

.login-modal-form label span {
  color: rgba(243, 240, 231, 0.68);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.16em;
}

.login-modal-form input {
  width: 100%;
  min-height: 48px;
  padding: 0 15px;
  border: 1px solid rgba(243, 240, 231, 0.2);
  border-radius: 12px;
  background: rgba(4, 22, 15, 0.5);
  color: #f3f0e7;
  outline: none;
  font: inherit;
  font-size: 14px;
  transition: border-color 0.3s ease, background 0.3s ease, box-shadow 0.3s ease;
}

.login-modal-form input:focus {
  border-color: rgba(226, 244, 82, 0.82);
  background: rgba(4, 22, 15, 0.7);
  box-shadow: 0 0 0 4px rgba(226, 244, 82, 0.1);
}

.login-modal-code-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
}

.login-modal-code {
  min-width: 92px;
  padding: 0 12px;
  border: 1px solid rgba(226, 244, 82, 0.42);
  border-radius: 12px;
  background: rgba(226, 244, 82, 0.12);
  color: #e2f452;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.08em;
  cursor: pointer;
  transition: background 0.25s ease, border-color 0.25s ease, opacity 0.25s ease;
}

.login-modal-code:hover:not(:disabled) {
  border-color: #e2f452;
  background: rgba(226, 244, 82, 0.22);
}

.login-modal-code:disabled {
  cursor: wait;
  opacity: 0.45;
}

.login-modal-error {
  margin: -2px 0 0;
  color: #ffb5a8;
  font-size: 12px;
  line-height: 1.4;
}

.login-modal-submit {
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  min-height: 52px;
  margin-top: 3px;
  padding: 0 18px 0 20px;
  border: 0;
  border-radius: 999px;
  background: #e2f452;
  color: #1e3c34;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.14em;
  cursor: pointer;
  box-shadow: 0 14px 28px rgba(2, 15, 10, 0.26);
  transition: transform 0.35s cubic-bezier(0.16, 1, 0.3, 1), background 0.3s ease, box-shadow 0.3s ease;
}

.login-modal-submit:hover:not(:disabled) {
  background: #b3f884;
  transform: translateY(-3px) scale(1.015);
  box-shadow: 0 20px 34px rgba(2, 15, 10, 0.34);
}

.login-modal-submit:disabled {
  cursor: wait;
  opacity: 0.55;
}

.login-modal-submit span:last-child {
  font-size: 20px;
  line-height: 0.65;
}

.login-modal-register {
  display: block;
  margin: 18px auto 0;
  border: 0;
  background: transparent;
  color: rgba(243, 240, 231, 0.66);
  font-size: 12px;
  cursor: pointer;
  transition: color 0.25s ease;
}

.login-modal-register:hover {
  color: #e2f452;
}

@keyframes modalFadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes modalRiseIn {
  from { opacity: 0; transform: translateY(20px) scale(0.97); }
  to { opacity: 1; transform: translateY(0) scale(1); }
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

  .entry-status {
    right: 50%;
    bottom: 78px;
    transform: translateX(50%);
    text-align: center;
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
